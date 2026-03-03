import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "file_index.db"


def get_db() -> sqlite3.Connection:
    """获取数据库连接，row_factory 已设置为 sqlite3.Row。"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """初始化数据库：创建目录、建表、建索引。"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        _create_tables(conn)
    finally:
        conn.close()


def _create_tables(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        -- 文件索引主表
        CREATE TABLE IF NOT EXISTS files (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            file_name         TEXT NOT NULL,
            file_name_no_ext  TEXT NOT NULL,
            extension         TEXT,
            file_size         INTEGER,
            created_time      TEXT,
            modified_time     TEXT,
            file_path         TEXT NOT NULL UNIQUE,
            parent_dir        TEXT,
            dir_depth         INTEGER,
            file_type         TEXT,
            shapefile_group   TEXT,
            disk_label        TEXT,
            is_available      INTEGER DEFAULT 1,
            content_text      TEXT,
            content_indexed   INTEGER DEFAULT 0,
            thumbnail_path    TEXT,
            created_at        TEXT DEFAULT (datetime('now')),
            updated_at        TEXT DEFAULT (datetime('now'))
        );

        -- 全文搜索虚拟表（FTS5）
        CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
            file_name,
            file_name_no_ext,
            file_path,
            content='files',
            content_rowid='id'
        );

        -- 扫描记录表
        CREATE TABLE IF NOT EXISTS scan_logs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_type   TEXT,
            root_path   TEXT,
            started_at  TEXT,
            finished_at TEXT,
            total_files INTEGER,
            added       INTEGER DEFAULT 0,
            deleted     INTEGER DEFAULT 0,
            modified    INTEGER DEFAULT 0,
            status      TEXT
        );

        -- 快照表（用于增量对比）
        CREATE TABLE IF NOT EXISTS file_snapshots (
            file_path     TEXT PRIMARY KEY,
            modified_time TEXT,
            file_size     INTEGER,
            scan_id       INTEGER,
            FOREIGN KEY (scan_id) REFERENCES scan_logs(id)
        );

        -- 索引
        CREATE INDEX IF NOT EXISTS idx_files_extension  ON files(extension);
        CREATE INDEX IF NOT EXISTS idx_files_file_type  ON files(file_type);
        CREATE INDEX IF NOT EXISTS idx_files_modified   ON files(modified_time);
        CREATE INDEX IF NOT EXISTS idx_files_parent_dir ON files(parent_dir);
        CREATE INDEX IF NOT EXISTS idx_files_shp_group  ON files(shapefile_group);
    """)
    conn.commit()
