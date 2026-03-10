# ── 必须在所有其他 import 之前完成日志配置 ───────────────────────────────────
from backend.logging_config import setup_logging
setup_logging()
# ────────────────────────────────────────────────────────────────────────────

import logging
import os
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.database import DB_PATH, init_db
from backend.routers import config_router, files, scan, search, stats

logger = logging.getLogger(__name__)

app = FastAPI(title="本地文件智能管理系统", version="1.0.0")

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


@app.on_event("startup")
async def startup() -> None:
    logger.info("=" * 60)
    logger.info("[STARTUP] ===== 系统启动 =====")
    logger.info("[STARTUP] Python版本: %s", sys.version.split()[0])
    logger.info("[STARTUP] 工作目录: %s", os.getcwd())

    # 管理员权限检测
    try:
        from backend.services.mft_scanner import is_admin
        admin = is_admin()
    except Exception as exc:
        admin = False
        logger.warning("[STARTUP] 管理员权限检测失败: %s", exc)
    logger.info(
        "[STARTUP] 管理员权限: %s%s",
        "是 ✓ (MFT扫描和USN监控可用)" if admin else "否",
        "" if admin else " ✗ (MFT/USN不可用，将使用os.scandir回退模式)",
    )

    # 数据库状态
    db_exists  = DB_PATH.exists()
    db_size_mb = DB_PATH.stat().st_size / 1024 / 1024 if db_exists else 0.0
    logger.info(
        "[STARTUP] 数据库路径: %s (%s, 大小: %.2f MB)",
        DB_PATH,
        "已存在" if db_exists else "不存在（将自动创建）",
        db_size_mb,
    )

    # 初始化数据库
    init_db()

    # 初始化后统计文件数和大小为0的记录（诊断MFT属性填充问题）
    try:
        import sqlite3
        _conn = sqlite3.connect(str(DB_PATH))
        try:
            file_count    = _conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
            zero_size_cnt = _conn.execute(
                "SELECT COUNT(*) FROM files WHERE file_size = 0 OR file_size IS NULL"
            ).fetchone()[0]
            logger.info(
                "[STARTUP] [DB] 当前文件数: %d, 大小为0的文件: %d%s",
                file_count,
                zero_size_cnt,
                (
                    " *** 警告: 超过50%%记录大小为0，可能是MFT属性填充失败 ***"
                    if file_count > 0 and zero_size_cnt > file_count * 0.5
                    else " (正常)" if file_count > 0 else ""
                ),
            )
        finally:
            _conn.close()
    except Exception as exc:
        logger.warning("[STARTUP] DB文件统计查询失败: %s", exc)

    logger.info("[STARTUP] ===== 启动完成，监听 http://127.0.0.1:8000 =====")
    logger.info("=" * 60)


# 注册 API 路由（必须在静态文件挂载之前，优先级更高）
app.include_router(scan.router, prefix="/api")
app.include_router(search.router, prefix="/api")
app.include_router(files.router, prefix="/api")
app.include_router(stats.router, prefix="/api")
app.include_router(config_router.router, prefix="/api")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(str(FRONTEND_DIR / "index.html"))


# 挂载前端静态资源（放在所有路由之后）
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR)), name="frontend")
