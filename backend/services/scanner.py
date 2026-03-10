"""
文件扫描服务

职责：
- 全量扫描：递归遍历目录，提取文件元数据，写入 SQLite
- 进度跟踪：全局 ScanState 对象，供 /api/scan/status 读取
- 异步安全：扫描在独立线程中运行，不阻塞 FastAPI 事件循环
"""

import fnmatch
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional

from backend.database import get_db
from backend.utils.file_types import SHAPEFILE_EXTENSIONS, get_file_type

logger = logging.getLogger(__name__)

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
    scan_method: str = "scandir"   # "mft"（MFT直读）或 "scandir"（os.scandir回退）


_state = ScanState()

# 只允许同时运行一个扫描任务
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="scanner")

_BATCH_SIZE = 20000  # 每批写入条数


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
    t_scan_start = time.monotonic()
    logger.info("=" * 50)
    logger.info("[SCAN] === 开始全量扫描 root=%s ===", root_path)

    conn = get_db()
    # WAL 模式 + 减少 fsync 次数，大幅提升批量写入速度
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-32768")   # 32 MB 缓存

    # ── 预判断 MFT 可用性（在 DB 操作之前，避免回滚复杂度）──────────────────
    _mft_mod = None
    _drive_letter: str = ""
    try:
        from backend.services import mft_scanner as _m
        admin_status = _m.is_admin()
        logger.info("[SCAN] 权限检测: is_admin=%s", admin_status)
        if admin_status:
            drive = Path(root_path).drive          # "C:"
            dl = drive.rstrip(":").strip().upper() # "C"
            if dl and len(dl) == 1 and dl.isalpha():
                _mft_mod = _m
                _drive_letter = dl
                logger.info("[SCAN] 扫描策略选择: MFT直读 (drive=%s:)", dl)
            else:
                logger.warning("[SCAN] 盘符无效 %r，将回退到os.scandir", drive)
        else:
            logger.info("[SCAN] 扫描策略选择: os.scandir (非管理员权限，MFT不可用)")
    except ImportError:
        logger.warning("[SCAN] mft_scanner模块导入失败，使用os.scandir")

    _state.scan_method = "mft" if _mft_mod else "scandir"
    logger.info("[SCAN] 确认扫描方法: %s", _state.scan_method)

    try:
        # 1. 创建扫描日志
        cur = conn.execute(
            "INSERT INTO scan_logs (scan_type, root_path, started_at, status) VALUES (?, ?, ?, ?)",
            ("full", root_path, _state.started_at, "running"),
        )
        conn.commit()
        scan_id: int = cur.lastrowid
        _state.scan_id = scan_id

        # 2. 全量扫描前删除索引（DELETE + 后续 INSERT 都快很多），再清空数据
        _drop_full_scan_indexes(conn)
        conn.execute("DELETE FROM file_snapshots")
        conn.execute("DELETE FROM files")
        conn.execute("INSERT INTO files_fts(files_fts) VALUES('rebuild')")
        conn.commit()

        # 3a. 尝试 MFT 快速通道
        if _mft_mod:
            try:
                _run_full_scan_mft(
                    conn, _mft_mod, _drive_letter,
                    root_path, disk_label, exclude_dirs, exclude_patterns, scan_id,
                )
                return
            except (PermissionError, OSError, RuntimeError, ValueError) as _mft_err:
                logger.warning(
                    "[SCAN] MFT扫描失败，回退到scandir模式: %s", _mft_err, exc_info=True
                )
                # fallback：重新清空（MFT 可能已写入部分数据），索引已删无需再删
                conn.execute("DELETE FROM file_snapshots")
                conn.execute("DELETE FROM files")
                conn.execute("INSERT INTO files_fts(files_fts) VALUES('rebuild')")
                conn.commit()
                # 注意：此时索引已在步骤2中删除，scandir 路径末尾会重建
                _state.scan_method = "scandir"
                _state.added = 0
                _state.scanned_count = 0
                logger.info("[SCAN] 已切换到scandir模式，继续扫描...")

        # 3b. os.scandir 通用通道
        batch: list[dict] = []
        added = 0
        root_depth = len(Path(root_path).parts)

        for record in _walk(root_path, root_depth, exclude_dirs, exclude_patterns, disk_label):
            batch.append(record)
            _state.scanned_count += 1
            _state.current_dir = record["parent_dir"]

            if len(batch) >= _BATCH_SIZE:
                _insert_batch(conn, batch, scan_id, sync_fts=False, skip_snapshots=True)
                added += len(batch)
                _state.added = added
                batch.clear()

        if batch:
            _insert_batch(conn, batch, scan_id, sync_fts=False, skip_snapshots=True)
            added += len(batch)
            _state.added = added

        # 全量写入完成：重建索引 + 批量快照 + FTS rebuild
        t_post = time.monotonic()
        _rebuild_full_scan_indexes(conn)
        conn.execute(
            "INSERT INTO file_snapshots (file_path, modified_time, file_size, scan_id) "
            "SELECT file_path, modified_time, file_size, ? FROM files",
            (scan_id,),
        )
        conn.commit()
        conn.execute("INSERT INTO files_fts(files_fts) VALUES('rebuild')")
        conn.commit()
        logger.info("[SCAN] 后处理(索引+快照+FTS)完成: 耗时=%.2fs", time.monotonic() - t_post)

        # 4. 更新扫描日志为完成
        conn.execute(
            "UPDATE scan_logs SET finished_at=?, total_files=?, added=?, status=? WHERE id=?",
            (datetime.now().isoformat(), added, added, "completed", scan_id),
        )
        conn.commit()

        _state.status = "completed"
        _state.added = added
        elapsed = time.monotonic() - t_scan_start
        speed   = added / elapsed if elapsed > 0 else 0
        logger.info(
            "[SCAN] scandir扫描完成: 总计=%d条, 耗时=%.2fs, 速度=%.0f条/s",
            added, elapsed, speed,
        )
        logger.info("[SCAN] === 全量扫描完成(scandir) 总耗时=%.2fs ===", elapsed)
        logger.info("=" * 50)
        _try_auto_start_usn(root_path)

    except Exception as exc:
        _state.status = "failed"
        _state.error = str(exc)
        logger.error("[SCAN] 全量扫描异常: %s", exc, exc_info=True)
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


def _try_auto_start_usn(root_path: str) -> None:
    """全量扫描完成后自动启动 USN Journal 监控（仅管理员模式下生效）。"""
    logger.info("[SCAN] 尝试自动启动USN Journal监控...")
    try:
        from backend.services import mft_scanner as _m
        admin = _m.is_admin()
        logger.info("[SCAN] USN启动前权限检查: is_admin=%s", admin)
        if not admin:
            logger.info("[SCAN] 非管理员权限，跳过USN监控自动启动")
            return
        from backend.services import usn_monitor
        result = usn_monitor.start_monitoring([root_path])
        logger.info(
            "[SCAN] USN监控自动启动结果: started=%s, already_running=%s",
            result["started"], result["already_running"],
        )
    except Exception as exc:
        logger.warning("[SCAN] USN监控自动启动失败（非致命）: %s", exc, exc_info=True)


def _run_full_scan_mft(
    conn,
    mft_mod,
    drive_letter: str,
    root_path: str,
    disk_label: str,
    exclude_dirs: list[str],
    exclude_patterns: list[str],
    scan_id: int,
) -> None:
    """
    MFT 快速通道：调用 mft_scanner.scan_volume()，
    在 batch_callback 中过滤路径、应用排除规则，
    然后复用现有 _insert_batch() 写入 DB。
    """
    global _state

    root_norm      = os.path.normcase(root_path.rstrip("\\/"))
    root_prefix    = root_norm + os.sep          # 用于前缀匹配
    root_depth     = len(Path(root_path).parts)
    exclude_set    = set(exclude_dirs)
    added          = 0
    batch_no       = 0

    # 扫描前 DB 状态
    try:
        pre_count = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        logger.info("[SCAN] [DB] MFT扫描前: 文件数=%d", pre_count)
    except Exception:
        pass

    # 让前端在 MFT 读取阶段（约 4s）也能看到有效状态，而非 scanned=0
    _state.current_dir = "正在读取 MFT 元数据..."

    def _callback(records: list[dict]) -> None:
        nonlocal added, batch_no
        filtered: list[dict] = []

        for r in records:
            fp_norm = os.path.normcase(r["file_path"])
            # 仅保留 root_path 下的文件
            if fp_norm != root_norm and not fp_norm.startswith(root_prefix):
                continue
            # 排除目录名匹配（检查路径各组成部分）
            parts = Path(r["file_path"]).parts
            if any(p in exclude_set for p in parts[:-1]):
                continue
            # 排除文件名通配符模式
            if _matches_patterns(r["file_name"], exclude_patterns):
                continue
            # 修正 dir_depth：相对 root_path（而非卷根）
            r["dir_depth"] = len(parts) - root_depth
            filtered.append(r)

        if filtered:
            # skip_snapshots=True：不逐批写快照，末尾一条 SQL 批量生成，快 30%
            _insert_batch(conn, filtered, scan_id, sync_fts=False, skip_snapshots=True)
            added += len(filtered)
            batch_no += 1
            _state.added = added
            _state.scanned_count += len(filtered)
            _state.current_dir = filtered[-1]["parent_dir"]
            logger.debug(
                "[SCAN] DB批次 #%d 写入: %d条, 累计: %d条",
                batch_no, len(filtered), added,
            )

    mft_mod.scan_volume(drive_letter, _callback, _BATCH_SIZE, disk_label)

    # ── 后处理：重建索引 + 批量快照 + FTS rebuild ──────────────────────────────
    t_post = time.monotonic()

    # 1) 重建 5 个索引（对已有数据做排序+B树构建，比逐行维护快很多）
    _rebuild_full_scan_indexes(conn)
    logger.info("[SCAN] 索引重建完成: 耗时=%.2fs", time.monotonic() - t_post)

    # 2) 一条 SQL 从 files 表批量生成 file_snapshots（替代逐批 executemany）
    t_snap = time.monotonic()
    conn.execute(
        "INSERT INTO file_snapshots (file_path, modified_time, file_size, scan_id) "
        "SELECT file_path, modified_time, file_size, ? FROM files",
        (scan_id,),
    )
    conn.commit()
    logger.info("[SCAN] 快照批量写入完成: 耗时=%.2fs", time.monotonic() - t_snap)

    # 3) FTS5 rebuild
    t_fts = time.monotonic()
    conn.execute("INSERT INTO files_fts(files_fts) VALUES('rebuild')")
    conn.commit()
    logger.info("[SCAN] FTS5索引重建完成: 耗时=%.2fs", time.monotonic() - t_fts)

    logger.info("[SCAN] 后处理总耗时: %.2fs", time.monotonic() - t_post)

    # 扫描后 DB 诊断（关键：检查大小为0的文件比例）
    try:
        post_count = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        zero_size  = conn.execute(
            "SELECT COUNT(*) FROM files WHERE file_size = 0 OR file_size IS NULL"
        ).fetchone()[0]
        logger.info(
            "[SCAN] [DB] MFT扫描后: 文件数=%d, 大小为0的文件=%d (%.1f%%)%s",
            post_count, zero_size,
            zero_size / post_count * 100 if post_count > 0 else 0.0,
            " *** 异常:大量文件size=0，可能是GetFileAttributesExW失败 ***"
            if post_count > 0 and zero_size > post_count * 0.5 else " (正常)",
        )
    except Exception as exc:
        logger.warning("[SCAN] 扫描后DB诊断查询失败: %s", exc)

    conn.execute(
        "UPDATE scan_logs SET finished_at=?, total_files=?, added=?, status=? WHERE id=?",
        (datetime.now().isoformat(), added, added, "completed", scan_id),
    )
    conn.commit()
    _state.status = "completed"
    _state.added = added
    logger.info("[SCAN] === 全量扫描完成(MFT) 总写入=%d条 ===", added)
    logger.info("=" * 50)
    _try_auto_start_usn(root_path)


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
        # 1. 无快照时自动回退全量扫描（关闭当前连接，不留悬空事务）
        if not conn.execute("SELECT 1 FROM file_snapshots LIMIT 1").fetchone():
            conn.close()
            conn = None
            _run_full_scan(root_path, disk_label, exclude_dirs, exclude_patterns)
            return

        # 2. 创建扫描日志
        cur = conn.execute(
            "INSERT INTO scan_logs (scan_type, root_path, started_at, status) VALUES (?, ?, ?, ?)",
            ("incremental", root_path, _state.started_at, "running"),
        )
        conn.commit()
        scan_id: int = cur.lastrowid
        _state.scan_id = scan_id

        # 3. 创建临时表（TEMP TABLE 随连接结束自动销毁，写入磁盘临时库，不占 Python 堆内存）
        conn.execute("DROP TABLE IF EXISTS temp_scan_snapshot")
        conn.execute("""
            CREATE TEMP TABLE temp_scan_snapshot (
                path             TEXT PRIMARY KEY,
                mtime            TEXT,
                size             INTEGER,
                file_name        TEXT,
                file_name_no_ext TEXT,
                extension        TEXT,
                created_time     TEXT,
                parent_dir       TEXT,
                dir_depth        INTEGER,
                file_type        TEXT,
                shapefile_group  TEXT,
                disk_label       TEXT
            )
        """)

        # 4. 遍历文件系统，批量写入临时表（内存中最多保留 _BATCH_SIZE 条）
        batch: list[dict] = []
        root_depth = len(Path(root_path).parts)

        for record in _walk(root_path, root_depth, exclude_dirs, exclude_patterns, disk_label):
            batch.append(record)
            _state.scanned_count += 1
            _state.current_dir = record["parent_dir"]

            if len(batch) >= _BATCH_SIZE:
                conn.executemany(_TEMP_INSERT_SQL, batch)
                conn.commit()
                batch.clear()

        if batch:
            conn.executemany(_TEMP_INSERT_SQL, batch)
            conn.commit()
            batch.clear()

        # 5. SQL 侧三路对比（全程不把快照拉入 Python 内存）
        added = conn.execute("""
            SELECT COUNT(*) FROM temp_scan_snapshot
            WHERE path NOT IN (SELECT file_path FROM file_snapshots)
        """).fetchone()[0]

        deleted = conn.execute("""
            SELECT COUNT(*) FROM file_snapshots
            WHERE file_path NOT IN (SELECT path FROM temp_scan_snapshot)
        """).fetchone()[0]

        modified = conn.execute("""
            SELECT COUNT(*) FROM temp_scan_snapshot t
            JOIN file_snapshots s ON t.path = s.file_path
            WHERE t.mtime != s.modified_time OR t.size != s.file_size
        """).fetchone()[0]

        # 6. 处理新增文件：INSERT files → 同步插入 FTS
        if added:
            conn.execute("""
                INSERT OR IGNORE INTO files
                    (file_name, file_name_no_ext, extension, file_size, created_time,
                     modified_time, file_path, parent_dir, dir_depth, file_type,
                     shapefile_group, disk_label)
                SELECT file_name, file_name_no_ext, extension, size, created_time,
                       mtime, path, parent_dir, dir_depth, file_type,
                       shapefile_group, disk_label
                FROM temp_scan_snapshot
                WHERE path NOT IN (SELECT file_path FROM file_snapshots)
            """)
            conn.commit()
            # 新增文件写入 files 后，同步插入 FTS 索引
            conn.execute("""
                INSERT INTO files_fts(rowid, file_name, file_path, file_type)
                SELECT id, file_name, file_path, file_type FROM files
                WHERE file_path IN (
                    SELECT path FROM temp_scan_snapshot
                    WHERE path NOT IN (SELECT file_path FROM file_snapshots)
                )
            """)
            conn.commit()
            _state.added = added

        # 7. 处理删除文件：先删 FTS 条目（content FTS 需在 files 记录存在时读取文本），再删 files
        if deleted:
            conn.execute("""
                DELETE FROM files_fts WHERE rowid IN (
                    SELECT id FROM files
                    WHERE file_path IN (
                        SELECT file_path FROM file_snapshots
                        WHERE file_path NOT IN (SELECT path FROM temp_scan_snapshot)
                    )
                )
            """)
            conn.execute("""
                DELETE FROM files
                WHERE file_path IN (
                    SELECT file_path FROM file_snapshots
                    WHERE file_path NOT IN (SELECT path FROM temp_scan_snapshot)
                )
            """)
            conn.commit()
            _state.deleted = deleted

        # 8. 处理修改文件：先删旧 FTS 条目 → INSERT OR REPLACE → 插入新 FTS 条目
        # INSERT OR REPLACE 会分配新 rowid，因此需要在替换后重新插入 FTS
        if modified:
            conn.execute("""
                DELETE FROM files_fts WHERE rowid IN (
                    SELECT f.id FROM files f
                    JOIN file_snapshots s ON f.file_path = s.file_path
                    JOIN temp_scan_snapshot t ON s.file_path = t.path
                    WHERE t.mtime != s.modified_time OR t.size != s.file_size
                )
            """)
            conn.execute("""
                INSERT OR REPLACE INTO files
                    (file_name, file_name_no_ext, extension, file_size, created_time,
                     modified_time, file_path, parent_dir, dir_depth, file_type,
                     shapefile_group, disk_label)
                SELECT t.file_name, t.file_name_no_ext, t.extension, t.size, t.created_time,
                       t.mtime, t.path, t.parent_dir, t.dir_depth, t.file_type,
                       t.shapefile_group, t.disk_label
                FROM temp_scan_snapshot t
                JOIN file_snapshots s ON t.path = s.file_path
                WHERE t.mtime != s.modified_time OR t.size != s.file_size
            """)
            conn.commit()
            # 用新 rowid 插入 FTS（INSERT OR REPLACE 后文件已有新 id）
            conn.execute("""
                INSERT INTO files_fts(rowid, file_name, file_path, file_type)
                SELECT id, file_name, file_path, file_type FROM files
                WHERE file_path IN (
                    SELECT t.path FROM temp_scan_snapshot t
                    JOIN file_snapshots s ON t.path = s.file_path
                    WHERE t.mtime != s.modified_time OR t.size != s.file_size
                )
            """)
            conn.commit()
            _state.modified = modified

        # 9. 替换 file_snapshots：DELETE ALL + INSERT FROM temp（全 SQL，单事务）
        conn.execute("DELETE FROM file_snapshots")
        conn.execute("""
            INSERT INTO file_snapshots (file_path, modified_time, file_size, scan_id)
            SELECT path, mtime, size, ?
            FROM temp_scan_snapshot
        """, (scan_id,))
        conn.commit()

        # 10. 更新扫描日志（FTS 已在各变更操作中同步，无需 rebuild）
        conn.execute(
            "UPDATE scan_logs SET finished_at=?, total_files=?, added=?, deleted=?, modified=?, status=? WHERE id=?",
            (datetime.now().isoformat(), _state.scanned_count, added, deleted, modified, "completed", scan_id),
        )
        conn.commit()

        _state.status = "completed"
        _state.added = added
        _state.deleted = deleted
        _state.modified = modified

    except Exception as exc:
        _state.status = "failed"
        _state.error = str(exc)
        if _state.scan_id and conn is not None:
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
        if conn is not None:
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

# 增量扫描：将文件系统快照写入临时表（复用 _walk 返回的 record 字段名）
_TEMP_INSERT_SQL = """
INSERT OR REPLACE INTO temp_scan_snapshot
    (path, mtime, size, file_name, file_name_no_ext, extension,
     created_time, parent_dir, dir_depth, file_type, shapefile_group, disk_label)
VALUES
    (:file_path, :modified_time, :file_size, :file_name, :file_name_no_ext, :extension,
     :created_time, :parent_dir, :dir_depth, :file_type, :shapefile_group, :disk_label)
"""


_FTS_CHUNK = 500  # 每次 FTS 批量插入的路径数（避免超出 SQLite 参数数量上限 999）


def _fts_insert_by_paths(conn, paths: list[str]) -> None:
    """按文件路径批量同步 FTS 索引，分块执行以避免 SQLite 参数上限。"""
    for i in range(0, len(paths), _FTS_CHUNK):
        sub = paths[i : i + _FTS_CHUNK]
        ph = ",".join("?" * len(sub))
        conn.execute(
            "INSERT INTO files_fts(rowid, file_name, file_path, file_type) "
            f"SELECT id, file_name, file_path, file_type FROM files WHERE file_path IN ({ph})",
            sub,
        )


def _insert_batch(
    conn, batch: list[dict], scan_id: int,
    sync_fts: bool = False, skip_snapshots: bool = False,
) -> None:
    conn.executemany(_INSERT_SQL, batch)
    if not skip_snapshots:
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
    if sync_fts:
        # 在同一事务内（executemany 未 commit），新插入行对本连接可见，可直接查询
        _fts_insert_by_paths(conn, [r["file_path"] for r in batch])
    conn.commit()


# 全量扫描：先删除这 5 个索引，写完后重建，INSERT 性能提升 5-6 倍
_FULL_SCAN_INDEXES = [
    ("idx_files_extension",  "ON files(extension)"),
    ("idx_files_file_type",  "ON files(file_type)"),
    ("idx_files_modified",   "ON files(modified_time)"),
    ("idx_files_parent_dir", "ON files(parent_dir)"),
    ("idx_files_shp_group",  "ON files(shapefile_group)"),
]


def _drop_full_scan_indexes(conn) -> None:
    for name, _ in _FULL_SCAN_INDEXES:
        conn.execute(f"DROP INDEX IF EXISTS {name}")
    conn.commit()


def _rebuild_full_scan_indexes(conn) -> None:
    for name, definition in _FULL_SCAN_INDEXES:
        conn.execute(f"CREATE INDEX IF NOT EXISTS {name} {definition}")
    conn.commit()
