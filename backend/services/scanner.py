"""
文件扫描服务

职责：
- 全量扫描：递归遍历目录，提取文件元数据，写入 SQLite
- 进度跟踪：全局 ScanState 对象，供 /api/scan/status 读取
- 异步安全：扫描在独立线程中运行，不阻塞 FastAPI 事件循环
"""

import fnmatch
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional

from backend.database import get_db
from backend.utils.file_types import SHAPEFILE_EXTENSIONS, get_file_type

# ─── 全局扫描状态 ───────────────────────────────────────────────────────────────

@dataclass
class ScanState:
    status: str = "idle"           # idle / running / completed / failed
    scan_id: Optional[int] = None
    root_path: str = ""
    scanned_count: int = 0         # 已处理的文件数
    current_dir: str = ""          # 当前正在扫描的目录
    added: int = 0                 # 新增文件数
    deleted: int = 0               # 删除文件数（增量扫描）
    modified: int = 0              # 修改文件数（增量扫描）
    started_at: Optional[str] = None
    error: Optional[str] = None


_state = ScanState()

# 只允许同时运行一个扫描任务
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="scanner")

_BATCH_SIZE = 1000  # 每批写入条数


def get_state() -> ScanState:
    return _state


def start_full_scan(
    root_path: str,
    disk_label: str,
    exclude_dirs: list[str],
    exclude_patterns: list[str],
) -> bool:
    """
    提交全量扫描任务到后台线程。
    返回 True 表示成功提交，False 表示已有扫描在运行。
    """
    global _state
    if _state.status == "running":
        return False

    _state = ScanState(
        status="running",
        root_path=root_path,
        started_at=datetime.now().isoformat(),
    )
    _executor.submit(_run_full_scan, root_path, disk_label, exclude_dirs, exclude_patterns)
    return True


def start_incremental_scan(
    root_path: str,
    disk_label: str,
    exclude_dirs: list[str],
    exclude_patterns: list[str],
) -> bool:
    """
    提交增量扫描任务到后台线程。
    返回 True 表示成功提交，False 表示已有扫描在运行。
    """
    global _state
    if _state.status == "running":
        return False

    _state = ScanState(
        status="running",
        root_path=root_path,
        started_at=datetime.now().isoformat(),
    )
    _executor.submit(_run_incremental_scan, root_path, disk_label, exclude_dirs, exclude_patterns)
    return True


# ─── 扫描主函数（在后台线程中执行）────────────────────────────────────────────

def _run_full_scan(
    root_path: str,
    disk_label: str,
    exclude_dirs: list[str],
    exclude_patterns: list[str],
) -> None:
    global _state
    conn = get_db()
    # WAL 模式 + 减少 fsync 次数，大幅提升批量写入速度
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-32768")   # 32 MB 缓存

    try:
        # 1. 创建扫描日志
        cur = conn.execute(
            "INSERT INTO scan_logs (scan_type, root_path, started_at, status) VALUES (?, ?, ?, ?)",
            ("full", root_path, _state.started_at, "running"),
        )
        conn.commit()
        scan_id: int = cur.lastrowid
        _state.scan_id = scan_id

        # 2. 清空旧数据（全量扫描覆盖）
        # FTS5 content 表：rebuild 会自动清理，无需手动删 FTS 行
        conn.execute("DELETE FROM file_snapshots")
        conn.execute("DELETE FROM files")
        conn.commit()

        # 3. 遍历文件系统，批量写入
        batch: list[dict] = []
        added = 0
        root_depth = len(Path(root_path).parts)

        for record in _walk(root_path, root_depth, exclude_dirs, exclude_patterns, disk_label):
            batch.append(record)
            _state.scanned_count += 1
            _state.current_dir = record["parent_dir"]

            if len(batch) >= _BATCH_SIZE:
                _insert_batch(conn, batch, scan_id)
                added += len(batch)
                _state.added = added
                batch.clear()

        if batch:
            _insert_batch(conn, batch, scan_id)
            added += len(batch)
            _state.added = added

        # 4. 重建 FTS5 全文索引
        conn.execute("INSERT INTO files_fts(files_fts) VALUES('rebuild')")
        conn.commit()

        # 5. 更新扫描日志为完成
        conn.execute(
            "UPDATE scan_logs SET finished_at=?, total_files=?, added=?, status=? WHERE id=?",
            (datetime.now().isoformat(), added, added, "completed", scan_id),
        )
        conn.commit()

        _state.status = "completed"
        _state.added = added

    except Exception as exc:
        _state.status = "failed"
        _state.error = str(exc)
        if _state.scan_id:
            try:
                conn.execute(
                    "UPDATE scan_logs SET finished_at=?, status=? WHERE id=?",
                    (datetime.now().isoformat(), "failed", _state.scan_id),
                )
                conn.commit()
            except Exception:
                pass
        raise
    finally:
        conn.close()


# ─── 增量扫描主函数（在后台线程中执行）────────────────────────────────────────

def _run_incremental_scan(
    root_path: str,
    disk_label: str,
    exclude_dirs: list[str],
    exclude_patterns: list[str],
) -> None:
    global _state
    conn = get_db()
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-32768")

    try:
        # 1. 创建扫描日志
        cur = conn.execute(
            "INSERT INTO scan_logs (scan_type, root_path, started_at, status) VALUES (?, ?, ?, ?)",
            ("incremental", root_path, _state.started_at, "running"),
        )
        conn.commit()
        scan_id: int = cur.lastrowid
        _state.scan_id = scan_id

        # 2. 加载旧快照：{file_path -> (modified_time, file_size)}
        rows = conn.execute(
            "SELECT file_path, modified_time, file_size FROM file_snapshots"
        ).fetchall()
        old_snapshots: dict[str, tuple] = {
            r["file_path"]: (r["modified_time"], r["file_size"]) for r in rows
        }

        # 3. 遍历文件系统，生成新记录列表
        new_records: list[dict] = []
        root_depth = len(Path(root_path).parts)
        for record in _walk(root_path, root_depth, exclude_dirs, exclude_patterns, disk_label):
            new_records.append(record)
            _state.scanned_count += 1
            _state.current_dir = record["parent_dir"]

        # 4. 构建新快照映射：{file_path -> record dict}
        new_snapshot: dict[str, dict] = {r["file_path"]: r for r in new_records}

        old_paths = set(old_snapshots.keys())
        new_paths = set(new_snapshot.keys())

        added_paths = new_paths - old_paths
        deleted_paths = old_paths - new_paths
        modified_paths = {
            p for p in old_paths & new_paths
            if (new_snapshot[p]["modified_time"], new_snapshot[p]["file_size"]) != old_snapshots[p]
        }

        # 5. 处理新增文件
        added = len(added_paths)
        if added_paths:
            add_batch = [new_snapshot[p] for p in added_paths]
            for i in range(0, len(add_batch), _BATCH_SIZE):
                chunk = add_batch[i : i + _BATCH_SIZE]
                conn.executemany(_INSERT_SQL, chunk)
                conn.executemany(
                    _SNAPSHOT_SQL,
                    [{"file_path": r["file_path"], "modified_time": r["modified_time"],
                      "file_size": r["file_size"], "scan_id": scan_id} for r in chunk],
                )
                conn.commit()
                _state.added = i + len(chunk)

        # 6. 处理删除文件
        deleted = len(deleted_paths)
        if deleted_paths:
            del_list = list(deleted_paths)
            for i in range(0, len(del_list), _BATCH_SIZE):
                chunk = del_list[i : i + _BATCH_SIZE]
                placeholders = ",".join("?" * len(chunk))
                conn.execute(f"DELETE FROM files WHERE file_path IN ({placeholders})", chunk)
                conn.execute(f"DELETE FROM file_snapshots WHERE file_path IN ({placeholders})", chunk)
                conn.commit()
            _state.deleted = deleted

        # 7. 处理修改文件（INSERT OR REPLACE 覆盖旧记录并更新快照）
        modified = len(modified_paths)
        if modified_paths:
            mod_batch = [new_snapshot[p] for p in modified_paths]
            for i in range(0, len(mod_batch), _BATCH_SIZE):
                chunk = mod_batch[i : i + _BATCH_SIZE]
                conn.executemany(_INSERT_SQL, chunk)
                conn.executemany(
                    _SNAPSHOT_SQL,
                    [{"file_path": r["file_path"], "modified_time": r["modified_time"],
                      "file_size": r["file_size"], "scan_id": scan_id} for r in chunk],
                )
                conn.commit()
            _state.modified = modified

        # 8. 仅当有变更时重建 FTS5 全文索引
        if added or deleted or modified:
            conn.execute("INSERT INTO files_fts(files_fts) VALUES('rebuild')")
            conn.commit()

        # 9. 更新扫描日志
        total = len(new_paths)
        conn.execute(
            "UPDATE scan_logs SET finished_at=?, total_files=?, added=?, deleted=?, modified=?, status=? WHERE id=?",
            (datetime.now().isoformat(), total, added, deleted, modified, "completed", scan_id),
        )
        conn.commit()

        _state.status = "completed"
        _state.added = added
        _state.deleted = deleted
        _state.modified = modified

    except Exception as exc:
        _state.status = "failed"
        _state.error = str(exc)
        if _state.scan_id:
            try:
                conn.execute(
                    "UPDATE scan_logs SET finished_at=?, status=? WHERE id=?",
                    (datetime.now().isoformat(), "failed", _state.scan_id),
                )
                conn.commit()
            except Exception:
                pass
        raise
    finally:
        conn.close()


# ─── 目录遍历（生成器）──────────────────────────────────────────────────────────

def _walk(
    root_path: str,
    root_depth: int,
    exclude_dirs: list[str],
    exclude_patterns: list[str],
    disk_label: str,
) -> Iterator[dict]:
    """
    用 os.scandir() 递归遍历目录树。
    - .gdb 目录视为单条 gis_vector 记录，不递归进入
    - PermissionError 静默跳过
    """
    exclude_dirs_set = set(exclude_dirs)

    def _scan_dir(dir_path: str) -> Iterator[dict]:
        _state.current_dir = dir_path
        try:
            entries = list(os.scandir(dir_path))
        except PermissionError:
            return

        for entry in entries:
            name = entry.name

            # 排除指定目录名
            if name in exclude_dirs_set:
                continue
            # 排除指定文件名模式（~$*、*.tmp 等）
            if _matches_patterns(name, exclude_patterns):
                continue

            try:
                is_dir = entry.is_dir(follow_symlinks=False)
            except OSError:
                continue

            if is_dir:
                if name.lower().endswith(".gdb"):
                    # FileGDB：记录为单条 gis_vector，不递归
                    yield _gdb_record(entry, root_depth, disk_label)
                else:
                    yield from _scan_dir(entry.path)
            else:
                if entry.is_file(follow_symlinks=False):
                    yield _file_record(entry, root_depth, disk_label)

    yield from _scan_dir(root_path)


def _matches_patterns(name: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(name, p) for p in patterns)


def _file_record(entry: os.DirEntry, root_depth: int, disk_label: str) -> dict:
    path = Path(entry.path)
    stem = path.stem
    ext = path.suffix.lower()
    depth = len(path.parts) - root_depth

    try:
        stat = entry.stat()
        size = stat.st_size
        ctime = datetime.fromtimestamp(stat.st_ctime).isoformat()
        mtime = datetime.fromtimestamp(stat.st_mtime).isoformat()
    except OSError:
        size, ctime, mtime = 0, None, None

    # Shapefile 分组：同目录同名文件共享 group 标识（绝对路径去扩展名）
    shapefile_group = str(path.parent / stem) if ext in SHAPEFILE_EXTENSIONS else None

    return {
        "file_name": path.name,
        "file_name_no_ext": stem,
        "extension": ext,
        "file_size": size,
        "created_time": ctime,
        "modified_time": mtime,
        "file_path": entry.path,
        "parent_dir": str(path.parent),
        "dir_depth": depth,
        "file_type": get_file_type(ext),
        "shapefile_group": shapefile_group,
        "disk_label": disk_label,
    }


def _gdb_record(entry: os.DirEntry, root_depth: int, disk_label: str) -> dict:
    """.gdb 目录作为一条 gis_vector 记录写入，不递归。"""
    path = Path(entry.path)
    depth = len(path.parts) - root_depth

    try:
        stat = entry.stat()
        ctime = datetime.fromtimestamp(stat.st_ctime).isoformat()
        mtime = datetime.fromtimestamp(stat.st_mtime).isoformat()
    except OSError:
        ctime, mtime = None, None

    return {
        "file_name": path.name,
        "file_name_no_ext": path.stem,
        "extension": ".gdb",
        "file_size": 0,
        "created_time": ctime,
        "modified_time": mtime,
        "file_path": entry.path,
        "parent_dir": str(path.parent),
        "dir_depth": depth,
        "file_type": "gis_vector",
        "shapefile_group": None,
        "disk_label": disk_label,
    }


# ─── 批量写入 ──────────────────────────────────────────────────────────────────

_INSERT_SQL = """
INSERT OR REPLACE INTO files
    (file_name, file_name_no_ext, extension, file_size, created_time,
     modified_time, file_path, parent_dir, dir_depth, file_type,
     shapefile_group, disk_label)
VALUES
    (:file_name, :file_name_no_ext, :extension, :file_size, :created_time,
     :modified_time, :file_path, :parent_dir, :dir_depth, :file_type,
     :shapefile_group, :disk_label)
"""

_SNAPSHOT_SQL = """
INSERT OR REPLACE INTO file_snapshots (file_path, modified_time, file_size, scan_id)
VALUES (:file_path, :modified_time, :file_size, :scan_id)
"""


def _insert_batch(conn, batch: list[dict], scan_id: int) -> None:
    conn.executemany(_INSERT_SQL, batch)
    conn.executemany(
        _SNAPSHOT_SQL,
        [
            {
                "file_path": r["file_path"],
                "modified_time": r["modified_time"],
                "file_size": r["file_size"],
                "scan_id": scan_id,
            }
            for r in batch
        ],
    )
    conn.commit()
