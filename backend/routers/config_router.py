from fastapi import APIRouter
from backend.config import get_config, save_config

router = APIRouter(tags=["config"])


@router.get("/config")
async def read_config():
    return get_config()


@router.put("/config")
async def update_config(new_config: dict):
    save_config(new_config)
    return {"status": "ok"}


@router.get("/disk/status")
async def disk_status():
    # TODO: 检测已配置磁盘的在线状态
    return {"disks": []}
