"""
NTFS MFT 直读扫描器 v2

通过直接读取 $MFT 文件原始数据解析每条记录，一次顺序 I/O 同时获得
文件名、父目录引用号、时间戳和 file_size，无需逐文件调用 GetFileAttributesExW。

与 v1 (FSCTL_ENUM_USN_DATA) 相比的优势：
  - file_size 从 $DATA 属性直接读取，无额外 Win32 API 调用
  - 顺序读取 $MFT，I/O 模式对移动硬盘 (USB) 极其友好
  - 路径解析使用预构建目录缓存（拓扑展开），O(1) 查找

对外接口（与 v1 完全相同）：
    is_admin()   -> bool
    scan_volume(drive_letter, batch_callback, batch_size, disk_label)
                 -> (total_count, elapsed_seconds)

要求：Windows + NTFS 格式卷 + 管理员权限
"""

import ctypes
import ctypes.wintypes as wt
import logging
import os
import struct
import time
from datetime import datetime
from typing import Callable, Iterator, Optional

from backend.utils.file_types import SHAPEFILE_EXTENSIONS, get_file_type

logger = logging.getLogger(__name__)

# ─── Windows API 常量 ──────────────────────────────────────────────────────────

GENERIC_READ                = 0x80000000
FILE_SHARE_READ             = 0x00000001
FILE_SHARE_WRITE            = 0x00000002
OPEN_EXISTING               = 3
FILE_FLAG_BACKUP_SEMANTICS  = 0x02000000   # 打开目录/系统文件需要
FILE_FLAG_SEQUENTIAL_SCAN   = 0x08000000   # 提示 OS 顺序预读

FSCTL_GET_NTFS_VOLUME_DATA      = 0x00090064
FSCTL_GET_RETRIEVAL_POINTERS    = 0x00090073   # 获取文件的 LCN Extent 列表

INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

# MFT 属性类型码
AT_STANDARD_INFORMATION = 0x10
AT_FILE_NAME            = 0x30
AT_DATA                 = 0x80
AT_END                  = 0xFFFFFFFF

# MFT 记录标志位
_FLAG_IN_USE  = 0x0001
_FLAG_IS_DIR  = 0x0002

# $FILE_NAME 命名空间（值越小优先级越高）
_NS_PRIORITY = {
    1: 0,   # Win32
    3: 0,   # Win32 & DOS（同一名称满足两种规范）
    0: 1,   # POSIX（区分大小写）
    2: 2,   # DOS 8.3（短名，尽量不用）
}

NTFS_ROOT_FRN = 5          # NTFS 根目录的 MFT 记录号固定为 5
_FT_EPOCH    = 116_444_736_000_000_000   # FILETIME 与 Unix 时间的差（100ns 间隔）


# ─── ctypes 结构体 ─────────────────────────────────────────────────────────────

class _NTFS_VOLUME_DATA(ctypes.Structure):
    """NTFS_VOLUME_DATA_BUFFER（FSCTL_GET_NTFS_VOLUME_DATA 输出）"""
    _fields_ = [
        ("VolumeSerialNumber",            ctypes.c_int64),
        ("NumberSectors",                 ctypes.c_int64),
        ("TotalClusters",                 ctypes.c_int64),
        ("FreeClusters",                  ctypes.c_int64),
        ("TotalReserved",                 ctypes.c_int64),
        ("BytesPerSector",                ctypes.c_uint32),
        ("BytesPerCluster",               ctypes.c_uint32),
        ("BytesPerFileRecordSegment",     ctypes.c_uint32),   # 通常 1024
        ("ClustersPerFileRecordSegment",  ctypes.c_uint32),
        ("MftValidDataLength",            ctypes.c_int64),    # $MFT 实际数据字节数
        ("MftStartLcn",                   ctypes.c_int64),
        ("Mft2StartLcn",                  ctypes.c_int64),
        ("MftZoneStart",                  ctypes.c_int64),
        ("MftZoneEnd",                    ctypes.c_int64),
    ]


# ─── 权限检测 ─────────────────────────────────────────────────────────────────

def is_admin() -> bool:
    """检测当前进程是否具有 Windows 管理员权限。"""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def check_admin() -> None:
    """无管理员权限时抛出 PermissionError。"""
    if not is_admin():
        raise PermissionError(
            "NTFS MFT 直读需要管理员权限，请以管理员身份运行程序。"
        )


# ─── 工具函数 ─────────────────────────────────────────────────────────────────

def _rec_num(frn: int) -> int:
    """从文件引用号 (FRN) 中提取 MFT 记录号（低 48 位）。"""
    return frn & 0x0000_FFFF_FFFF_FFFF


def _ft_to_iso(val: int) -> Optional[str]:
    """FILETIME（100ns 间隔，从 1601-01-01 起）→ ISO 8601 字符串；零值返回 None。"""
    if val <= 0:
        return None
    try:
        ts = (val - _FT_EPOCH) / 10_000_000
        return datetime.fromtimestamp(ts).isoformat()
    except (OSError, OverflowError, ValueError):
        return None


def _apply_usa_fixup(buf: bytearray, rec_size: int, sector_size: int) -> bool:
    """
    应用 Update Sequence Array (USA) 修复。

    MFT 记录写入时，每个扇区末尾 2 字节被替换为序列号以做校验；读取时需将
    其还原为原始数据。USA 偏移/计数存在记录头 offset 4/6 处。
    校验失败（磁盘错误）返回 False，否则原地修改 buf 并返回 True。
    """
    if len(buf) < 8:
        return False
    usa_off = struct.unpack_from('<H', buf, 4)[0]
    usa_cnt = struct.unpack_from('<H', buf, 6)[0]
    if usa_cnt < 2 or usa_off + usa_cnt * 2 > len(buf):
        return False
    seq = struct.unpack_from('<H', buf, usa_off)[0]
    for i in range(1, usa_cnt):
        end = i * sector_size - 2
        if end + 2 > len(buf):
            break
        if struct.unpack_from('<H', buf, end)[0] != seq:
            return False                                # 扇区末尾校验失败
        orig = struct.unpack_from('<H', buf, usa_off + i * 2)[0]
        struct.pack_into('<H', buf, end, orig)          # 还原原始数据
    return True


# ─── MFT 记录解析 ─────────────────────────────────────────────────────────────

def _parse_record(raw: bytes, rec_size: int) -> Optional[dict]:
    """
    解析单条 MFT 记录（已经过 USA 修复）。

    遍历属性链表，收集：
      $STANDARD_INFORMATION → 精确时间戳（Explorer 显示的时间）
      $FILE_NAME            → 父目录 FRN、文件名、命名空间
      $DATA                 → file_size（驻留取值长度，非驻留取 DataLength）

    返回 dict(parent_frn, name, is_dir, file_size, ctime, mtime)，
    或 None（记录未使用 / 无法解析）。
    """
    if len(raw) < 42 or raw[:4] != b'FILE':
        return None

    attrs_off = struct.unpack_from('<H', raw, 20)[0]
    flags     = struct.unpack_from('<H', raw, 22)[0]

    if not (flags & _FLAG_IN_USE):
        return None

    is_dir = bool(flags & _FLAG_IS_DIR)

    parent_frn  = None
    name        = None
    name_prio   = 999      # 当前已选名称的命名空间优先级（越小越好）
    file_size   = 0
    si_ctime    = None     # $STANDARD_INFORMATION 时间戳（更准确）
    si_mtime    = None
    fn_ctime    = None     # $FILE_NAME 时间戳（备用）
    fn_mtime    = None

    off = attrs_off
    while off + 8 <= len(raw):
        atype = struct.unpack_from('<I', raw, off)[0]
        if atype == AT_END:
            break
        alen = struct.unpack_from('<I', raw, off + 4)[0]
        if alen < 8 or off + alen > len(raw):
            break
        non_res = raw[off + 8]   # 0 = 驻留，1 = 非驻留

        # ── $STANDARD_INFORMATION（通常驻留，提供 Explorer 显示的时间戳）──
        if atype == AT_STANDARD_INFORMATION and non_res == 0:
            voff = struct.unpack_from('<H', raw, off + 20)[0]
            v = off + voff
            if v + 16 <= len(raw):
                si_ctime = _ft_to_iso(struct.unpack_from('<Q', raw, v    )[0])
                si_mtime = _ft_to_iso(struct.unpack_from('<Q', raw, v + 8)[0])

        # ── $FILE_NAME（可能有多个：Win32/DOS/POSIX，选优先级最高的）──
        elif atype == AT_FILE_NAME and non_res == 0:
            voff = struct.unpack_from('<H', raw, off + 20)[0]
            v = off + voff
            if v + 66 <= len(raw):
                fn_ns    = raw[v + 65]
                fn_nch   = raw[v + 64]
                name_end = v + 66 + fn_nch * 2
                prio     = _NS_PRIORITY.get(fn_ns, 3)
                if name_end <= len(raw) and (name is None or prio < name_prio):
                    try:
                        candidate  = raw[v + 66:name_end].decode('utf-16-le')
                        name       = candidate
                        name_prio  = prio
                        parent_frn = _rec_num(struct.unpack_from('<Q', raw, v)[0])
                        fn_ctime   = _ft_to_iso(struct.unpack_from('<Q', raw, v +  8)[0])
                        fn_mtime   = _ft_to_iso(struct.unpack_from('<Q', raw, v + 16)[0])
                        # $FILE_NAME 里的 DataSize 也可用作 file_size 备用值
                        if not is_dir:
                            fn_size = struct.unpack_from('<Q', raw, v + 48)[0]
                            if fn_size > 0:
                                file_size = fn_size
                    except UnicodeDecodeError:
                        pass

        # ── $DATA：优先于 $FILE_NAME 的 DataSize，且只取无名数据流 ──
        elif atype == AT_DATA and not is_dir:
            attr_name_len = raw[off + 9]    # 属性自身名称长度（0 = 无名主流）
            if attr_name_len == 0:
                if non_res == 0:
                    # 驻留：值长度即文件大小
                    file_size = struct.unpack_from('<I', raw, off + 16)[0]
                elif off + 56 <= len(raw):
                    # 非驻留：DataLength 在 attr+48
                    file_size = struct.unpack_from('<Q', raw, off + 48)[0]

        off += alen

    if parent_frn is None or not name:
        return None

    return {
        'parent_frn': parent_frn,
        'name':       name,
        'is_dir':     is_dir,
        'file_size':  file_size,
        # $STANDARD_INFORMATION 更准确，$FILE_NAME 作备用
        'ctime':      si_ctime or fn_ctime,
        'mtime':      si_mtime or fn_mtime,
    }


# ─── $MFT 读取 ────────────────────────────────────────────────────────────────

def _parse_data_runs(raw: bytes, offset: int, end: int, bytes_per_cluster: int) -> list[tuple[int, int]]:
    """
    解析 NTFS nonresident 属性的 data runs（运行列表）。

    Data run 格式（紧凑变长编码）：
      header byte: 高4位 = offset字段字节数(o), 低4位 = length字段字节数(l)
      后跟 l 字节的 cluster_count（无符号）和 o 字节的 lcn_offset（有符号，相对前一个）
      header=0x00 表示列表结束

    返回 [(start_byte, length_bytes), ...]，即每个 Extent 的物理起始位置和长度。
    """
    extents: list[tuple[int, int]] = []
    pos = offset
    prev_lcn = 0

    while pos < end:
        header = raw[pos]
        if header == 0:
            break
        pos += 1

        len_size = header & 0x0F       # 低 4 位：length 字段字节数
        off_size = (header >> 4) & 0x0F  # 高 4 位：offset 字段字节数

        if len_size == 0 or pos + len_size + off_size > end:
            break

        # 读 cluster_count（无符号）
        cluster_count = int.from_bytes(raw[pos:pos + len_size], 'little', signed=False)
        pos += len_size

        if off_size == 0:
            # 稀疏 run（无物理位置），跳过
            continue

        # 读 lcn_offset（有符号，相对于前一个 LCN）
        lcn_delta = int.from_bytes(raw[pos:pos + off_size], 'little', signed=True)
        pos += off_size

        lcn = prev_lcn + lcn_delta
        prev_lcn = lcn

        if lcn >= 0 and cluster_count > 0:
            extents.append((lcn * bytes_per_cluster, cluster_count * bytes_per_cluster))

    return extents


def _bootstrap_mft_extents(
    vol_handle,
    kernel32,
    mft_start_lcn: int,
    bytes_per_cluster: int,
    rec_size: int,
    sector_size: int,
) -> list[tuple[int, int]]:
    """
    Bootstrap 方法：从 MFT 记录 0（$MFT 自身的元数据记录）的 $DATA 属性
    解析 nonresident data runs，直接获取完整的 MFT Extent 列表。

    原理：MFT 记录 0 始终位于 MFT 的最开头（MftStartLcn 指向的位置），
    其 $DATA 属性描述了整个 $MFT 文件的物理布局。即使 MFT 碎片化为多段，
    记录 0 本身只有 1024 字节，一定在第一段内，所以只需读一条记录即可获得
    完整的 Extent 信息。

    不需要打开 $MFT 文件句柄（绕过 err=5），只需要已有的卷句柄。
    """
    # 定位到 MFT 起始位置，读取第一条记录
    start_byte = mft_start_lcn * bytes_per_cluster
    dist    = ctypes.c_int64(start_byte)
    new_pos = ctypes.c_int64(0)

    kernel32.SetFilePointerEx.restype = ctypes.c_int
    ok = kernel32.SetFilePointerEx(vol_handle, dist, ctypes.byref(new_pos), 0)
    if not ok:
        logger.debug("[MFT] bootstrap: SetFilePointerEx 失败 err=%d", kernel32.GetLastError())
        return []

    buf = ctypes.create_string_buffer(rec_size)
    br  = wt.DWORD(0)
    ok  = kernel32.ReadFile(vol_handle, buf, rec_size, ctypes.byref(br), None)
    if not ok or br.value < rec_size:
        logger.debug("[MFT] bootstrap: ReadFile 失败 err=%d bytes=%d", kernel32.GetLastError(), br.value)
        return []

    raw = bytearray(buf.raw[:rec_size])

    # 校验 MFT 签名
    if raw[:4] != b'FILE':
        logger.debug("[MFT] bootstrap: 记录0签名不是FILE")
        return []

    # 应用 USA fixup
    if not _apply_usa_fixup(raw, rec_size, sector_size):
        logger.debug("[MFT] bootstrap: USA fixup 失败")
        return []

    # 遍历属性链表，找到 $DATA 的 nonresident data runs
    attrs_off = struct.unpack_from('<H', raw, 20)[0]
    off = attrs_off

    while off + 8 <= len(raw):
        atype = struct.unpack_from('<I', raw, off)[0]
        if atype == AT_END:
            break
        alen = struct.unpack_from('<I', raw, off + 4)[0]
        if alen < 8 or off + alen > len(raw):
            break

        non_res = raw[off + 8]

        if atype == AT_DATA and non_res == 1:
            # nonresident $DATA 属性
            # 属性名长度必须为0（无名主数据流）
            attr_name_len = raw[off + 9]
            if attr_name_len == 0:
                # data runs 偏移存储在属性头 offset+32（RunsOffset, WORD）
                runs_offset = struct.unpack_from('<H', raw, off + 32)[0]
                runs_start  = off + runs_offset
                runs_end    = off + alen

                extents = _parse_data_runs(raw, runs_start, runs_end, bytes_per_cluster)
                if extents:
                    total_bytes = sum(ln for _, ln in extents)
                    logger.info(
                        "[MFT] bootstrap 成功: 从MFT记录0的$DATA解析出 %d 个Extent, "
                        "总计=%.1f MB",
                        len(extents), total_bytes / 1024 / 1024,
                    )
                    return extents

        off += alen

    logger.debug("[MFT] bootstrap: 未在记录0中找到nonresident $DATA属性")
    return []


def _parse_retrieval_pointers(data: bytes, bytes_per_cluster: int) -> list[tuple[int, int]]:
    """
    解析 RETRIEVAL_POINTERS_BUFFER 结构，返回 [(start_byte, length_bytes), ...]。

    结构布局（64 位对齐）：
      ExtentCount  DWORD      offset 0
      (padding)    4B         offset 4
      StartingVcn  LONGLONG   offset 8
      Extents[i]:
        NextVcn    LONGLONG   offset 16 + i*16
        Lcn        LONGLONG   offset 24 + i*16
    """
    if len(data) < 16:
        return []
    extent_count = struct.unpack_from('<I', data, 0)[0]
    extents: list[tuple[int, int]] = []
    prev_vcn = struct.unpack_from('<q', data, 8)[0]   # StartingVcn

    for i in range(extent_count):
        off = 16 + i * 16
        if off + 16 > len(data):
            break
        next_vcn = struct.unpack_from('<q', data, off    )[0]
        lcn      = struct.unpack_from('<q', data, off + 8)[0]
        if lcn >= 0:
            cluster_count = next_vcn - prev_vcn
            extents.append((lcn * bytes_per_cluster, cluster_count * bytes_per_cluster))
        # lcn == -1 表示稀疏/空洞，跳过
        prev_vcn = next_vcn

    return extents


def _get_mft_extents(
    drive: str,
    vol_handle,
    kernel32,
    mft_start_lcn: int,
    mft_bytes: int,
    bytes_per_cluster: int,
    rec_size: int = 1024,
    sector_size: int = 512,
) -> list[tuple[int, int]]:
    """
    获取 $MFT 文件的所有物理 Extent，解决 MFT 碎片化导致只扫部分数据的问题。

    尝试顺序（优先级从高到低）：
    1. 通过文件ID（FRN=0）打开 $MFT，调用 FSCTL_GET_RETRIEVAL_POINTERS
    2. 以路径 \\\\?\\D:\\$MFT 打开，调用 FSCTL_GET_RETRIEVAL_POINTERS
    3. Bootstrap：从 MFT 记录 0 的 $DATA data runs 直接解析 Extent
    4. 回退：单段模式（MftStartLcn + MftValidDataLength）

    返回 [(start_byte, length_bytes), ...] 按顺序排列。
    """
    fallback = [(mft_start_lcn * bytes_per_cluster, mft_bytes)]

    class _StartVcn(ctypes.Structure):
        _fields_ = [("StartingVcn", ctypes.c_int64)]

    def _query_extents(handle) -> list[tuple[int, int]]:
        """在给定文件句柄上调用 FSCTL_GET_RETRIEVAL_POINTERS。"""
        buf_size = 1024 * 1024   # 1 MB，足以容纳高度碎片化的 MFT
        out_buf  = ctypes.create_string_buffer(buf_size)
        in_buf   = _StartVcn(0)
        br       = wt.DWORD(0)

        ok = kernel32.DeviceIoControl(
            handle,
            FSCTL_GET_RETRIEVAL_POINTERS,
            ctypes.byref(in_buf), ctypes.sizeof(in_buf),
            out_buf, buf_size,
            ctypes.byref(br), None,
        )
        err = kernel32.GetLastError()
        if not ok and err != 234:   # 234 = ERROR_MORE_DATA（部分返回，仍可解析）
            return []
        data = out_buf.raw[: br.value]
        return _parse_retrieval_pointers(data, bytes_per_cluster)

    kernel32.CreateFileW.restype = ctypes.c_void_p

    # ── 方法1：通过文件ID打开 $MFT（FRN固定为0，FILE_OPEN_BY_FILE_ID=0x2000）──
    # 构造 ObjectAttributes 指向卷路径，FileId = 0（$MFT 的 FRN）
    # 注：NtCreateFile 签名复杂，改用 OpenFileById（较简洁）
    try:
        ntdll = ctypes.WinDLL("ntdll")

        class _UNICODE_STRING(ctypes.Structure):
            _fields_ = [("Length", wt.USHORT), ("MaximumLength", wt.USHORT),
                        ("Buffer", ctypes.c_void_p)]

        class _OBJECT_ATTRIBUTES(ctypes.Structure):
            _fields_ = [("Length", wt.ULONG), ("RootDirectory", ctypes.c_void_p),
                        ("ObjectName", ctypes.POINTER(_UNICODE_STRING)),
                        ("Attributes", wt.ULONG), ("SecurityDescriptor", ctypes.c_void_p),
                        ("SecurityQualityOfService", ctypes.c_void_p)]

        # 文件ID缓冲区：LARGE_INTEGER 存 FRN=0（$MFT）
        file_id_buf = ctypes.create_string_buffer(8)
        struct.pack_into('<Q', file_id_buf, 0, 0)   # FRN = 0

        us = _UNICODE_STRING()
        us.Length = 8
        us.MaximumLength = 8
        us.Buffer = ctypes.cast(file_id_buf, ctypes.c_void_p).value

        oa = _OBJECT_ATTRIBUTES()
        oa.Length = ctypes.sizeof(_OBJECT_ATTRIBUTES)
        oa.RootDirectory = vol_handle   # 卷句柄作为根
        oa.ObjectName = ctypes.pointer(us)
        oa.Attributes = 0x40            # OBJ_CASE_INSENSITIVE

        io_status = (ctypes.c_int64 * 2)()
        mft_handle = ctypes.c_void_p(0)

        # FILE_OPEN_BY_FILE_ID = 0x00002000, FILE_NON_DIRECTORY_FILE = 0x00000040
        # DesiredAccess = FILE_READ_DATA(1) | SYNCHRONIZE(0x00100000)
        status = ntdll.NtCreateFile(
            ctypes.byref(mft_handle),
            0x00100001,              # DesiredAccess: FILE_READ_DATA | SYNCHRONIZE
            ctypes.byref(oa),
            io_status,
            None,                   # AllocationSize
            0,                      # FileAttributes
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            1,                      # OPEN_EXISTING
            0x00002040,             # FILE_OPEN_BY_FILE_ID | FILE_NON_DIRECTORY_FILE
            None, 0,                # EaBuffer, EaLength
        )
        if status == 0 and mft_handle.value and mft_handle.value != INVALID_HANDLE_VALUE:
            try:
                extents = _query_extents(mft_handle.value)
                if extents:
                    total_ext = sum(ln for _, ln in extents)
                    logger.info(
                        "[MFT] $MFT Extent 数量=%d (通过FRN打开), 总字节=%.1f MB",
                        len(extents), total_ext / 1024 / 1024,
                    )
                    return extents
            finally:
                kernel32.CloseHandle(mft_handle.value)
    except Exception as e:
        logger.debug("[MFT] NtCreateFile方式失败: %s", e)

    # ── 方法2：以路径打开 $MFT ────────────────────────────────────────────────
    mft_path = f"\\\\?\\{drive}:\\$MFT"
    mft_handle2 = kernel32.CreateFileW(
        mft_path,
        GENERIC_READ,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        None,
        OPEN_EXISTING,
        FILE_FLAG_BACKUP_SEMANTICS,
        None,
    )
    if mft_handle2 != INVALID_HANDLE_VALUE:
        try:
            extents = _query_extents(mft_handle2)
            if extents:
                total_ext = sum(ln for _, ln in extents)
                logger.info(
                    "[MFT] $MFT Extent 数量=%d (通过路径打开), 总字节=%.1f MB",
                    len(extents), total_ext / 1024 / 1024,
                )
                return extents
        finally:
            kernel32.CloseHandle(mft_handle2)
    else:
        err = kernel32.GetLastError()
        logger.debug("[MFT] 无法打开 $MFT 文件句柄 err=%d，尝试 bootstrap 方法", err)

    # ── 方法3：Bootstrap — 从 MFT 记录 0 的 $DATA data runs 获取 Extent ────
    # 不需要打开 $MFT 文件句柄，只用卷句柄读取 MFT 第一条记录即可。
    # MFT 记录 0 是 $MFT 自身的元数据，其 $DATA 属性的 data runs 包含
    # 整个 MFT 文件的完整物理布局。
    bootstrap_extents = _bootstrap_mft_extents(
        vol_handle, kernel32,
        mft_start_lcn, bytes_per_cluster,
        rec_size, sector_size,
    )
    if bootstrap_extents:
        return bootstrap_extents

    # ── 方法4：回退单段模式（最后手段）──────────────────────────────────────
    logger.warning(
        "[MFT] 回退单 Extent 模式（MFT碎片化时可能丢失数据）: "
        "start=%.1f MB, len=%.1f MB",
        mft_start_lcn * bytes_per_cluster / 1024 / 1024,
        mft_bytes / 1024 / 1024,
    )
    return fallback


def _open_handle(path: str, kernel32, flags: int = 0):
    """打开文件/卷句柄，失败抛出 OSError。"""
    kernel32.CreateFileW.restype = ctypes.c_void_p
    h = kernel32.CreateFileW(
        path,
        GENERIC_READ,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        None,
        OPEN_EXISTING,
        FILE_FLAG_SEQUENTIAL_SCAN | flags,
        None,
    )
    if h == INVALID_HANDLE_VALUE:
        err = kernel32.GetLastError()
        raise OSError(f"无法打开 {path!r}，GetLastError={err}")
    return h


def _get_ntfs_volume_data(vol_handle, kernel32) -> _NTFS_VOLUME_DATA:
    """通过 FSCTL_GET_NTFS_VOLUME_DATA 获取 NTFS 卷参数。"""
    vd = _NTFS_VOLUME_DATA()
    br = wt.DWORD(0)
    ok = kernel32.DeviceIoControl(
        vol_handle, FSCTL_GET_NTFS_VOLUME_DATA,
        None, 0,
        ctypes.byref(vd), ctypes.sizeof(vd),
        ctypes.byref(br), None,
    )
    if not ok:
        raise RuntimeError(
            f"FSCTL_GET_NTFS_VOLUME_DATA 失败，GetLastError={kernel32.GetLastError()}。"
            "请确认目标卷为 NTFS 格式。"
        )
    return vd


def _iter_mft_records(
    vol_handle,
    kernel32,
    rec_size: int,
    sector_size: int,
    extents: list[tuple[int, int]],
    mft_valid_bytes: int = 0,
) -> Iterator[tuple[int, bytes]]:
    """
    按 Extent 列表逐段读取 $MFT，yield (rec_num, record_bytes)。

    rec_num 为该记录在 MFT 中的全局绝对索引（与 FRN 记录号对应）。
    按 Extent 分段读取可正确处理碎片化 MFT（即 MFT 在磁盘上不连续的情况）。

    mft_valid_bytes: MftValidDataLength，限制总读取量避免读到簇对齐填充区。
                     为 0 时不限制（按 extents 总长读取）。
    """
    recs_per_chunk  = max(4096, (4 * 1024 * 1024) // rec_size)
    chunk_size      = recs_per_chunk * rec_size
    buf             = ctypes.create_string_buffer(chunk_size)
    br              = wt.DWORD(0)
    global_rec_num  = 0       # 跨 Extent 累计的 MFT 记录绝对编号
    total_read      = 0       # 跨 Extent 累计已读字节数

    kernel32.SetFilePointerEx.restype = ctypes.c_int

    for ext_start, ext_len in extents:
        if mft_valid_bytes > 0 and total_read >= mft_valid_bytes:
            break   # 已超过 MFT 有效数据范围，停止

        # 定位到本 Extent 起始字节（需扇区对齐，MFT 簇对齐必然满足 512B 对齐）
        dist    = ctypes.c_int64(ext_start)
        new_pos = ctypes.c_int64(0)
        ok = kernel32.SetFilePointerEx(vol_handle, dist, ctypes.byref(new_pos), 0)
        if not ok:
            logger.warning(
                "[MFT] Extent 定位失败 start=%.1f MB err=%d，跳过本段",
                ext_start / 1024 / 1024, kernel32.GetLastError(),
            )
            # 估算跳过的记录数，保持 global_rec_num 连续性
            global_rec_num += ext_len // rec_size
            total_read     += ext_len
            continue

        # 限制本段读取量：取 Extent 长度 和 剩余有效字节数 的最小值
        if mft_valid_bytes > 0:
            ext_limit = min(ext_len, mft_valid_bytes - total_read)
        else:
            ext_limit = ext_len

        ext_read = 0
        while ext_read < ext_limit:
            to_read = min(chunk_size, ext_limit - ext_read)
            ok = kernel32.ReadFile(vol_handle, buf, to_read, ctypes.byref(br), None)
            if not ok or br.value == 0:
                err = kernel32.GetLastError()
                logger.debug(
                    "[MFT] Extent 读取中断 ext_start=%.1f MB ext_read=%.1f MB err=%d",
                    ext_start / 1024 / 1024, ext_read / 1024 / 1024, err,
                )
                break

            chunk_bytes   = br.value
            ext_read     += chunk_bytes
            recs_in_chunk = chunk_bytes // rec_size

            mv = memoryview(buf).cast('B')   # 字节视图，切片不复制内存
            for i in range(recs_in_chunk):
                start = i * rec_size
                # bytes(mv[...]) 仍会复制，但只有 4 字节，远小于原来的 1024B 切片
                if mv[start] != 0x46 or mv[start+1] != 0x49 or mv[start+2] != 0x4C or mv[start+3] != 0x45:
                    continue  # 'F','I','L','E' = 0x46,0x49,0x4C,0x45
                rec = bytearray(mv[start:start + rec_size])
                if _apply_usa_fixup(rec, rec_size, sector_size):
                    yield global_rec_num + i, rec   # bytearray 兼容所有 struct/bytes 操作，省去 bytes() 拷贝

            global_rec_num += recs_in_chunk

        total_read += ext_read


# ─── 目录路径缓存（拓扑展开）─────────────────────────────────────────────────

def _build_dir_cache(
    dir_map: dict[int, tuple[str, int, Optional[str]]],
    drive_root: str,
) -> tuple[dict[int, tuple[str, int]], dict[str, Optional[str]]]:
    """
    将 {rec_num: (name, parent_rec_num, mtime)} 拓扑展开为：
      - cache     : {rec_num: (full_path, depth)}
      - dir_mtimes: {full_path: mtime}  供后处理直接写 dir_snapshots，无需 os.stat()

    depth 从根目录算起（根目录 depth=1），子目录 depth = 父 depth + 1。
    多轮迭代直至所有目录均可解析（处理 MFT 枚举顺序不确定的情况）。
    孤立目录（父链中断）在规定轮数后放弃，并为其分配虚拟路径，
    格式：<drive_root>$ORPHAN$\<frn>，确保文件不丢失。
    """
    root_path = drive_root.rstrip(os.sep)
    root_depth = root_path.count(os.sep) + 1
    cache: dict[int, tuple[str, int]] = {NTFS_ROOT_FRN: (root_path, root_depth)}
    dir_mtimes: dict[str, Optional[str]] = {}

    pending = [
        (rec, name, parent, mtime)
        for rec, (name, parent, mtime) in dir_map.items()
        if rec not in cache and rec != parent
    ]

    for _ in range(512):
        if not pending:
            break
        next_pending = []
        for rec, name, parent, mtime in pending:
            parent_entry = cache.get(parent)
            if parent_entry is not None:
                parent_path, parent_depth = parent_entry
                full_path = parent_path + os.sep + name
                cache[rec] = (full_path, parent_depth + 1)
                dir_mtimes[full_path] = mtime
            else:
                next_pending.append((rec, name, parent, mtime))
        if len(next_pending) == len(pending):
            break
        pending = next_pending

    # 孤立目录分配虚拟路径（不写入 dir_mtimes，后处理跳过即可）
    orphan_root = drive_root + "$ORPHAN$"
    for rec, name, parent, _mtime in pending:
        cache[rec] = (orphan_root + os.sep + str(rec), root_depth + 99)

    return cache, dir_mtimes


# ─── 主扫描逻辑 ───────────────────────────────────────────────────────────────

def _do_scan(
    vol_handle,
    drive_root: str,
    batch_callback: Callable[[list[dict]], None],
    batch_size: int,
    disk_label: str,
    kernel32,
    phase_callback: Optional[Callable[[str, str], None]] = None,
) -> tuple[int, float, dict[str, Optional[str]]]:
    t0 = time.monotonic()

    # ── 1. 获取 NTFS 卷参数 ────────────────────────────────────────────────────
    vd          = _get_ntfs_volume_data(vol_handle, kernel32)
    rec_size    = vd.BytesPerFileRecordSegment or 1024
    sector_size = vd.BytesPerSector            or 512
    mft_bytes   = vd.MftValidDataLength

    if mft_bytes <= 0:
        raise RuntimeError("MftValidDataLength 为 0，无法读取 MFT")

    logger.info(
        "[MFT] 卷参数: rec_size=%d B, sector_size=%d B, MFT大小=%.1f MB",
        rec_size, sector_size, mft_bytes / 1024 / 1024,
    )

    # ── 2. 获取 $MFT 的物理 Extent 列表（解决 MFT 碎片化导致只扫部分数据的问题）──
    # 旧方式：SetFilePointerEx 定位到 MftStartLcn 后顺序 ReadFile，遇到 MFT
    # 的第一段末尾就会中断（Windows 裸卷读取不会跨 Extent 自动续读）。
    # 新方式：先用 FSCTL_GET_RETRIEVAL_POINTERS 取到所有 Extent，再逐段读取。
    logger.info(
        "[MFT] 获取 $MFT Extent 列表（MFT起始LCN=%d，MFT大小=%.1f MB）...",
        vd.MftStartLcn, mft_bytes / 1024 / 1024,
    )
    mft_extents = _get_mft_extents(
        drive_root[0], vol_handle, kernel32,
        vd.MftStartLcn, mft_bytes, vd.BytesPerCluster,
        rec_size, sector_size,
    )

    # ── 3. 单次遍历 MFT，分类收集 ─────────────────────────────────────────
    # dir_map  : {rec_num: (name, parent_rec_num, mtime)}  普通目录
    # files_raw: [(parent_frn, name, size, ctime, mtime)]  普通文件
    # gdb_raw  : [(parent_frn, name, ctime, mtime)]  .gdb 目录（GIS 数据库）
    if True:
        dir_map:   dict[int, tuple[str, int, Optional[str]]] = {}
        files_raw: list[tuple[int, str, int, Optional[str], Optional[str]]] = []
        gdb_raw:   list[tuple[int, str, Optional[str], Optional[str]]] = []

        dir_count  = 0
        file_count = 0

        t_enum_start = time.monotonic()

        _phase_interval = 50_000   # 每解析 5 万条记录更新一次进度
        _parsed_total   = 0

        for rec_num, raw in _iter_mft_records(
            vol_handle, kernel32, rec_size, sector_size, mft_extents, mft_bytes
        ):
            parsed = _parse_record(raw, rec_size)
            if parsed is None:
                continue

            p_frn  = parsed['parent_frn']
            name   = parsed['name']
            is_dir = parsed['is_dir']
            size   = parsed['file_size']
            ctime  = parsed['ctime']
            mtime  = parsed['mtime']

            if is_dir:
                if name.lower().endswith('.gdb'):
                    gdb_raw.append((p_frn, name, ctime, mtime))
                else:
                    dir_map[rec_num] = (name, p_frn, mtime)
                dir_count += 1
            else:
                files_raw.append((p_frn, name, size, ctime, mtime))
                file_count += 1

            _parsed_total += 1
            if phase_callback and _parsed_total % _phase_interval == 0:
                phase_callback(
                    "读取 MFT 元数据",
                    f"已解析 {_parsed_total:,} 条记录（文件 {file_count:,} / 目录 {dir_count:,}）",
                )

        t_enum_done = time.monotonic()
        logger.info(
            "[MFT] $MFT读取完成: 目录=%d, 文件=%d, .gdb=%d, 耗时=%.2fs",
            dir_count, file_count, len(gdb_raw),
            t_enum_done - t_enum_start,
        )
        if phase_callback:
            phase_callback("解析目录路径结构", f"共 {dir_count} 个目录，构建路径索引...")

    # ── 4. 拓扑展开目录路径缓存 ────────────────────────────────────────────────
    t_cache_start = time.monotonic()
    dir_cache, dir_mtimes = _build_dir_cache(dir_map, drive_root)
    t_cache_done = time.monotonic()
    orphan_dirs = dir_count - len(dir_cache) + 1   # +1 因为 cache 包含 root
    logger.info(
        "[MFT] 目录路径缓存: 成功=%d, 孤立=%d, 耗时=%.2fs",
        len(dir_cache) - 1, max(0, orphan_dirs),
        t_cache_done - t_cache_start,
    )

    # ── 5. 构建并输出文件记录 ──────────────────────────────────────────────────
    # dir_cache 现在存 {rec_num: (full_path, depth)}，文件深度 = 父目录深度 + 1
    # 无需再对完整路径字符串计数分隔符，O(1) 查表即可
    root_depth_fallback = drive_root.rstrip("\\").count("\\") + 1 + 1  # 孤立文件备用深度
    batch:      list[dict] = []
    total_count = 0
    path_ok     = 0
    path_fail   = 0
    sep         = os.sep   # "\\" on Windows，缓存避免重复属性查找

    def _flush(records: list[dict]) -> None:
        nonlocal total_count
        batch_callback(records)
        total_count += len(records)

    # 孤立文件的虚拟根路径
    orphan_root = drive_root + "$ORPHAN$"

    # get_file_type 结果缓存（同扩展名只调用一次，53万文件扩展名种类有限）
    _ft_cache: dict[str, str] = {}
    _get_ft = _ft_cache.__missing__ if False else lambda e: _ft_cache.setdefault(e, get_file_type(e))

    # shapefile 扩展名集合（本地引用避免重复全局查找）
    _shp_exts = SHAPEFILE_EXTENSIONS

    # 普通文件
    for p_frn, name, size, ctime, mtime in files_raw:
        entry = dir_cache.get(p_frn)
        if entry is None:
            # 父目录FRN未在dir_cache中（可能是MFT碎片化导致目录记录未读到）
            # 归入虚拟孤立目录，保证文件不丢失
            parent_path = orphan_root + sep + str(p_frn)
            depth = root_depth_fallback
            path_fail += 1
        else:
            parent_path, parent_depth = entry
            depth = parent_depth + 1   # 文件深度 = 父目录深度 + 1，O(1) 查表
            path_ok += 1
        full_path  = parent_path + sep + name
        # 扩展名：从文件名找最后一个点
        dot_idx    = name.rfind('.')
        if dot_idx > 0:
            ext  = name[dot_idx:].lower()
            stem = name[:dot_idx]
        else:
            ext  = ""
            stem = name
        sg    = parent_path + sep + stem if ext in _shp_exts else None

        batch.append({
            "file_name":        name,
            "file_name_no_ext": stem,
            "extension":        ext,
            "file_size":        size,
            "created_time":     ctime,
            "modified_time":    mtime,
            "file_path":        full_path,
            "parent_dir":       parent_path,
            "dir_depth":        depth,
            "file_type":        _get_ft(ext),
            "shapefile_group":  sg,
            "disk_label":       disk_label,
        })
        if len(batch) >= batch_size:
            _flush(batch)
            batch = []

    # .gdb 目录（作为单条 gis_vector 记录）
    for p_frn, name, ctime, mtime in gdb_raw:
        entry = dir_cache.get(p_frn)
        if entry is None:
            continue
        parent_path, parent_depth = entry
        full_path  = parent_path + sep + name
        dot_idx    = name.rfind('.')
        stem       = name[:dot_idx] if dot_idx > 0 else name
        depth      = parent_depth + 1   # 同上，O(1) 查表

        batch.append({
            "file_name":        name,
            "file_name_no_ext": stem,
            "extension":        ".gdb",
            "file_size":        0,
            "created_time":     ctime,
            "modified_time":    mtime,
            "file_path":        full_path,
            "parent_dir":       parent_path,
            "dir_depth":        depth,
            "file_type":        "gis_vector",
            "shapefile_group":  None,
            "disk_label":       disk_label,
        })
        if len(batch) >= batch_size:
            _flush(batch)
            batch = []

    if batch:
        _flush(batch)

    elapsed = time.monotonic() - t0
    logger.info(
        "[MFT] 路径解析: 成功=%d, 孤立失败=%d (%.1f%%)",
        path_ok, path_fail,
        path_fail / (path_ok + path_fail) * 100 if (path_ok + path_fail) > 0 else 0.0,
    )
    logger.info(
        "[MFT] 总耗时=%.2fs (MFT读取+解析=%.2fs, 目录缓存=%.2fs, 路径展开=%.2fs)",
        elapsed,
        t_enum_done - t_enum_start,
        t_cache_done - t_cache_start,
        elapsed - (t_cache_done - t_cache_start) - (t_enum_done - t_enum_start),
    )
    return total_count, elapsed, dir_mtimes


# ─── 公开接口（与 v1 完全兼容）───────────────────────────────────────────────

def scan_volume(
    drive_letter: str,
    batch_callback: Callable[[list[dict]], None],
    batch_size: int = 20_000,
    disk_label: str = "",
    phase_callback: Optional[Callable[[str, str], None]] = None,
) -> tuple[int, float]:
    """
    通过 NTFS MFT 直读枚举卷内所有文件，按批次调用 batch_callback。

    参数：
        drive_letter  : 盘符，如 "C" 或 "C:"（不含反斜杠）
        batch_callback: 接收 list[dict] 的回调，dict 格式与 scanner.py 相同
        batch_size    : 每批回调的文件数（默认 20000）
        disk_label    : 写入记录 disk_label 字段的标签字符串
        phase_callback: 可选，签名 (phase: str, current_dir: str) -> None，
                        在关键阶段切换时调用，用于向外部更新进度状态

    返回：
        (total_count, elapsed_seconds, dir_mtimes)
        dir_mtimes: {full_path: mtime_isostr}，供调用方直接写 dir_snapshots

    异常：
        PermissionError : 无管理员权限
        OSError         : 卷句柄或 $MFT 打开失败
        RuntimeError    : 非 NTFS 卷或 API 调用失败
    """
    check_admin()

    drive = drive_letter.strip(":\\ ").upper()
    if not drive or len(drive) != 1 or not drive.isalpha():
        raise ValueError(f"无效盘符：{drive_letter!r}")

    volume_path = f"\\\\.\\{drive}:"
    drive_root  = f"{drive}:\\"

    kernel32 = ctypes.windll.kernel32
    kernel32.CreateFileW.restype     = ctypes.c_void_p
    kernel32.ReadFile.restype        = ctypes.c_int
    kernel32.CloseHandle.restype     = ctypes.c_int
    kernel32.DeviceIoControl.restype = ctypes.c_int

    logger.info("[MFT] 打开卷句柄: %s (drive_root=%s)", volume_path, drive_root)
    vol_handle = kernel32.CreateFileW(
        volume_path,
        GENERIC_READ,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        None,
        OPEN_EXISTING,
        0,
        None,
    )
    if vol_handle == INVALID_HANDLE_VALUE:
        err = kernel32.GetLastError()
        raise OSError(f"无法打开卷 {volume_path}，GetLastError={err}")

    try:
        total, elapsed, dir_mtimes = _do_scan(
            vol_handle, drive_root, batch_callback, batch_size, disk_label, kernel32,
            phase_callback=phase_callback,
        )
        logger.info("[MFT] scan_volume完成: total=%d, elapsed=%.2fs", total, elapsed)
        return total, elapsed, dir_mtimes
    except Exception as exc:
        logger.error("[MFT] scan_volume异常终止: %s", exc, exc_info=True)
        raise
    finally:
        kernel32.CloseHandle(vol_handle)
