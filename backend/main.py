from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.database import init_db
from backend.routers import config_router, files, scan, search, stats

app = FastAPI(title="本地文件智能管理系统", version="1.0.0")

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


@app.on_event("startup")
async def startup() -> None:
    init_db()


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
