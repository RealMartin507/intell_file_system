"""
NTFS MFT 直读扫描器

通过 ctypes + DeviceIoControl (FSCTL_ENUM_USN_DATA) 直接枚举 NTFS MFT，
无需安装额外依赖，但需要管理员权限。

对外接口：
    is_admin()   -> bool
    scan_volume(drive_letter, batch_callback, batch_size, disk_label)
                 -> (total_count, elapsed_seconds)
"""

import ctypes
import ctypes.wintypes as wt
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from backend.utils.file_types import SHAPEFILE_EXTENSIONS, get_file_type

# ─── Windows API 常量 ──────────────────────────────────────────────────────────

GENERIC_READ         = 0x80000000
FILE_SHARE_READ      = 0x00000001
FILE_SHARE_WRITE     = 0x00000002
OPEN_EXISTING        = 3

FSCTL_ENUM_USN_DATA  = 0x000900B3

FILE_ATTRIBUTE_DIRECTORY     = 0x00000010
FILE_ATTRIBUTE_HIDDEN        = 0x00000002
FILE_ATTRIBUTE_SYSTEM        = 0x00000004

ERROR_HANDLE_EOF     = 38
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

# NTFS 根目录 MFT 记录号固定为 5
NTFS_ROOT_RECORD_NUM = 5

# FSCTL_ENUM_USN_DATA 输出缓冲区大小（1 MB）
_OUT_BUF_SIZE = 1 << 20

# ─── ctypes 结构体 ─────────────────────────────────────────────────────────────

class _MFT_ENUM_DATA_V0(ctypes.Structure):
    _fields_ = [
        ("StartFileReferenceNumber", ctypes.c_uint64),
        ("LowUsn",                   ctypes.c_int64),
        ("HighUsn",                  ctypes.c_int64),
    ]


class _USN_RECORD_V2_HDR(ctypes.Structure):
    """USN_RECORD_V2 固定头部（不含变长 FileName）"""
    _fields_ = [
        ("RecordLength",              wt.DWORD),
        ("MajorVersion",              wt.WORD),
        ("MinorVersion",              wt.WORD),
        ("FileReferenceNumber",       ctypes.c_uint64),
        ("ParentFileReferenceNumber", ctypes.c_uint64),
        ("Usn",                       ctypes.c_int64),
        ("TimeStamp",                 ctypes.c_int64),
        ("Reason",                    wt.DWORD),
        ("SourceInfo",                wt.DWORD),
        ("SecurityId",                wt.DWORD),
        ("FileAttributes",            wt.DWORD),
        ("FileNameLength",            wt.WORD),
        ("FileNameOffset",            wt.WORD),
    ]


class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wt.DWORD), ("dwHighDateTime", wt.DWORD)]


class _WIN32_FILE_ATTRIBUTE_DATA(ctypes.Structure):
    _fields_ = [
        ("dwFileAttributes", wt.DWORD),
        ("ftCreationTime",   _FILETIME),
        ("ftLastAccessTime", _FILETIME),
        ("ftLastWriteTime",  _FILETIME),
        ("nFileSizeHigh",    wt.DWORD),
        ("nFileSizeLow",     wt.DWORD),
    ]


_HDR_SIZE = ctypes.sizeof(_USN_RECORD_V2_HDR)

# FILETIME 纪元差：从 1601-01-01 到 1970-01-01 的 100ns 间隔数
_FT_EPOCH_DIFF = 116_444_736_000_000_000


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
            "NTFS MFT 直读需要管理员权限，请以管理员身份运行程序，"
            "或切换为 os.scandir 回退模式。"
        )


# ─── 工具函数 ─────────────────────────────────────────────────────────────────

def _rec_num(frn: int) -> int:
    """从文件引用号 (FRN) 中提取 MFT 记录号（低 48 位）。"""
    return frn & 0x0000_FFFF_FFFF_FFFF


def _filetime_to_iso(ft: _FILETIME) -> Optional[str]:
    """将 FILETIME 结构转换为 ISO 8601 字符串；全零时返回 None。"""
    try:
        val = (ft.dwHighDateTime << 32) | ft.dwLowDateTime
        if val == 0:
            return None
        ts = (val - _FT_EPOCH_DIFF) / 10_000_000
        return datetime.fromtimestamp(ts).isoformat()
    except (OSError, OverflowError, ValueError):
        return None


def _get_win32_attr(path: str) -> Optional[_WIN32_FILE_ATTRIBUTE_DATA]:
    """调用 GetFileAttributesExW 获取文件/目录属性（无需打开文件句柄）。"""
    data = _WIN32_FILE_ATTRIBUTE_DATA()
    ok = ctypes.windll.kernel32.GetFileAttributesExW(
        path, 0,  # GetFileExInfoStandard = 0
        ctypes.byref(data),
    )
    return data if ok else None


def _resolve_dir_path(
    rec_num: int,
    dir_map: dict[int, tuple[str, int]],
    drive_root: str,
) -> Optional[str]:
    """
    将目录 MFT 记录号解析为完整路径。
    drive_root 格式为 "C:\\"（含尾部反斜杠）。
    返回 None 表示孤立记录（父链中断）。
    """
    parts: list[str] = []
    current = rec_num
    for _ in range(512):  # 防无限循环
        if current == NTFS_ROOT_RECORD_NUM:
            break
        entry = dir_map.get(current)
        if entry is None:
            return None
        name, parent = entry
        parts.append(name)
        current = parent
    parts.reverse()
    return os.path.join(drive_root, *parts) if parts else drive_root


# ─── 记录构建 ─────────────────────────────────────────────────────────────────

def _file_record(
    full_path: str,
    file_name: str,
    depth: int,
    disk_label: str,
) -> Optional[dict]:
    """构建与 scanner.py _file_record() 格式一致的 dict。"""
    path = Path(full_path)
    stem = path.stem
    ext = path.suffix.lower()

    data = _get_win32_attr(full_path)
    if data is None:
        size, ctime, mtime = 0, None, None
    else:
        size = (data.nFileSizeHigh << 32) | data.nFileSizeLow
        ctime = _filetime_to_iso(data.ftCreationTime)
        mtime = _filetime_to_iso(data.ftLastWriteTime)

    shapefile_group = str(path.parent / stem) if ext in SHAPEFILE_EXTENSIONS else None

    return {
        "file_name":        file_name,
        "file_name_no_ext": stem,
        "extension":        ext,
        "file_size":        size,
        "created_time":     ctime,
        "modified_time":    mtime,
        "file_path":        full_path,
        "parent_dir":       str(path.parent),
        "dir_depth":        depth,
        "file_type":        get_file_type(ext),
        "shapefile_group":  shapefile_group,
        "disk_label":       disk_label,
    }


def _gdb_record(full_path: str, depth: int, disk_label: str) -> dict:
    """.gdb 目录作为单条 gis_vector 记录（不递归内部文件）。"""
    path = Path(full_path)
    data = _get_win32_attr(full_path)
    ctime = _filetime_to_iso(data.ftCreationTime) if data else None
    mtime = _filetime_to_iso(data.ftLastWriteTime) if data else None

    return {
        "file_name":        path.name,
        "file_name_no_ext": path.stem,
        "extension":        ".gdb",
        "file_size":        0,
        "created_time":     ctime,
        "modified_time":    mtime,
        "file_path":        full_path,
        "parent_dir":       str(path.parent),
        "dir_depth":        depth,
        "file_type":        "gis_vector",
        "shapefile_group":  None,
        "disk_label":       disk_label,
    }


# ─── 主扫描接口 ───────────────────────────────────────────────────────────────

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
        OSError         : 卷句柄打开失败（盘符不存在）
        RuntimeError    : DeviceIoControl 失败（非 NTFS 或 API 错误）
    """
    check_admin()

    drive = drive_letter.strip(":\\ ").upper()  # "C"
    if not drive or len(drive) != 1 or not drive.isalpha():
        raise ValueError(f"无效盘符：{drive_letter!r}")

    volume_path = f"\\\\.\\{drive}:"
    drive_root  = f"{drive}:\\"           # "C:\\"

    kernel32 = ctypes.windll.kernel32

    handle = kernel32.CreateFileW(
        volume_path,
        GENERIC_READ,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        None,
        OPEN_EXISTING,
        0,
        None,
    )
    if handle == INVALID_HANDLE_VALUE:
        err = kernel32.GetLastError()
        raise OSError(f"无法打开卷 {volume_path}，GetLastError={err}")

    try:
        return _do_scan(handle, drive_root, batch_callback, batch_size, disk_label, kernel32)
    finally:
        kernel32.CloseHandle(handle)


# ─── 内部实现 ─────────────────────────────────────────────────────────────────

def _iter_usn_records(handle, kernel32, out_buf, med):
    """
    生成器：反复调用 FSCTL_ENUM_USN_DATA，逐条 yield USN 记录的
    (hdr: _USN_RECORD_V2_HDR, name: str)。
    遇到 ERROR_HANDLE_EOF 或缓冲区耗尽时停止。
    """
    bytes_returned = wt.DWORD(0)

    while True:
        ok = kernel32.DeviceIoControl(
            handle,
            FSCTL_ENUM_USN_DATA,
            ctypes.byref(med),
            ctypes.sizeof(med),
            out_buf,
            _OUT_BUF_SIZE,
            ctypes.byref(bytes_returned),
            None,
        )

        if not ok:
            err = kernel32.GetLastError()
            if err == ERROR_HANDLE_EOF:
                return
            raise RuntimeError(
                f"FSCTL_ENUM_USN_DATA 失败，GetLastError={err}。"
                "请确认目标卷为 NTFS 格式且具备管理员权限。"
            )

        total = bytes_returned.value
        if total <= 8:
            return

        # 前 8 字节：下次迭代的 StartFileReferenceNumber
        next_frn = ctypes.cast(out_buf, ctypes.POINTER(ctypes.c_uint64))[0]
        med.StartFileReferenceNumber = next_frn

        offset = 8
        while offset + _HDR_SIZE <= total:
            try:
                hdr = _USN_RECORD_V2_HDR.from_buffer_copy(out_buf, offset)
            except Exception:
                break
            if hdr.RecordLength == 0:
                break

            name_start = offset + hdr.FileNameOffset
            name_end   = name_start + hdr.FileNameLength
            if name_end <= total:
                try:
                    name = out_buf[name_start:name_end].decode("utf-16-le")
                except UnicodeDecodeError:
                    name = ""
            else:
                name = ""

            yield hdr, name
            offset += hdr.RecordLength


def _do_scan(
    handle,
    drive_root: str,
    batch_callback: Callable[[list[dict]], None],
    batch_size: int,
    disk_label: str,
    kernel32,
) -> tuple[int, float]:
    t0 = time.monotonic()
    out_buf = ctypes.create_string_buffer(_OUT_BUF_SIZE)

    # ── 第一遍：枚举所有目录，建立 rec_num → (name, parent_rec_num) 映射 ──────
    # .gdb 目录不加入 dir_map，使其内部文件无法解析路径（从而自动跳过）
    dir_map: dict[int, tuple[str, int]] = {}

    med = _MFT_ENUM_DATA_V0(
        StartFileReferenceNumber=0,
        LowUsn=0,
        HighUsn=0x7FFF_FFFF_FFFF_FFFF,
    )
    for hdr, name in _iter_usn_records(handle, kernel32, out_buf, med):
        if hdr.FileAttributes & FILE_ATTRIBUTE_DIRECTORY:
            if not name.lower().endswith(".gdb"):
                rec  = _rec_num(hdr.FileReferenceNumber)
                prec = _rec_num(hdr.ParentFileReferenceNumber)
                dir_map[rec] = (name, prec)

    # ── 第二遍：枚举所有文件，构建记录并分批回调 ─────────────────────────────
    med.StartFileReferenceNumber = 0
    root_depth = len(Path(drive_root).parts)  # "C:\\" → 1
    batch: list[dict] = []
    total_count = 0

    for hdr, name in _iter_usn_records(handle, kernel32, out_buf, med):
        attrs  = hdr.FileAttributes
        is_dir = bool(attrs & FILE_ATTRIBUTE_DIRECTORY)

        if is_dir:
            # 仅处理 .gdb 目录（作为 gis_vector 记录）
            if not name.lower().endswith(".gdb"):
                continue
            parent_rec  = _rec_num(hdr.ParentFileReferenceNumber)
            parent_path = _resolve_dir_path(parent_rec, dir_map, drive_root)
            if parent_path is None:
                continue
            full_path = os.path.join(parent_path, name)
            depth     = len(Path(full_path).parts) - root_depth
            rec       = _gdb_record(full_path, depth, disk_label)
        else:
            # 跳过同时具有系统+隐藏属性的文件（OS 内核文件）
            if (attrs & FILE_ATTRIBUTE_HIDDEN) and (attrs & FILE_ATTRIBUTE_SYSTEM):
                continue

            parent_rec  = _rec_num(hdr.ParentFileReferenceNumber)
            parent_path = _resolve_dir_path(parent_rec, dir_map, drive_root)
            if parent_path is None:
                # 父目录无法解析：孤立文件或 .gdb 内部文件，跳过
                continue
            full_path = os.path.join(parent_path, name)
            depth     = len(Path(full_path).parts) - root_depth
            rec       = _file_record(full_path, name, depth, disk_label)
            if rec is None:
                continue

        batch.append(rec)
        if len(batch) >= batch_size:
            batch_callback(batch)
            total_count += len(batch)
            batch = []

    if batch:
        batch_callback(batch)
        total_count += len(batch)

    return total_count, time.monotonic() - t0
