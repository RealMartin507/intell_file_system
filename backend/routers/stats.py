"""
统计路由

GET /api/stats/overview   文件总数、各类型数量、最近扫描信息、数据库大小
GET /api/stats/types      按 file_type 分组的数量与总大小（前端饼图数据）
"""

from fastapi import APIRouter

from backend.database import DB_PATH, get_db

router = APIRouter(tags=["stats"])


@router.get("/stats/overview")
async def get_overview():
    """
    返回：
    - total_files      : 数据库中文件总条数
    - type_counts      : {file_type: count} 各类型数量
    - last_scan        : 最近一次扫描记录（scan_logs 最新行）
    - db_size_bytes    : SQLite 文件大小（字节）
    - db_size_mb       : SQLite 文件大小（MB，保留 2 位小数）
    """
    conn = get_db()
    try:
        # 文件总数
        total = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]

        # 各类型数量
        rows = conn.execute(
            "SELECT file_type, COUNT(*) AS cnt FROM files GROUP BY file_type ORDER BY cnt DESC"
        ).fetchall()
        type_counts = {(r["file_type"] or "other"): r["cnt"] for r in rows}

        # 最近扫描记录
        last_row = conn.execute(
            """
            SELECT scan_type, root_path, started_at, finished_at,
                   total_files, added, deleted, modified, status
            FROM scan_logs
            ORDER BY id DESC LIMIT 1
            """
        ).fetchone()
        last_scan = dict(last_row) if last_row else None

        # 数据库文件大小
        db_bytes = DB_PATH.stat().st_size if DB_PATH.exists() else 0

        return {
            "total_files": total,
            "type_counts": type_counts,
            "last_scan": last_scan,
            "db_size_bytes": db_bytes,
            "db_size_mb": round(db_bytes / 1024 / 1024, 2),
        }
    finally:
        conn.close()


@router.get("/stats/types")
async def get_type_distribution():
    """
    按 file_type 分组，返回每种类型的文件数量和总大小，供前端饼图使用。

    响应格式：
    {
      "distribution": [
        {"file_type": "document", "count": 120, "total_size": 524288000},
        ...
      ]
    }
    """
    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT
                COALESCE(file_type, 'other') AS file_type,
                COUNT(*)                     AS count,
                SUM(COALESCE(file_size, 0))  AS total_size
            FROM files
            GROUP BY file_type
            ORDER BY count DESC
            """
        ).fetchall()
        return {
            "distribution": [
                {
                    "file_type": r["file_type"],
                    "count": r["count"],
                    "total_size": r["total_size"],
                }
                for r in rows
            ]
        }
    finally:
        conn.close()
