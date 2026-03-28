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
    current_phase: str = ""        # 当前阶段描述（供前端显示）
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
    # WAL 模式 + 扫描期间关闭 fsync（扫描丢失最多重新扫描，代价极低）
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("PRAGMA cache_size=-32768")   # 32 MB 缓存

    # ── 预判断 MFT 可用性（在 DB 操作之前，避免回滚复杂度）──────────────────
    _mft_mod = None
    _drive_letter: str = ""
    try:
        from backend.services import mft_scanner as _m
        admin_status = _m.is_admin()
        logger.info("[SCAN] 权限检测: is_admin=%s", admin_status)
        if admin_status:
            drive = root_path[:2] if len(root_path) >= 2 and root_path[1] == ':' else ""  # "C:"
            dl = drive[0].upper() if drive else ""  # "C"
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
        # 注意：files 清空后无需 FTS rebuild，末尾写完数据后统一 rebuild 一次
        _drop_full_scan_indexes(conn)
        conn.execute("DELETE FROM file_snapshots")
        conn.execute("DELETE FROM files")
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
                conn.commit()
                # 注意：此时索引已在步骤2中删除，scandir 路径末尾会重建
                _state.scan_method = "scandir"
                _state.added = 0
                _state.scanned_count = 0
                logger.info("[SCAN] 已切换到scandir模式，继续扫描...")

        # 3b. os.scandir 通用通道
        batch: list[dict] = []
        added = 0
        root_depth = root_path.replace('/', os.sep).rstrip(os.sep).count(os.sep) + 1
        _state.current_phase = "遍历文件系统"

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

        # 全量写入完成：两波并行后处理（与 MFT 路径相同策略）
        t_post = time.monotonic()

        # 第一波：索引重建 + 快照写入 并行（各用独立连接，互不阻塞）
        _state.current_phase = "重建数据库索引 & 生成文件快照"

        def _sd_task_rebuild_indexes() -> float:
            t = time.monotonic()
            c = get_db()
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=OFF")
            try:
                _rebuild_full_scan_indexes(c)
            finally:
                c.close()
            return time.monotonic() - t

        def _sd_task_write_snapshots() -> float:
            t = time.monotonic()
            c = get_db()
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=OFF")
            try:
                # DROP→无索引INSERT→末尾建唯一索引（bulk-load，避免逐行维护 PRIMARY KEY B-tree）
                c.executescript("""
                    DROP TABLE IF EXISTS file_snapshots;
                    CREATE TABLE file_snapshots (
                        file_path     TEXT NOT NULL,
                        modified_time TEXT,
                        file_size     INTEGER,
                        scan_id       INTEGER
                    );
                """)
                c.execute(
                    "INSERT INTO file_snapshots (file_path, modified_time, file_size, scan_id) "
                    "SELECT file_path, modified_time, file_size, ? FROM files",
                    (scan_id,),
                )
                c.commit()
                c.execute(
                    "CREATE UNIQUE INDEX idx_file_snapshots_path ON file_snapshots(file_path)"
                )
                c.commit()
            finally:
                c.close()
            return time.monotonic() - t

        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="sd_post1") as pool:
            f_idx  = pool.submit(_sd_task_rebuild_indexes)
            f_snap = pool.submit(_sd_task_write_snapshots)
            t_idx  = f_idx.result()
            t_snap = f_snap.result()
        logger.info("[SCAN] 索引重建完成: 耗时=%.2fs", t_idx)
        logger.info("[SCAN] 快照批量写入完成: 耗时=%.2fs", t_snap)

        # 第二波：FTS rebuild + 目录快照 并行（写不同表，WAL 下互不阻塞）
        _state.current_phase = "重建全文搜索索引 & 更新目录快照"

        def _sd_task_rebuild_fts() -> float:
            t = time.monotonic()
            c = get_db()
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=OFF")
            try:
                c.execute("INSERT INTO files_fts(files_fts) VALUES('rebuild')")
                c.commit()
            finally:
                c.close()
            return time.monotonic() - t

        def _sd_task_rebuild_dir_snapshots() -> float:
            t = time.monotonic()
            c = get_db()
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=OFF")
            try:
                _rebuild_dir_snapshots_fast(c, scan_id)
            finally:
                c.close()
            return time.monotonic() - t

        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="sd_post2") as pool:
            f_fts = pool.submit(_sd_task_rebuild_fts)
            f_dir = pool.submit(_sd_task_rebuild_dir_snapshots)
            t_fts = f_fts.result()
            f_dir.result()
        logger.info("[SCAN] FTS5索引重建完成: 耗时=%.2fs", t_fts)

        logger.info("[SCAN] 后处理(索引+快照+FTS+目录快照)完成: 耗时=%.2fs", time.monotonic() - t_post)

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

    root_norm      = root_path.rstrip("\\/").lower()
    root_prefix    = root_norm + os.sep          # 用于前缀匹配
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
    _state.current_phase = "读取 MFT 元数据"

    _sep = os.sep
    _first_batch = True

    def _callback(records: list[dict]) -> None:
        nonlocal added, batch_no, _first_batch
        # MFT 读取完成、目录路径展开完成后第一批数据才会到达
        if _first_batch:
            _first_batch = False
            _state.current_phase = "写入文件记录"
            _state.current_dir = ""
        filtered: list[dict] = []

        for r in records:
            fp = r["file_path"]
            fp_norm = fp.lower()
            # 仅保留 root_path 下的文件
            if fp_norm != root_norm and not fp_norm.startswith(root_prefix):
                continue
            # 排除目录名匹配（检查路径中间各部分，用字符串分割替代 Path.parts）
            parent = r["parent_dir"]
            if any(part in exclude_set for part in parent.split(_sep)):
                continue
            # 排除文件名通配符模式
            if _matches_patterns(r["file_name"], exclude_patterns):
                continue
            # dir_depth 已在 mft_scanner 内按 drive_root 计算，无需修正
            filtered.append(r)

        if filtered:
            # skip_snapshots=True：不逐批写快照，末尾一条 SQL 批量生成，快 30%
            _insert_batch(conn, filtered, scan_id, sync_fts=False, skip_snapshots=True)
            added += len(filtered)
            batch_no += 1
            _state.added = added
            _state.scanned_count += len(filtered)
            _state.current_dir = filtered[-1]["parent_dir"]
            _state.current_phase = "写入文件记录"
            logger.debug(
                "[SCAN] DB批次 #%d 写入: %d条, 累计: %d条",
                batch_no, len(filtered), added,
            )

    def _phase_cb(phase: str, current_dir: str) -> None:
        _state.current_phase = phase
        _state.current_dir = current_dir

    _, _, dir_mtimes = mft_mod.scan_volume(drive_letter, _callback, _BATCH_SIZE, disk_label, phase_callback=_phase_cb)

    # ── 后处理：两波并行执行 ───────────────────────────────────────────────────
    # 第一波并行：索引重建 + 快照写入（互不依赖，各用独立连接）
    # 第二波并行：FTS rebuild + 目录快照（需等第一波完成，因 FTS rebuild 需扫全表）
    t_post = time.monotonic()
    _state.current_phase = "重建数据库索引 & 生成文件快照"

    def _task_rebuild_indexes() -> float:
        t = time.monotonic()
        c = get_db()
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=OFF")
        try:
            _rebuild_full_scan_indexes(c)
        finally:
            c.close()
        return time.monotonic() - t

    def _task_write_snapshots() -> float:
        t = time.monotonic()
        c = get_db()
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=OFF")
        try:
            # DROP→无索引INSERT→末尾建唯一索引（bulk-load）
            c.executescript("""
                DROP TABLE IF EXISTS file_snapshots;
                CREATE TABLE file_snapshots (
                    file_path     TEXT NOT NULL,
                    modified_time TEXT,
                    file_size     INTEGER,
                    scan_id       INTEGER
                );
            """)
            c.execute(
                "INSERT INTO file_snapshots (file_path, modified_time, file_size, scan_id) "
                "SELECT file_path, modified_time, file_size, ? FROM files",
                (scan_id,),
            )
            c.commit()
            c.execute(
                "CREATE UNIQUE INDEX idx_file_snapshots_path ON file_snapshots(file_path)"
            )
            c.commit()
        finally:
            c.close()
        return time.monotonic() - t

    def _task_rebuild_fts() -> float:
        t = time.monotonic()
        c = get_db()
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=OFF")
        try:
            c.execute("INSERT INTO files_fts(files_fts) VALUES('rebuild')")
            c.commit()
        finally:
            c.close()
        return time.monotonic() - t

    def _task_rebuild_dir_snapshots() -> float:
        t = time.monotonic()
        c = get_db()
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=OFF")
        try:
            # dir_mtimes 由 mft_scanner.scan_volume 返回，直接用（无需 os.stat）
            c.executescript("""
                DROP TABLE IF EXISTS dir_snapshots;
                CREATE TABLE dir_snapshots (
                    dir_path  TEXT NOT NULL,
                    dir_mtime TEXT,
                    scan_id   INTEGER
                );
            """)
            batch: list[tuple] = []
            for dir_path, mtime in dir_mtimes.items():
                batch.append((dir_path, mtime, scan_id))
                if len(batch) >= 5000:
                    c.executemany(
                        "INSERT INTO dir_snapshots (dir_path, dir_mtime, scan_id) VALUES (?, ?, ?)",
                        batch,
                    )
                    batch.clear()
            if batch:
                c.executemany(
                    "INSERT INTO dir_snapshots (dir_path, dir_mtime, scan_id) VALUES (?, ?, ?)",
                    batch,
                )
            c.commit()
            c.execute("CREATE UNIQUE INDEX idx_dir_snapshots_path ON dir_snapshots(dir_path)")
            c.commit()
        finally:
            c.close()
        elapsed_t = time.monotonic() - t
        logger.info("[SCAN] 目录快照重建完成: %d 个目录, 耗时=%.2fs", len(dir_mtimes), elapsed_t)
        return elapsed_t

    # 第一波：索引重建 + 快照写入 并行（各用独立连接）
    _state.current_phase = "重建数据库索引 & 生成文件快照"
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="post1") as pool:
        f_idx  = pool.submit(_task_rebuild_indexes)
        f_snap = pool.submit(_task_write_snapshots)
        t_idx  = f_idx.result()
        t_snap = f_snap.result()
    logger.info("[SCAN] 索引重建完成: 耗时=%.2fs", t_idx)
    logger.info("[SCAN] 快照批量写入完成: 耗时=%.2fs", t_snap)

    # 第二波：FTS rebuild + 目录快照 并行（FTS读files写files_fts，目录快照写dir_snapshots，WAL下互不阻塞）
    _state.current_phase = "重建全文搜索索引 & 更新目录快照"
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="post2") as pool:
        f_fts = pool.submit(_task_rebuild_fts)
        f_dir = pool.submit(_task_rebuild_dir_snapshots)
        t_fts = f_fts.result()
        f_dir.result()
    logger.info("[SCAN] FTS5索引重建完成: 耗时=%.2fs", t_fts)

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


# ─── 增量扫描主函数（在后台线程中执行）────────────────────────────────────────

def _run_incremental_scan(
    root_path: str,
    disk_label: str,
    exclude_dirs: list[str],
    exclude_patterns: list[str],
) -> None:
    global _state
    t_scan_start = time.monotonic()
    logger.info("[SCAN] === 开始增量扫描 root=%s ===", root_path)

    conn = get_db()
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-32768")

    try:
        # 1. 无快照时自动回退全量扫描（关闭当前连接，不留悬空事务）
        if not conn.execute("SELECT 1 FROM file_snapshots LIMIT 1").fetchone():
            conn.close()
            conn = None
            logger.info("[SCAN] 无历史快照，自动回退全量扫描")
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

        # 3. 加载目录快照（用于 mtime 剪枝）
        # 若无目录快照（旧数据库），退化为完整遍历（dir_snapshots_dict 为空）
        t_load = time.monotonic()
        dir_snapshots_dict: dict[str, str] = {}
        rows = conn.execute("SELECT dir_path, dir_mtime FROM dir_snapshots").fetchall()
        for row in rows:
            dir_snapshots_dict[row[0]] = row[1]
        has_dir_snapshots = len(dir_snapshots_dict) > 0
        logger.info(
            "[SCAN] 目录快照加载: %d 条, 耗时=%.3fs, 剪枝=%s",
            len(dir_snapshots_dict), time.monotonic() - t_load,
            "启用" if has_dir_snapshots else "禁用(无目录快照，将完整遍历)",
        )

        # 4. 创建临时表（TEMP TABLE 随连接结束自动销毁）
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

        # 5. 用 mtime 剪枝遍历，只遍历有变化的目录
        #    changed_dirs: 本次实际遍历（扫描）的目录集合，用于更新目录快照
        batch: list[dict] = []
        root_depth = root_path.replace('/', os.sep).rstrip(os.sep).count(os.sep) + 1
        changed_dirs: set[str] = set()   # 本次被实际扫描的目录（mtime 变化或新目录）
        skipped_dirs: int = 0            # 被剪枝跳过的目录数

        _state.current_phase = "遍历文件系统（目录剪枝）"
        t_walk = time.monotonic()
        for record in _walk_incremental(
            root_path, root_depth, exclude_dirs, exclude_patterns,
            disk_label, dir_snapshots_dict, changed_dirs,
        ):
            if record is _SKIP_SENTINEL:
                skipped_dirs += 1
                continue
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

        logger.info(
            "[SCAN] 文件遍历完成: 扫描=%d条, 跳过目录=%d, 耗时=%.2fs",
            _state.scanned_count, skipped_dirs, time.monotonic() - t_walk,
        )

        # 6. 未变化目录的文件直接从旧快照复制到临时表（SQL 操作，极快）
        #    这样临时表包含完整文件列表，后续三路 SQL 对比逻辑不变
        if has_dir_snapshots and skipped_dirs > 0:
            _state.current_phase = "合并未变化目录文件"
            t_copy = time.monotonic()
            conn.execute("""
                INSERT OR IGNORE INTO temp_scan_snapshot
                    (path, mtime, size, file_name, file_name_no_ext, extension,
                     created_time, parent_dir, dir_depth, file_type, shapefile_group, disk_label)
                SELECT
                    f.file_path, f.modified_time, f.file_size,
                    f.file_name, f.file_name_no_ext, f.extension,
                    f.created_time, f.parent_dir, f.dir_depth, f.file_type,
                    f.shapefile_group, f.disk_label
                FROM files f
                WHERE f.parent_dir NOT IN (
                    SELECT DISTINCT parent_dir FROM temp_scan_snapshot
                )
            """)
            conn.commit()
            logger.info("[SCAN] 未变化目录文件从 files 表复制完成: 耗时=%.2fs", time.monotonic() - t_copy)

        # 7. SQL 侧三路对比（全程不把快照拉入 Python 内存）
        _state.current_phase = "对比文件变化"
        t_diff = time.monotonic()
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

        logger.info(
            "[SCAN] 三路对比完成: added=%d, deleted=%d, modified=%d, 耗时=%.2fs",
            added, deleted, modified, time.monotonic() - t_diff,
        )

        # 8. 处理新增文件：INSERT files → 同步插入 FTS
        if added:
            _state.current_phase = f"写入新增文件（{added} 条）"
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

        # 9. 处理删除文件：先删 FTS，再删 files
        if deleted:
            _state.current_phase = f"删除失效文件（{deleted} 条）"
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

        # 10. 处理修改文件：先删旧 FTS → INSERT OR REPLACE → 插入新 FTS
        if modified:
            _state.current_phase = f"更新修改文件（{modified} 条）"
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

        # 11. 替换 file_snapshots（全量，从临时表生成）
        _state.current_phase = "更新文件快照"
        conn.execute("DELETE FROM file_snapshots")
        conn.execute("""
            INSERT INTO file_snapshots (file_path, modified_time, file_size, scan_id)
            SELECT path, mtime, size, ?
            FROM temp_scan_snapshot
        """, (scan_id,))
        conn.commit()

        # 12. 更新目录快照（增量：只更新本次扫描到的目录，删除不再存在的目录）
        _state.current_phase = "更新目录快照"
        _update_dir_snapshots_incremental(conn, scan_id, changed_dirs)

        # 13. 更新扫描日志
        total_files = conn.execute("SELECT COUNT(*) FROM temp_scan_snapshot").fetchone()[0]
        conn.execute(
            "UPDATE scan_logs SET finished_at=?, total_files=?, added=?, deleted=?, modified=?, status=? WHERE id=?",
            (datetime.now().isoformat(), total_files, added, deleted, modified, "completed", scan_id),
        )
        conn.commit()

        _state.status = "completed"
        _state.added = added
        _state.deleted = deleted
        _state.modified = modified

        elapsed = time.monotonic() - t_scan_start
        logger.info(
            "[SCAN] === 增量扫描完成: 总文件=%d, added=%d, deleted=%d, modified=%d, 耗时=%.2fs ===",
            total_files, added, deleted, modified, elapsed,
        )

    except Exception as exc:
        _state.status = "failed"
        _state.error = str(exc)
        logger.error("[SCAN] 增量扫描异常: %s", exc, exc_info=True)
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

# 哨兵对象：_walk_incremental 跳过目录时 yield 此对象，以便外部统计 skipped_dirs
_SKIP_SENTINEL = object()


def _walk_incremental(
    root_path: str,
    root_depth: int,
    exclude_dirs: list[str],
    exclude_patterns: list[str],
    disk_label: str,
    dir_snapshots_dict: dict[str, str],
    changed_dirs: set[str],
) -> Iterator:
    """
    带目录 mtime 剪枝的增量遍历。
    - 若目录 mtime 未变化：跳过该目录**自身的文件**，但仍递归检查子目录
    - 若目录 mtime 变化或是新目录：正常 scandir 文件 + 递归子目录，加入 changed_dirs
    - .gdb 目录仍作为单条 gis_vector 记录
    """
    exclude_dirs_set = set(exclude_dirs)

    def _scan_dir(dir_path: str) -> Iterator:
        # 检查目录 mtime 是否变化
        try:
            dir_stat = os.stat(dir_path)
            current_mtime = datetime.fromtimestamp(dir_stat.st_mtime).isoformat()
        except OSError:
            return

        old_mtime = dir_snapshots_dict.get(dir_path)
        dir_unchanged = old_mtime is not None and current_mtime == old_mtime

        if dir_unchanged:
            # 目录自身未变化：跳过文件扫描（yield 哨兵计数），但必须继续递归子目录
            yield _SKIP_SENTINEL
        else:
            # 目录有变化或是新目录，需要扫描该目录的文件
            changed_dirs.add(dir_path)
            _state.current_dir = dir_path

        # 不论目录是否变化，都需要 scandir 以便递归检查子目录
        try:
            entries = list(os.scandir(dir_path))
        except PermissionError:
            return

        for entry in entries:
            name = entry.name

            if name in exclude_dirs_set:
                continue
            if _matches_patterns(name, exclude_patterns):
                continue

            try:
                is_dir = entry.is_dir(follow_symlinks=False)
            except OSError:
                continue

            if is_dir:
                if name.lower().endswith(".gdb"):
                    if not dir_unchanged:
                        yield _gdb_record(entry, root_depth, disk_label)
                else:
                    yield from _scan_dir(entry.path)
            elif not dir_unchanged:
                # 只有目录有变化时才收集文件
                if entry.is_file(follow_symlinks=False):
                    yield _file_record(entry, root_depth, disk_label)

    yield from _scan_dir(root_path)


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
    fp   = entry.path
    name = entry.name
    # 扩展名：从文件名找最后一个点（os.DirEntry.name 已是纯文件名）
    dot_idx = name.rfind('.')
    if dot_idx > 0:
        ext  = name[dot_idx:].lower()
        stem = name[:dot_idx]
    else:
        ext  = ""
        stem = name
    # 父目录：找路径最后一个分隔符
    sep_idx    = fp.rfind(os.sep)
    parent_dir = fp[:sep_idx] if sep_idx >= 0 else fp
    depth      = fp.count(os.sep) - root_depth + 1

    try:
        stat = entry.stat()
        size = stat.st_size
        ctime = datetime.fromtimestamp(stat.st_ctime).isoformat()
        mtime = datetime.fromtimestamp(stat.st_mtime).isoformat()
    except OSError:
        size, ctime, mtime = 0, None, None

    # Shapefile 分组：同目录同名文件共享 group 标识（父目录 + 无扩展名）
    shapefile_group = parent_dir + os.sep + stem if ext in SHAPEFILE_EXTENSIONS else None

    return {
        "file_name": name,
        "file_name_no_ext": stem,
        "extension": ext,
        "file_size": size,
        "created_time": ctime,
        "modified_time": mtime,
        "file_path": fp,
        "parent_dir": parent_dir,
        "dir_depth": depth,
        "file_type": get_file_type(ext),
        "shapefile_group": shapefile_group,
        "disk_label": disk_label,
    }


def _gdb_record(entry: os.DirEntry, root_depth: int, disk_label: str) -> dict:
    """.gdb 目录作为一条 gis_vector 记录写入，不递归。"""
    fp      = entry.path
    name    = entry.name
    sep_idx = fp.rfind(os.sep)
    parent_dir = fp[:sep_idx] if sep_idx >= 0 else fp
    dot_idx = name.rfind('.')
    stem    = name[:dot_idx] if dot_idx > 0 else name
    depth   = fp.count(os.sep) - root_depth + 1

    try:
        stat = entry.stat()
        ctime = datetime.fromtimestamp(stat.st_ctime).isoformat()
        mtime = datetime.fromtimestamp(stat.st_mtime).isoformat()
    except OSError:
        ctime, mtime = None, None

    return {
        "file_name": name,
        "file_name_no_ext": stem,
        "extension": ".gdb",
        "file_size": 0,
        "created_time": ctime,
        "modified_time": mtime,
        "file_path": fp,
        "parent_dir": parent_dir,
        "dir_depth": depth,
        "file_type": "gis_vector",
        "shapefile_group": None,
        "disk_label": disk_label,
    }


# ─── 批量写入 ──────────────────────────────────────────────────────────────────

# 全量扫描：表已清空，直接 INSERT，省去 UNIQUE 约束检查开销
_INSERT_SQL = """
INSERT INTO files
    (file_name, file_name_no_ext, extension, file_size, created_time,
     modified_time, file_path, parent_dir, dir_depth, file_type,
     shapefile_group, disk_label)
VALUES
    (:file_name, :file_name_no_ext, :extension, :file_size, :created_time,
     :modified_time, :file_path, :parent_dir, :dir_depth, :file_type,
     :shapefile_group, :disk_label)
"""

# 增量扫描修改文件时需要 INSERT OR REPLACE（文件可能已存在）
_INSERT_OR_REPLACE_SQL = """
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


# ─── 目录快照辅助函数 ───────────────────────────────────────────────────────────

def _rebuild_dir_snapshots(conn, scan_id: int) -> None:
    """
    全量扫描后重建目录快照（旧接口，内部委托给 fast 版本）。
    """
    _rebuild_dir_snapshots_fast(conn, scan_id)


def _rebuild_dir_snapshots_fast(conn, scan_id: int) -> None:
    """
    全量扫描后重建目录快照（bulk-load 版本）：
    DROP→无索引 INSERT（os.stat 获取 mtime）→末尾建唯一索引，
    比逐行维护 PRIMARY KEY B-tree 快 10x+。
    """
    t = time.monotonic()
    dirs = [row[0] for row in conn.execute(
        "SELECT DISTINCT parent_dir FROM files WHERE parent_dir IS NOT NULL"
    ).fetchall()]

    # DROP+重建无索引表，末尾统一建索引（bulk-load）
    conn.executescript("""
        DROP TABLE IF EXISTS dir_snapshots;
        CREATE TABLE dir_snapshots (
            dir_path  TEXT NOT NULL,
            dir_mtime TEXT,
            scan_id   INTEGER
        );
    """)

    batch: list[tuple] = []
    for dir_path in dirs:
        try:
            mtime = datetime.fromtimestamp(os.stat(dir_path).st_mtime).isoformat()
        except OSError:
            continue
        batch.append((dir_path, mtime, scan_id))
        if len(batch) >= 5000:
            conn.executemany(
                "INSERT INTO dir_snapshots (dir_path, dir_mtime, scan_id) VALUES (?, ?, ?)",
                batch,
            )
            batch.clear()

    if batch:
        conn.executemany(
            "INSERT INTO dir_snapshots (dir_path, dir_mtime, scan_id) VALUES (?, ?, ?)",
            batch,
        )
    conn.commit()
    conn.execute("CREATE UNIQUE INDEX idx_dir_snapshots_path ON dir_snapshots(dir_path)")
    conn.commit()
    logger.info("[SCAN] 目录快照重建完成: %d 个目录, 耗时=%.2fs", len(dirs), time.monotonic() - t)


def _update_dir_snapshots_incremental(conn, scan_id: int, changed_dirs: set[str]) -> None:
    """
    增量扫描后更新目录快照：
    - 更新/新增本次实际扫描到的目录（changed_dirs）
    - 删除文件系统中已不存在的目录（从 dir_snapshots 中移除）
    """
    if not changed_dirs:
        return

    t = time.monotonic()

    # 更新/新增变化目录的 mtime
    batch: list[tuple] = []
    for dir_path in changed_dirs:
        try:
            mtime = datetime.fromtimestamp(os.stat(dir_path).st_mtime).isoformat()
        except OSError:
            # 目录已删除，后续清理步骤会处理
            continue
        batch.append((dir_path, mtime, scan_id))

    if batch:
        conn.executemany(
            "INSERT OR REPLACE INTO dir_snapshots (dir_path, dir_mtime, scan_id) VALUES (?, ?, ?)",
            batch,
        )

    # 删除文件系统中已不存在的目录记录
    # 策略：dir_snapshots 中不在 files.parent_dir 里的条目即为已删除目录
    conn.execute("""
        DELETE FROM dir_snapshots
        WHERE dir_path NOT IN (
            SELECT DISTINCT parent_dir FROM files WHERE parent_dir IS NOT NULL
        )
    """)
    conn.commit()
    logger.info(
        "[SCAN] 目录快照增量更新完成: 更新=%d个目录, 耗时=%.3fs",
        len(batch), time.monotonic() - t,
    )
