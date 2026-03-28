import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "file_index.db"


def get_db() -> sqlite3.Connection:
    """获取数据库连接，row_factory 已设置为 sqlite3.Row。"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """初始化数据库：创建目录、建表、建索引，并迁移 FTS5 表结构。"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA cache_size = -262144")
        conn.execute("PRAGMA mmap_size = 536870912")
        _create_tables(conn)
        _migrate_fts_schema(conn)
    finally:
        conn.close()


def fts_insert(conn: sqlite3.Connection, file_id: int) -> None:
    """将 files 表中 id=file_id 的记录同步插入 files_fts 索引。
    调用方须确保文件已写入 files 表后再调用。"""
    conn.execute(
        "INSERT INTO files_fts(rowid, file_name, file_path, file_type) "
        "SELECT id, file_name, file_path, file_type FROM files WHERE id = ?",
        (file_id,),
    )


def fts_delete(conn: sqlite3.Connection, file_id: int) -> None:
    """从 files_fts 索引删除指定行。
    必须在从 files 表删除同一行之前调用，以便 content FTS5 正确读取旧文本值。"""
    conn.execute("DELETE FROM files_fts WHERE rowid = ?", (file_id,))


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

        -- 全文搜索虚拟表（FTS5）：仅索引 file_name/file_path/file_type 三列
        -- unicode61 tokenizer 支持多语言分词
        CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
            file_name,
            file_path,
            file_type,
            content='files',
            content_rowid='id',
            tokenize='unicode61'
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

        -- 目录快照表（用于增量扫描目录 mtime 剪枝）
        CREATE TABLE IF NOT EXISTS dir_snapshots (
            dir_path  TEXT PRIMARY KEY,
            dir_mtime TEXT,
            scan_id   INTEGER
        );

        -- 索引
        CREATE INDEX IF NOT EXISTS idx_files_extension  ON files(extension);
        CREATE INDEX IF NOT EXISTS idx_files_file_type  ON files(file_type);
        CREATE INDEX IF NOT EXISTS idx_files_modified   ON files(modified_time);
        CREATE INDEX IF NOT EXISTS idx_files_parent_dir ON files(parent_dir);
        CREATE INDEX IF NOT EXISTS idx_files_shp_group  ON files(shapefile_group);
    """)
    conn.commit()


def _migrate_fts_schema(conn: sqlite3.Connection) -> None:
    """检测并升级 FTS5 表结构。
    旧版表含 file_name_no_ext 列或缺少 file_type 列时，自动重建（清空 FTS 索引，需重新扫描填充）。
    """
    try:
        cur = conn.execute("SELECT * FROM files_fts LIMIT 0")
        cols = {d[0] for d in cur.description} if cur.description else set()
        if "file_type" in cols and "file_name_no_ext" not in cols:
            return  # 已是新版结构，无需迁移
    except Exception:
        return  # 表不存在或查询异常，交由 _create_tables 处理

    # 旧结构：重建 FTS 表（清空索引，待下次全量扫描重建内容）
    conn.execute("DROP TABLE IF EXISTS files_fts")
    conn.execute("""
        CREATE VIRTUAL TABLE files_fts USING fts5(
            file_name,
            file_path,
            file_type,
            content='files',
            content_rowid='id',
            tokenize='unicode61'
        )
    """)
    conn.commit()
