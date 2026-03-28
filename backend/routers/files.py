"""
文件操作路由

GET  /api/files/{id}           返回文件详情
GET  /api/files/{id}/path      返回完整路径（前端复制到剪贴板）
GET  /api/files/{id}/preview   图片返回缩略图；其他文件返回基本信息
POST /api/files/{id}/open      os.startfile() 打开文件
POST /api/files/{id}/open-dir  explorer /select 定位文件
"""

import ctypes
import os
import subprocess
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse

from backend.database import DB_PATH, get_db

router = APIRouter(tags=["files"])

# 缩略图缓存目录（与 DB 同级的 data/thumbnails）
_THUMB_DIR = DB_PATH.parent / "thumbnails"
_THUMB_SIZE = (256, 256)

# 支持生成缩略图的扩展名
_IMAGE_EXTS = frozenset({
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp",
    ".tif", ".tiff",
})


# ── 内部工具 ────────────────────────────────────────────────────────────────────

def _query_file(conn, file_id: int) -> dict:
    """按 id 查文件记录，不存在则抛 404。"""
    row = conn.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
    if not row:
        raise HTTPException(
            status_code=404,
            detail=f"文件记录不存在（id={file_id}）",
        )
    return dict(row)


def _disk_status(file_path: str) -> dict:
    """检查文件是否存在于磁盘，返回状态字段。"""
    exists = Path(file_path).exists()
    return {
        "on_disk": exists,
        "unavailable_reason": None if exists else "文件不在磁盘上，可能磁盘未插入或文件已移动",
    }


def _make_thumbnail(file_id: int, src: Path) -> Optional[Path]:
    """
    生成或返回缓存缩略图。
    成功返回缩略图 Path，失败（Pillow 未安装 / 解码错误）返回 None。
    """
    _THUMB_DIR.mkdir(parents=True, exist_ok=True)
    thumb = _THUMB_DIR / f"{file_id}.jpg"
    if thumb.exists():
        return thumb
    try:
        from PIL import Image  # 懒加载，未安装时只影响预览
        with Image.open(src) as img:
            img.thumbnail(_THUMB_SIZE, Image.LANCZOS)
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            img.save(str(thumb), "JPEG", quality=85)
        return thumb
    except Exception:
        return None


# ── 路由（子路径先于 bare {file_id}，避免匹配歧义）─────────────────────────────

@router.get("/files/{file_id}/path")
async def get_file_path(file_id: int):
    """返回文件完整路径，前端用于复制到剪贴板。"""
    conn = get_db()
    try:
        record = _query_file(conn, file_id)
        return {
            "file_path": record["file_path"],
            **_disk_status(record["file_path"]),
        }
    finally:
        conn.close()


@router.get("/files/{file_id}/preview")
async def preview_file(file_id: int):
    """
    图片文件：生成 256×256 缩略图（Pillow），缓存后以 image/jpeg 返回。
    其他文件：返回基本元信息 JSON。
    文件不在磁盘：返回 JSON 说明原因。
    """
    conn = get_db()
    try:
        record = _query_file(conn, file_id)
        file_path = Path(record["file_path"])
        ext = (record.get("extension") or "").lower()

        if not file_path.exists():
            return JSONResponse({
                "available": False,
                "message": "文件不在磁盘上，可能磁盘未插入或文件已移动",
                "file_name": record["file_name"],
                "file_type": record["file_type"],
                "file_size": record["file_size"],
            })

        # 图片：尝试生成缩略图
        if ext in _IMAGE_EXTS:
            thumb = _make_thumbnail(file_id, file_path)
            if thumb:
                return FileResponse(str(thumb), media_type="image/jpeg")

        # 非图片或缩略图生成失败：返回基本信息
        return {
            "available": True,
            "file_name": record["file_name"],
            "file_type": record["file_type"],
            "extension": ext,
            "file_size": record["file_size"],
            "modified_time": record["modified_time"],
            "parent_dir": record["parent_dir"],
        }
    finally:
        conn.close()


@router.post("/files/{file_id}/open")
async def open_file(file_id: int):
    """用系统默认程序打开文件（os.startfile）。"""
    conn = get_db()
    try:
        record = _query_file(conn, file_id)
        file_path = record["file_path"]

        if not Path(file_path).exists():
            return {
                "status": "error",
                "message": f"文件不在磁盘上，可能磁盘未插入或文件已移动：{file_path}",
            }

        try:
            os.startfile(file_path)  # Windows-only
            return {"status": "ok", "file_path": file_path}
        except OSError as exc:
            return {"status": "error", "message": str(exc)}
    finally:
        conn.close()


@router.post("/files/{file_id}/open-dir")
async def open_file_dir(file_id: int):
    """在资源管理器中定位并选中文件（explorer /select）。"""
    conn = get_db()
    try:
        record = _query_file(conn, file_id)
        file_path = record["file_path"]

        if Path(file_path).exists():
            # 用 ShellExecuteW 调用 Windows API，正确处理含中文/空格的路径
            ctypes.windll.shell32.ShellExecuteW(
                None, "open", "explorer.exe", f'/select,"{file_path}"', None, 1
            )
            return {"status": "ok", "file_path": file_path}

        # 文件不存在时尝试打开父目录
        parent = str(Path(file_path).parent)
        if Path(parent).exists():
            ctypes.windll.shell32.ShellExecuteW(
                None, "open", "explorer.exe", parent, None, 1
            )
            return {
                "status": "partial",
                "message": "文件不存在，已打开所在目录",
                "opened_dir": parent,
            }

        return {
            "status": "error",
            "message": f"文件及其目录均不存在，可能磁盘未插入：{file_path}",
        }
    finally:
        conn.close()


@router.get("/files/{file_id}")
async def get_file(file_id: int):
    """返回文件全部元信息，并附加 on_disk 状态。"""
    conn = get_db()
    try:
        record = _query_file(conn, file_id)
        record.update(_disk_status(record["file_path"]))
        return record
    finally:
        conn.close()
