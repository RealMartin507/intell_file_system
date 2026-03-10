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
from pathlib import Path
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

FSCTL_GET_NTFS_VOLUME_DATA  = 0x00090064

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
    mft_handle,
    kernel32,
    rec_size: int,
    sector_size: int,
    total_bytes: int,
) -> Iterator[tuple[int, bytes]]:
    """
    顺序读取 $MFT，逐条 yield (rec_num, record_bytes)。

    rec_num 为记录在 MFT 中的绝对索引（从 0 开始），与其他记录引用的
    父目录 FRN 记录号一致。跳过签名错误或 USA 校验失败的记录。
    """
    # 每次读取块大小：至少 4MB，且为 rec_size 的整数倍
    recs_per_chunk = max(4096, (4 * 1024 * 1024) // rec_size)
    chunk_size     = recs_per_chunk * rec_size
    buf            = ctypes.create_string_buffer(chunk_size)
    br             = wt.DWORD(0)
    read_total     = 0
    base_rec_num   = 0      # 当前块第一条记录的绝对编号

    while read_total < total_bytes:
        to_read = min(chunk_size, total_bytes - read_total)
        ok = kernel32.ReadFile(mft_handle, buf, to_read, ctypes.byref(br), None)
        if not ok or br.value == 0:
            break

        chunk_bytes = br.value
        read_total += chunk_bytes
        recs_in_chunk = chunk_bytes // rec_size

        for i in range(recs_in_chunk):
            start = i * rec_size
            raw   = buf[start: start + rec_size]
            if raw[:4] != b'FILE':
                continue
            rec = bytearray(raw)
            if _apply_usa_fixup(rec, rec_size, sector_size):
                yield base_rec_num + i, bytes(rec)

        base_rec_num += recs_in_chunk


# ─── 目录路径缓存（拓扑展开）─────────────────────────────────────────────────

def _build_dir_cache(
    dir_map: dict[int, tuple[str, int]],
    drive_root: str,
) -> dict[int, str]:
    """
    将 {rec_num: (name, parent_rec_num)} 拓扑展开为 {rec_num: full_path}。

    多轮迭代直至所有目录均可解析（处理 MFT 枚举顺序不确定的情况）。
    孤立目录（父链中断）在规定轮数后放弃。
    """
    cache: dict[int, str] = {NTFS_ROOT_FRN: drive_root}
    # 过滤掉自引用记录（根目录本身 parent == self）以及已在 cache 中的
    pending = [
        (rec, name, parent)
        for rec, (name, parent) in dir_map.items()
        if rec not in cache and rec != parent
    ]

    for _ in range(512):        # 最大目录深度防护
        if not pending:
            break
        next_pending = []
        for rec, name, parent in pending:
            parent_path = cache.get(parent)
            if parent_path is not None:
                cache[rec] = os.path.join(parent_path, name)
            else:
                next_pending.append((rec, name, parent))
        if len(next_pending) == len(pending):
            break               # 无新进展，剩余均为孤立目录
        pending = next_pending

    return cache


# ─── 主扫描逻辑 ───────────────────────────────────────────────────────────────

def _do_scan(
    vol_handle,
    drive_root: str,
    batch_callback: Callable[[list[dict]], None],
    batch_size: int,
    disk_label: str,
    kernel32,
) -> tuple[int, float]:
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

    # ── 2. 将卷句柄定位到 MFT 起始字节 ───────────────────────────────────────
    # Windows 不允许通过路径直接打开 $MFT（ERROR_ACCESS_DENIED），
    # 正确做法是在已有卷句柄上用 SetFilePointerEx 定位到 MFT 起始簇，然后 ReadFile。
    mft_start_byte = vd.MftStartLcn * vd.BytesPerCluster
    kernel32.SetFilePointerEx.restype = ctypes.c_int
    dist    = ctypes.c_int64(mft_start_byte)
    new_pos = ctypes.c_int64(0)
    ok = kernel32.SetFilePointerEx(vol_handle, dist, ctypes.byref(new_pos), 0)  # FILE_BEGIN=0
    if not ok:
        raise RuntimeError(
            f"SetFilePointerEx 失败（MFT偏移={mft_start_byte}），"
            f"GetLastError={kernel32.GetLastError()}"
        )

    logger.info(
        "[MFT] 开始顺序读取 $MFT（偏移=%.1f MB，大小=%.1f MB）...",
        mft_start_byte / 1024 / 1024, mft_bytes / 1024 / 1024,
    )

    # ── 3. 单次遍历 MFT，分类收集 ─────────────────────────────────────────
    # dir_map  : {rec_num: (name, parent_rec_num)}  普通目录
    # files_raw: [(parent_frn, name, size, ctime, mtime)]  普通文件
    # gdb_raw  : [(parent_frn, name, ctime, mtime)]  .gdb 目录（GIS 数据库）
    if True:
        dir_map:   dict[int, tuple[str, int]] = {}
        files_raw: list[tuple[int, str, int, Optional[str], Optional[str]]] = []
        gdb_raw:   list[tuple[int, str, Optional[str], Optional[str]]] = []

        dir_count  = 0
        file_count = 0

        t_enum_start = time.monotonic()

        for rec_num, raw in _iter_mft_records(
            vol_handle, kernel32, rec_size, sector_size, mft_bytes
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
                    dir_map[rec_num] = (name, p_frn)
                dir_count += 1
            else:
                files_raw.append((p_frn, name, size, ctime, mtime))
                file_count += 1

        t_enum_done = time.monotonic()
        logger.info(
            "[MFT] $MFT读取完成: 目录=%d, 文件=%d, .gdb=%d, 耗时=%.2fs",
            dir_count, file_count, len(gdb_raw),
            t_enum_done - t_enum_start,
        )

    # ── 4. 拓扑展开目录路径缓存 ────────────────────────────────────────────────
    t_cache_start = time.monotonic()
    dir_cache = _build_dir_cache(dir_map, drive_root)
    t_cache_done = time.monotonic()
    orphan_dirs = dir_count - len(dir_cache) + 1   # +1 因为 cache 包含 root
    logger.info(
        "[MFT] 目录路径缓存: 成功=%d, 孤立=%d, 耗时=%.2fs",
        len(dir_cache) - 1, max(0, orphan_dirs),
        t_cache_done - t_cache_start,
    )

    # ── 5. 构建并输出文件记录 ──────────────────────────────────────────────────
    root_depth  = len(Path(drive_root).parts)
    batch:      list[dict] = []
    total_count = 0
    path_ok     = 0
    path_fail   = 0

    def _flush(records: list[dict]) -> None:
        nonlocal total_count
        batch_callback(records)
        total_count += len(records)

    # 普通文件
    for p_frn, name, size, ctime, mtime in files_raw:
        parent_path = dir_cache.get(p_frn)
        if parent_path is None:
            path_fail += 1
            continue
        path_ok  += 1
        full_path = os.path.join(parent_path, name)
        path_obj  = Path(full_path)
        stem      = path_obj.stem
        ext       = path_obj.suffix.lower()
        depth     = len(path_obj.parts) - root_depth
        sg        = str(path_obj.parent / stem) if ext in SHAPEFILE_EXTENSIONS else None

        batch.append({
            "file_name":        name,
            "file_name_no_ext": stem,
            "extension":        ext,
            "file_size":        size,
            "created_time":     ctime,
            "modified_time":    mtime,
            "file_path":        full_path,
            "parent_dir":       str(path_obj.parent),
            "dir_depth":        depth,
            "file_type":        get_file_type(ext),
            "shapefile_group":  sg,
            "disk_label":       disk_label,
        })
        if len(batch) >= batch_size:
            _flush(batch)
            batch = []

    # .gdb 目录（作为单条 gis_vector 记录）
    for p_frn, name, ctime, mtime in gdb_raw:
        parent_path = dir_cache.get(p_frn)
        if parent_path is None:
            continue
        full_path = os.path.join(parent_path, name)
        path_obj  = Path(full_path)
        depth     = len(path_obj.parts) - root_depth

        batch.append({
            "file_name":        name,
            "file_name_no_ext": path_obj.stem,
            "extension":        ".gdb",
            "file_size":        0,
            "created_time":     ctime,
            "modified_time":    mtime,
            "file_path":        full_path,
            "parent_dir":       str(path_obj.parent),
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
    return total_count, elapsed


# ─── 公开接口（与 v1 完全兼容）───────────────────────────────────────────────

def scan_volume(
    drive_letter: str,
    batch_callback: Callable[[list[dict]], None],
    batch_size: int = 20_000,
    disk_label: str = "",
) -> tuple[int, float]:
    """
    通过 NTFS MFT 直读枚举卷内所有文件，按批次调用 batch_callback。

    参数：
        drive_letter  : 盘符，如 "C" 或 "C:"（不含反斜杠）
        batch_callback: 接收 list[dict] 的回调，dict 格式与 scanner.py 相同
        batch_size    : 每批回调的文件数（默认 20000）
        disk_label    : 写入记录 disk_label 字段的标签字符串

    返回：
        (total_count, elapsed_seconds)

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
        total, elapsed = _do_scan(
            vol_handle, drive_root, batch_callback, batch_size, disk_label, kernel32
        )
        logger.info("[MFT] scan_volume完成: total=%d, elapsed=%.2fs", total, elapsed)
        return total, elapsed
    except Exception as exc:
        logger.error("[MFT] scan_volume异常终止: %s", exc, exc_info=True)
        raise
    finally:
        kernel32.CloseHandle(vol_handle)
