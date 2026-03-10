import logging

from fastapi import APIRouter, HTTPException, Query

from backend.config import get_config
from backend.database import get_db
from backend.models import MonitorStartRequest, ScanStartRequest
from backend.services import scanner, usn_monitor

router = APIRouter(tags=["scan"])
logger = logging.getLogger(__name__)


@router.post("/scan/start")
async def start_scan(body: ScanStartRequest):
    """
    启动扫描任务。
    - root_path: 要扫描的根目录（如 E:\\ 或 E:\\工作文件）
    - scan_type: "full"（全量）或 "incremental"（增量）
      增量扫描要求已存在快照；若快照不存在则自动回退到全量扫描。
    若已有扫描在运行，返回 409。
    """
    logger.info("[API] POST /scan/start: root_path=%s, scan_type=%s", body.root_path, body.scan_type)
    cfg = get_config()

    # 从配置中查找该路径对应的磁盘标签
    disk_label = ""
    req_path = body.root_path.rstrip("\\").rstrip("/")
    for root in cfg.get("scan_roots", []):
        cfg_path = root.get("path", "").rstrip("\\").rstrip("/")
        if cfg_path.lower() == req_path.lower():
            disk_label = root.get("disk_label", "")
            break

    scan_kwargs = dict(
        root_path=body.root_path,
        disk_label=disk_label,
        exclude_dirs=cfg.get("exclude_dirs", []),
        exclude_patterns=cfg.get("exclude_patterns", []),
    )

    if body.scan_type == "incremental":
        # 检查是否存在历史快照，若无则回退全量
        conn = get_db()
        try:
            has_snapshot = conn.execute(
                "SELECT 1 FROM file_snapshots LIMIT 1"
            ).fetchone() is not None
        finally:
            conn.close()

        if has_snapshot:
            started = scanner.start_incremental_scan(**scan_kwargs)
            actual_type = "incremental"
        else:
            started = scanner.start_full_scan(**scan_kwargs)
            actual_type = "full (fallback: no snapshot)"
    else:
        started = scanner.start_full_scan(**scan_kwargs)
        actual_type = "full"

    if not started:
        logger.warning("[API] 扫描任务已在运行，拒绝新请求 (root=%s)", body.root_path)
        raise HTTPException(status_code=409, detail="扫描任务已在进行中，请等待完成后重试")

    logger.info("[API] 扫描任务已提交: actual_type=%s, root=%s", actual_type, body.root_path)
    return {"status": "started", "root_path": body.root_path, "scan_type": actual_type}


@router.get("/scan/status")
async def get_scan_status():
    """返回当前扫描进度。"""
    state = scanner.get_state()
    logger.debug(
        "[API] GET /scan/status: status=%s method=%s scanned=%d added=%d",
        state.status, state.scan_method, state.scanned_count, state.added,
    )
    return {
        "status": state.status,
        "scan_id": state.scan_id,
        "root_path": state.root_path,
        "scanned_count": state.scanned_count,
        "added": state.added,
        "deleted": state.deleted,
        "modified": state.modified,
        "current_dir": state.current_dir,
        "started_at": state.started_at,
        "error": state.error,
        "scan_method": state.scan_method,
    }


@router.get("/scan/logs")
async def get_scan_logs(limit: int = Query(20, ge=1, le=100)):
    """返回扫描历史记录，最新的排在最前。"""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM scan_logs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return {"logs": [dict(r) for r in rows]}
    finally:
        conn.close()


@router.post("/scan/monitor/start")
async def start_monitor(body: MonitorStartRequest):
    """
    启动 NTFS USN Journal 实时监控。
    - roots: 要监控的根路径列表，如 ["E:\\\\", "D:\\\\工作文件"]
    - 每个路径提取卷符（E:）后启动独立监控线程
    - 若该卷已在监控中，跳过（不重启）
    - 需要以管理员权限运行服务（FSCTL_READ_USN_JOURNAL 需要 SeManageVolumePrivilege）
    """
    if not body.roots:
        raise HTTPException(status_code=422, detail="roots 不能为空")
    result = usn_monitor.start_monitoring(body.roots)
    return {
        "status": "ok",
        "started_volumes": result["started"],
        "already_running": result["already_running"],
    }


@router.post("/scan/monitor/stop")
async def stop_monitor():
    """
    停止所有卷的 USN Journal 监控线程。
    等待线程退出（最多 5 秒），返回已停止的卷列表。
    """
    result = usn_monitor.stop_monitoring()
    return {"status": "ok", "stopped_volumes": result["stopped"]}


@router.get("/scan/monitor/status")
async def get_monitor_status():
    """
    返回 USN Journal 监控状态。
    {
        "running": bool,
        "watching_volumes": [{"volume", "status", "events_processed",
                              "upserted", "deleted", "skipped",
                              "started_at", "restart_count", "last_error"}],
        "events_processed": int
    }
    """
    return usn_monitor.get_status()
