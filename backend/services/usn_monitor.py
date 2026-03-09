"""NTFS USN Journal 变更监控服务。

用 ctypes 调用 Windows API 监听 NTFS 卷的文件变更，实时更新 files 表和 files_fts 索引。

要求：以管理员权限运行（FSCTL_READ_USN_JOURNAL 需要 SeManageVolumePrivilege）。

公开接口：
  start_monitoring(roots)  — 启动监控
  stop_monitoring()        — 停止监控
  get_status()             — 查询状态
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import fnmatch
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from backend.config import get_config
from backend.database import get_db
from backend.utils.file_types import SHAPEFILE_EXTENSIONS, get_file_type

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Windows 常量
# ─────────────────────────────────────────────────────────────────────────────

FSCTL_QUERY_USN_JOURNAL = 0x000900F4
FSCTL_READ_USN_JOURNAL  = 0x000900BB

# USN Reason 标志位
USN_REASON_DATA_OVERWRITE  = 0x00000001
USN_REASON_DATA_EXTEND     = 0x00000002
USN_REASON_DATA_TRUNCATION = 0x00000004
USN_REASON_FILE_CREATE     = 0x00000100
USN_REASON_FILE_DELETE     = 0x00000200
USN_REASON_RENAME_OLD_NAME = 0x00001000
USN_REASON_RENAME_NEW_NAME = 0x00002000
USN_REASON_CLOSE           = 0x80000000

# 监听的 Reason 掩码（传给 ReasonMask）
_WATCH_MASK = (
    USN_REASON_DATA_OVERWRITE
    | USN_REASON_DATA_EXTEND
    | USN_REASON_DATA_TRUNCATION
    | USN_REASON_FILE_CREATE
    | USN_REASON_FILE_DELETE
    | USN_REASON_RENAME_OLD_NAME
    | USN_REASON_RENAME_NEW_NAME
    | USN_REASON_CLOSE
)

_MODIFY_REASONS = (
    USN_REASON_DATA_OVERWRITE
    | USN_REASON_DATA_EXTEND
    | USN_REASON_DATA_TRUNCATION
)

# CreateFile / 句柄相关常量
FILE_SHARE_READ              = 0x00000001
FILE_SHARE_WRITE             = 0x00000002
FILE_SHARE_DELETE            = 0x00000004
OPEN_EXISTING                = 3
FILE_FLAG_BACKUP_SEMANTICS   = 0x02000000
FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
FILE_ATTRIBUTE_DIRECTORY     = 0x00000010

# GetFinalPathNameByHandle 标志
FILE_NAME_NORMALIZED = 0x0
VOLUME_NAME_DOS      = 0x0

# Windows 错误码
ERROR_HANDLE_EOF            = 38
ERROR_JOURNAL_ENTRY_DELETED = 1181
ERROR_ACCESS_DENIED         = 5

# 监控参数
_POLL_INTERVAL = 2.0    # 无新事件时休眠秒数
_READ_BUF_SIZE = 65536  # DeviceIoControl 输出缓冲区大小（字节）
_MAX_RESTARTS  = 3      # 线程崩溃后最多重启次数


# ─────────────────────────────────────────────────────────────────────────────
# ctypes 结构体
# ─────────────────────────────────────────────────────────────────────────────

class USN_JOURNAL_DATA(ctypes.Structure):
    """FSCTL_QUERY_USN_JOURNAL 输出（对应 SDK 的 USN_JOURNAL_DATA_V0）。"""
    _fields_ = [
        ("UsnJournalID",    ctypes.c_uint64),
        ("FirstUsn",        ctypes.c_int64),
        ("NextUsn",         ctypes.c_int64),
        ("LowestValidUsn",  ctypes.c_int64),
        ("MaxUsn",          ctypes.c_int64),
        ("MaximumSize",     ctypes.c_uint64),
        ("AllocationDelta", ctypes.c_uint64),
    ]


class READ_USN_JOURNAL_DATA(ctypes.Structure):
    """FSCTL_READ_USN_JOURNAL 输入（对应 SDK 的 READ_USN_JOURNAL_DATA_V0）。"""
    _fields_ = [
        ("StartUsn",          ctypes.c_int64),
        ("ReasonMask",        ctypes.c_uint32),
        ("ReturnOnlyOnClose", ctypes.c_uint32),
        ("Timeout",           ctypes.c_uint64),
        ("BytesToWaitFor",    ctypes.c_uint64),
        ("UsnJournalID",      ctypes.c_uint64),
    ]


class USN_RECORD(ctypes.Structure):
    """
    USN 记录头（V2 格式，固定部分 60 字节）。
    FileName 从 offset=FileNameOffset 处开始，长度 FileNameLength 字节（UTF-16LE）。
    """
    _fields_ = [
        ("RecordLength",              ctypes.c_uint32),
        ("MajorVersion",              ctypes.c_uint16),
        ("MinorVersion",              ctypes.c_uint16),
        ("FileReferenceNumber",       ctypes.c_uint64),
        ("ParentFileReferenceNumber", ctypes.c_uint64),
        ("Usn",                       ctypes.c_int64),
        ("TimeStamp",                 ctypes.c_int64),
        ("Reason",                    ctypes.c_uint32),
        ("SourceInfo",                ctypes.c_uint32),
        ("SecurityId",                ctypes.c_uint32),
        ("FileAttributes",            ctypes.c_uint32),
        ("FileNameLength",            ctypes.c_uint16),
        ("FileNameOffset",            ctypes.c_uint16),
    ]


class _FileIdUnion(ctypes.Union):
    _fields_ = [
        ("FileId", ctypes.c_int64),
        ("_pad",   ctypes.c_uint8 * 16),  # 与 GUID/FILE_ID_128 对齐（16 字节）
    ]


class FILE_ID_DESCRIPTOR(ctypes.Structure):
    """OpenFileById 所需的文件 ID 描述符。Type=0 表示使用 64-bit FRN。"""
    _anonymous_ = ("_u",)
    _fields_ = [
        ("dwSize", ctypes.c_uint32),
        ("Type",   ctypes.c_uint32),  # 0 = FileIdType（使用 64-bit FRN）
        ("_u",     _FileIdUnion),
    ]


# ─────────────────────────────────────────────────────────────────────────────
# 数据类
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class UsnEvent:
    """解析后的单条 USN 事件。"""
    usn:             int
    reason:          int
    frn:             int   # FileReferenceNumber（文件自身 FRN）
    parent_frn:      int   # ParentFileReferenceNumber（父目录 FRN）
    filename:        str   # 文件名（不含路径）
    file_attributes: int


@dataclass
class MonitorState:
    """单个卷的监控运行状态。"""
    volume:           str
    status:           str = "stopped"  # stopped / running / error
    events_processed: int = 0
    upserted:         int = 0
    deleted:          int = 0
    skipped:          int = 0
    started_at:       str = ""
    last_error:       str = ""
    restart_count:    int = 0


# ─────────────────────────────────────────────────────────────────────────────
# Windows API 封装
# ─────────────────────────────────────────────────────────────────────────────

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_INVALID_HANDLE = wintypes.HANDLE(-1).value


def _open_volume(volume_path: str) -> int:
    """
    打开卷句柄，用于 DeviceIoControl 和 OpenFileById hint。
    volume_path 格式：r"\\.\E:"
    失败时抛 PermissionError（无管理员权限）或 OSError。
    """
    handle = _kernel32.CreateFileW(
        volume_path,
        0,  # dwDesiredAccess=0（仅用于 IOCTL，无需读写权限）
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
        None,
        OPEN_EXISTING,
        FILE_FLAG_BACKUP_SEMANTICS,
        None,
    )
    if handle == _INVALID_HANDLE:
        err = ctypes.get_last_error()
        if err == ERROR_ACCESS_DENIED:
            raise PermissionError(
                f"打开卷 {volume_path} 失败（错误码 {err}）：请以管理员权限运行服务"
            )
        raise OSError(f"打开卷 {volume_path} 失败，错误码 {err}")
    return handle


def _frn_to_path(vol_handle: int, frn: int) -> Optional[str]:
    """
    通过 OpenFileById + GetFinalPathNameByHandle 将 FRN 解析为绝对路径。
    失败（文件已删除等竞态）时返回 None，不抛异常。
    """
    fid = FILE_ID_DESCRIPTOR()
    fid.dwSize = ctypes.sizeof(FILE_ID_DESCRIPTOR)
    fid.Type   = 0
    # NTFS FRN 最大 48-bit，安全转为有符号 int64
    fid.FileId = ctypes.c_int64(frn & 0xFFFF_FFFF_FFFF).value

    file_handle = _kernel32.OpenFileById(
        vol_handle,
        ctypes.byref(fid),
        0,  # dwDesiredAccess=0，仅查询路径
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
        None,
        FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT,
    )
    if file_handle == _INVALID_HANDLE:
        return None

    try:
        buf = ctypes.create_unicode_buffer(32768)
        length = _kernel32.GetFinalPathNameByHandleW(
            file_handle,
            buf,
            32768,
            FILE_NAME_NORMALIZED | VOLUME_NAME_DOS,
        )
        if length == 0:
            return None
        path = buf.value
        # 去除 \\?\ 长路径前缀，统一为标准 Win32 路径格式
        if path.startswith("\\\\?\\"):
            path = path[4:]
        return path
    finally:
        _kernel32.CloseHandle(file_handle)


def _deleted_path_from_parent(
    vol_handle: int, parent_frn: int, filename: str
) -> Optional[str]:
    """
    针对删除事件：文件已删除，改为解析父目录 FRN 再拼接 filename。
    父目录通常仍存在；若也解析失败则返回 None。
    """
    parent_path = _frn_to_path(vol_handle, parent_frn)
    if parent_path:
        return str(Path(parent_path) / filename)
    return None


# ─────────────────────────────────────────────────────────────────────────────
# USN 缓冲区解析
# ─────────────────────────────────────────────────────────────────────────────

_USN_RECORD_HEADER_SIZE = ctypes.sizeof(USN_RECORD)  # 60 字节


def _parse_usn_buffer(buf: bytes) -> tuple[int, list[UsnEvent]]:
    """
    解析 FSCTL_READ_USN_JOURNAL 输出缓冲区。
    格式：[8 字节 NextUsn][USN_RECORD_V2][USN_RECORD_V2]...
    返回 (next_usn, events)。
    """
    if len(buf) < 8:
        return 0, []

    next_usn = int.from_bytes(buf[:8], "little", signed=True)
    events: list[UsnEvent] = []
    offset = 8

    while offset + _USN_RECORD_HEADER_SIZE <= len(buf):
        rec = USN_RECORD.from_buffer_copy(buf, offset)
        record_length = rec.RecordLength

        # 防御：RecordLength 必须合法（最小 = 结构头 + 至少 1 个字符）
        if record_length < _USN_RECORD_HEADER_SIZE or offset + record_length > len(buf):
            break

        fn_start = offset + rec.FileNameOffset
        fn_end   = fn_start + rec.FileNameLength
        try:
            filename = buf[fn_start:fn_end].decode("utf-16-le")
        except (UnicodeDecodeError, ValueError):
            filename = ""

        events.append(UsnEvent(
            usn             = rec.Usn,
            reason          = rec.Reason,
            frn             = rec.FileReferenceNumber,
            parent_frn      = rec.ParentFileReferenceNumber,
            filename        = filename,
            file_attributes = rec.FileAttributes,
        ))

        # RecordLength 已按 8 字节对齐
        offset += record_length

    return next_usn, events


# ─────────────────────────────────────────────────────────────────────────────
# 排除规则（与 scanner.py 的 _matches_patterns 保持一致）
# ─────────────────────────────────────────────────────────────────────────────

def _matches_patterns(name: str, patterns: list) -> bool:
    return any(fnmatch.fnmatch(name, p) for p in patterns)


def _is_under_roots(path: str, roots: list) -> bool:
    """路径是否在 scan_roots 列表中的某个根路径之下（大小写不敏感）。"""
    path_lower = path.lower()
    return any(path_lower.startswith(r.lower()) for r in roots)


def _is_excluded(path: str, exclude_dirs: list, exclude_patterns: list) -> bool:
    """按路径各分段检查 exclude_dirs（精确匹配）和 exclude_patterns（fnmatch）。"""
    for part in Path(path).parts:
        if part in exclude_dirs:
            return True
        if _matches_patterns(part, exclude_patterns):
            return True
    return False


def _is_inside_gdb(path: str) -> bool:
    """路径是否位于某个 .gdb 目录内部（.gdb 目录本身不算"内部"）。"""
    parts = Path(path).parts
    # 只检查祖先路径段，不检查最后一段（文件名自身）
    for part in parts[:-1]:
        if part.lower().endswith(".gdb"):
            return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# 数据库写入（复用 scanner.py 的 SQL 模式）
# ─────────────────────────────────────────────────────────────────────────────

def _build_record(path: str, disk_label: str, volume_root: str) -> Optional[dict]:
    """
    构建文件记录字典（字段与 scanner._file_record 一致）。
    .gdb 目录：file_size=0, extension=".gdb", file_type="gis_vector"。
    文件不可访问时返回 None。
    """
    p = Path(path)
    is_gdb = p.is_dir() and p.suffix.lower() == ".gdb"

    try:
        stat  = p.stat()
        size  = 0 if is_gdb else stat.st_size
        ctime = datetime.fromtimestamp(stat.st_ctime).strftime("%Y-%m-%d %H:%M:%S")
        mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    except OSError:
        return None  # 文件在 stat 时已消失（竞态），跳过

    ext        = ".gdb" if is_gdb else p.suffix.lower()
    root_depth = len(Path(volume_root).parts)
    depth      = len(p.parts) - root_depth

    shapefile_group = None
    if not is_gdb and ext in SHAPEFILE_EXTENSIONS:
        shapefile_group = str(p.parent / p.stem)

    return {
        "file_name":        p.name,
        "file_name_no_ext": p.stem,
        "extension":        ext,
        "file_size":        size,
        "created_time":     ctime,
        "modified_time":    mtime,
        "file_path":        str(p),
        "parent_dir":       str(p.parent),
        "dir_depth":        depth,
        "file_type":        "gis_vector" if is_gdb else get_file_type(ext),
        "shapefile_group":  shapefile_group,
        "disk_label":       disk_label,
    }


_UPSERT_SQL = """
INSERT OR REPLACE INTO files
    (file_name, file_name_no_ext, extension, file_size, created_time, modified_time,
     file_path, parent_dir, dir_depth, file_type, shapefile_group, disk_label)
VALUES
    (:file_name, :file_name_no_ext, :extension, :file_size, :created_time, :modified_time,
     :file_path, :parent_dir, :dir_depth, :file_type, :shapefile_group, :disk_label)
"""


def _db_upsert(conn, path: str, disk_label: str, volume_root: str) -> bool:
    """
    INSERT OR REPLACE 文件记录 + 同步 FTS5 索引。
    顺序：先删旧 FTS 条目 → INSERT OR REPLACE files → 查新 id → 插新 FTS 条目。
    （INSERT OR REPLACE 会重新分配 id，必须重取 id 再写 FTS）
    返回 True 表示成功；False 表示文件不可访问。
    """
    record = _build_record(path, disk_label, volume_root)
    if record is None:
        return False

    # 先删旧 FTS 条目（若记录已存在）
    existing = conn.execute(
        "SELECT id FROM files WHERE file_path = ?", (path,)
    ).fetchone()
    if existing:
        conn.execute("DELETE FROM files_fts WHERE rowid = ?", (existing[0],))

    # INSERT OR REPLACE
    conn.execute(_UPSERT_SQL, record)

    # 重新查 id（REPLACE 后 id 可能变化），插入 FTS
    new_row = conn.execute(
        "SELECT id FROM files WHERE file_path = ?", (path,)
    ).fetchone()
    if new_row:
        conn.execute(
            "INSERT INTO files_fts(rowid, file_name, file_path, file_type) "
            "SELECT id, file_name, file_path, file_type FROM files WHERE id = ?",
            (new_row[0],),
        )
    return True


def _db_delete(conn, path: str) -> bool:
    """
    删除 files 表记录及其 FTS 索引条目。
    顺序：先删 FTS（需 files 记录仍在）→ 再删 files。
    返回 True 表示找到并删除了记录。
    """
    row = conn.execute(
        "SELECT id FROM files WHERE file_path = ?", (path,)
    ).fetchone()
    if not row:
        return False
    conn.execute("DELETE FROM files_fts WHERE rowid = ?", (row[0],))
    conn.execute("DELETE FROM files WHERE id = ?", (row[0],))
    return True


def _db_lookup_by_name(conn, filename: str) -> Optional[str]:
    """
    兜底：FRN 和父目录解析都失败时，按 file_name 查最近修改的路径（用于删除事件）。
    """
    row = conn.execute(
        "SELECT file_path FROM files WHERE file_name = ? ORDER BY modified_time DESC LIMIT 1",
        (filename,),
    ).fetchone()
    return row[0] if row else None


# ─────────────────────────────────────────────────────────────────────────────
# 事件处理
# ─────────────────────────────────────────────────────────────────────────────

def _process_events(
    events:           list[UsnEvent],
    vol_handle:       int,
    volume_root:      str,
    disk_label:       str,
    scan_roots:       list,
    exclude_dirs:     list,
    exclude_patterns: list,
    state:            MonitorState,
) -> None:
    """
    对一批 USN 事件进行分类、过滤、路径解析，写入/删除 DB。
    每次调用独立开一个 DB 连接，处理完后 commit 关闭。
    """
    conn = get_db()
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")

    try:
        for evt in events:
            is_dir = bool(evt.file_attributes & FILE_ATTRIBUTE_DIRECTORY)

            # 1. 事件分类（优先级：DELETE > RENAME_OLD > CREATE/RENAME_NEW/MODIFY）
            if evt.reason & USN_REASON_FILE_DELETE:
                action = "delete"
            elif evt.reason & USN_REASON_RENAME_OLD_NAME:
                action = "delete"  # 旧路径消失
            elif evt.reason & (USN_REASON_FILE_CREATE | USN_REASON_RENAME_NEW_NAME | _MODIFY_REASONS):
                action = "upsert"
            else:
                continue  # 其他 Reason（如 BASIC_INFO_CHANGE），跳过

            # 2. 目录过滤：只保留 .gdb 目录事件，跳过其他目录
            if is_dir and not evt.filename.lower().endswith(".gdb"):
                continue

            # 3. 路径解析
            if action == "upsert":
                path = _frn_to_path(vol_handle, evt.frn)
                if path is None:
                    state.skipped += 1
                    continue
            else:  # delete
                path = _deleted_path_from_parent(vol_handle, evt.parent_frn, evt.filename)
                if path is None:
                    # 兜底：按文件名在 DB 中查找
                    tmp = get_db()
                    try:
                        path = _db_lookup_by_name(tmp, evt.filename)
                    finally:
                        tmp.close()
                if path is None:
                    state.skipped += 1
                    continue

            # 4. 仅处理 scan_roots 下的路径
            if not _is_under_roots(path, scan_roots):
                continue

            # 5. 排除规则过滤
            if _is_excluded(path, exclude_dirs, exclude_patterns):
                continue

            # 6. .gdb 内部文件过滤（只记录 .gdb 目录本身）
            if _is_inside_gdb(path):
                continue

            # 7. 执行 DB 操作
            if action == "upsert":
                if _db_upsert(conn, path, disk_label, volume_root):
                    state.upserted += 1
                else:
                    state.skipped += 1
            else:
                if _db_delete(conn, path):
                    state.deleted += 1

        conn.commit()
        state.events_processed += len(events)

    except Exception as exc:
        logger.error("[USN] 事件处理异常：%s", exc, exc_info=True)
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# 单卷监控主循环
# ─────────────────────────────────────────────────────────────────────────────

def _monitor_volume_loop(
    volume:           str,
    volume_root:      str,
    disk_label:       str,
    scan_roots:       list,
    exclude_dirs:     list,
    exclude_patterns: list,
    stop_event:       threading.Event,
    state:            MonitorState,
) -> None:
    """
    单卷 USN Journal 轮询主循环。
    - 以 NextUsn 为起点，跳过历史记录，仅捕获启动后的新变更
    - ReturnOnlyOnClose=1：等文件关闭后再处理，避免同文件多次写入重复触发
    - Timeout=0, BytesToWaitFor=0：非阻塞轮询，配合 stop_event 可干净退出
    """
    vol_path   = r"\\.\\" + volume   # r"\\.\E:"
    vol_handle = _open_volume(vol_path)  # 可能抛 PermissionError / OSError

    try:
        # 查询 USN Journal 元数据
        journal_data  = USN_JOURNAL_DATA()
        bytes_returned = ctypes.c_uint32(0)

        ok = _kernel32.DeviceIoControl(
            vol_handle,
            FSCTL_QUERY_USN_JOURNAL,
            None, 0,
            ctypes.byref(journal_data),
            ctypes.sizeof(journal_data),
            ctypes.byref(bytes_returned),
            None,
        )
        if not ok:
            err = ctypes.get_last_error()
            if err == ERROR_ACCESS_DENIED:
                raise PermissionError(
                    f"FSCTL_QUERY_USN_JOURNAL 失败：需要管理员权限（错误码 {err}）"
                )
            raise OSError(f"FSCTL_QUERY_USN_JOURNAL 失败，错误码 {err}")

        current_usn = journal_data.NextUsn      # 从当前末尾开始，跳过历史
        journal_id  = journal_data.UsnJournalID
        logger.info(
            "[USN] 卷 %s 监控启动，JournalID=%#x, StartUsn=%d",
            volume, journal_id, current_usn,
        )

        buf = (ctypes.c_byte * _READ_BUF_SIZE)()

        while not stop_event.is_set():
            read_data = READ_USN_JOURNAL_DATA()
            read_data.StartUsn          = current_usn
            read_data.ReasonMask        = _WATCH_MASK
            read_data.ReturnOnlyOnClose = 1   # 聚合同文件多次写入，仅在 close 时返回
            read_data.Timeout           = 0   # 非阻塞
            read_data.BytesToWaitFor    = 0
            read_data.UsnJournalID      = journal_id

            ok = _kernel32.DeviceIoControl(
                vol_handle,
                FSCTL_READ_USN_JOURNAL,
                ctypes.byref(read_data),
                ctypes.sizeof(read_data),
                buf,
                _READ_BUF_SIZE,
                ctypes.byref(bytes_returned),
                None,
            )

            if not ok:
                err = ctypes.get_last_error()
                if err == ERROR_HANDLE_EOF:
                    # 已到日志末尾，无新事件，休眠后重试
                    stop_event.wait(timeout=_POLL_INTERVAL)
                    continue
                if err == ERROR_JOURNAL_ENTRY_DELETED:
                    # 日志截断：重新查询元数据，从最低有效 USN 开始
                    logger.warning("[USN] 卷 %s USN 日志截断，重新初始化", volume)
                    ok2 = _kernel32.DeviceIoControl(
                        vol_handle,
                        FSCTL_QUERY_USN_JOURNAL,
                        None, 0,
                        ctypes.byref(journal_data),
                        ctypes.sizeof(journal_data),
                        ctypes.byref(bytes_returned),
                        None,
                    )
                    if ok2:
                        current_usn = journal_data.LowestValidUsn
                        journal_id  = journal_data.UsnJournalID
                    continue
                if err == ERROR_ACCESS_DENIED:
                    raise PermissionError(
                        f"FSCTL_READ_USN_JOURNAL 失败：需要管理员权限（错误码 {err}）"
                    )
                raise OSError(f"FSCTL_READ_USN_JOURNAL 失败，错误码 {err}")

            raw      = bytes(buf[:bytes_returned.value])
            next_usn, events = _parse_usn_buffer(raw)

            if events:
                _process_events(
                    events, vol_handle, volume_root, disk_label,
                    scan_roots, exclude_dirs, exclude_patterns, state,
                )

            if next_usn > current_usn:
                current_usn = next_usn
            elif not events:
                # USN 未推进且无事件，休眠避免 CPU 空转
                stop_event.wait(timeout=_POLL_INTERVAL)

    finally:
        _kernel32.CloseHandle(vol_handle)


# ─────────────────────────────────────────────────────────────────────────────
# 线程管理
# ─────────────────────────────────────────────────────────────────────────────

class USNMonitorManager:
    """
    管理多个 NTFS 卷的 USN Journal 监控线程。
    每个卷独立一个 daemon 线程，异常时自动重启（最多 3 次，指数退避）。
    """

    def __init__(self) -> None:
        self._threads:     dict[str, threading.Thread] = {}
        self._stop_events: dict[str, threading.Event]  = {}
        self._states:      dict[str, MonitorState]     = {}
        self._lock = threading.Lock()

    def start_monitoring(self, roots: list) -> dict:
        """
        启动对 roots 路径列表的监控。
        提取卷符（如 "E:"），去重后为每个卷启动独立 daemon 线程。
        若卷线程已存活则跳过，不重启。
        """
        cfg              = get_config()
        exclude_dirs     = cfg.get("exclude_dirs", [])
        exclude_patterns = cfg.get("exclude_patterns", [])

        # 统一 scan_roots 为以 \\ 结尾的格式
        normalized_roots = [
            (r if r.endswith("\\") else r + "\\") for r in roots
        ]

        started: list = []
        already:  list = []

        with self._lock:
            for root in roots:
                volume      = root[:2].upper()                        # "E:"
                volume_root = root if root.endswith("\\") else root + "\\"

                if volume in self._threads and self._threads[volume].is_alive():
                    already.append(volume)
                    continue

                disk_label = _get_disk_label(cfg, root)
                stop_event = threading.Event()
                state      = MonitorState(
                    volume     = volume,
                    status     = "running",
                    started_at = datetime.now().isoformat(),
                )

                self._stop_events[volume] = stop_event
                self._states[volume]      = state

                t = threading.Thread(
                    target = self._run_with_retry,
                    args   = (
                        volume, volume_root, disk_label,
                        normalized_roots,
                        exclude_dirs, exclude_patterns,
                        stop_event, state,
                    ),
                    name   = f"usn-monitor-{volume[0]}",
                    daemon = True,
                )
                t.start()
                self._threads[volume] = t
                started.append(volume)

        return {"started": started, "already_running": already}

    def _run_with_retry(
        self,
        volume:           str,
        volume_root:      str,
        disk_label:       str,
        scan_roots:       list,
        exclude_dirs:     list,
        exclude_patterns: list,
        stop_event:       threading.Event,
        state:            MonitorState,
    ) -> None:
        """带指数退避自动重启的监控线程入口（在 daemon 线程中运行）。"""
        for attempt in range(_MAX_RESTARTS + 1):
            if stop_event.is_set():
                break
            try:
                _monitor_volume_loop(
                    volume, volume_root, disk_label,
                    scan_roots, exclude_dirs, exclude_patterns,
                    stop_event, state,
                )
                break  # 正常退出（stop_event 被设置）
            except PermissionError as exc:
                # 权限错误不重试（重试也没用）
                state.status     = "error"
                state.last_error = str(exc)
                logger.error("[USN] 卷 %s 权限错误，不再重试：%s", volume, exc)
                break
            except Exception as exc:
                state.last_error    = str(exc)
                state.restart_count = attempt
                logger.error(
                    "[USN] 卷 %s 监控线程异常（第 %d/%d 次）：%s",
                    volume, attempt + 1, _MAX_RESTARTS, exc,
                    exc_info=True,
                )
                if attempt < _MAX_RESTARTS and not stop_event.is_set():
                    wait_sec = 2 ** attempt  # 指数退避：1s, 2s, 4s
                    logger.info("[USN] 卷 %s 将在 %ds 后重启", volume, wait_sec)
                    stop_event.wait(timeout=float(wait_sec))
                else:
                    state.status = "error"
                    break

        # 线程退出后更新最终状态
        if state.status == "running":
            state.status = "error" if state.last_error else "stopped"

    def stop_monitoring(self) -> dict:
        """停止所有卷的监控线程，等待退出（超时 5 秒）。"""
        with self._lock:
            volumes = list(self._stop_events.keys())
            for ev in self._stop_events.values():
                ev.set()

        for volume in volumes:
            t = self._threads.get(volume)
            if t and t.is_alive():
                t.join(timeout=5.0)

        with self._lock:
            self._threads.clear()
            self._stop_events.clear()
            for s in self._states.values():
                if s.status == "running":
                    s.status = "stopped"

        return {"stopped": volumes}

    def get_status(self) -> dict:
        """返回所有卷的监控状态，供 API 端点使用。"""
        with self._lock:
            watching_volumes = [
                {
                    "volume":           s.volume,
                    "status":           s.status,
                    "events_processed": s.events_processed,
                    "upserted":         s.upserted,
                    "deleted":          s.deleted,
                    "skipped":          s.skipped,
                    "started_at":       s.started_at,
                    "restart_count":    s.restart_count,
                    "last_error":       s.last_error,
                }
                for s in self._states.values()
            ]
            total_events = sum(s.events_processed for s in self._states.values())
            running      = any(s.status == "running" for s in self._states.values())

        return {
            "running":          running,
            "watching_volumes": watching_volumes,
            "events_processed": total_events,
        }


# ─────────────────────────────────────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────────────────────────────────────

def _get_disk_label(cfg: dict, root: str) -> str:
    """从配置的 scan_roots 中按路径匹配 disk_label。"""
    req = root.rstrip("\\").rstrip("/").lower()
    for r in cfg.get("scan_roots", []):
        cfg_path = r.get("path", "").rstrip("\\").rstrip("/").lower()
        if cfg_path == req:
            return r.get("disk_label", "")
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# 公开 API（全局单例）
# ─────────────────────────────────────────────────────────────────────────────

_manager = USNMonitorManager()


def start_monitoring(roots: list) -> dict:
    """启动对指定路径列表的 USN Journal 监控。"""
    return _manager.start_monitoring(roots)


def stop_monitoring() -> dict:
    """停止所有 USN Journal 监控线程。"""
    return _manager.stop_monitoring()


def get_status() -> dict:
    """返回监控状态字典，包含各卷的统计信息。"""
    return _manager.get_status()
