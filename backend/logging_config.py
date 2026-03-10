"""
日志系统配置

在 main.py 启动时最先调用 setup_logging()，之后所有模块通过
logging.getLogger(__name__) 自动获得文件+控制台双输出。

日志文件：项目根目录/logs/app.log（RotatingFileHandler，10MB × 5份，UTF-8）
"""

import logging
import logging.handlers
import sys
from pathlib import Path

# 项目根目录（backend/ 的上级）
_PROJECT_ROOT = Path(__file__).parent.parent
_LOG_DIR  = _PROJECT_ROOT / "logs"
_LOG_FILE = _LOG_DIR / "app.log"

# 格式：[2026-03-09 14:30:00.123] [INFO ] [module_name] 消息内容
_FMT      = "[%(asctime)s.%(msecs)03d] [%(levelname)-5s] [%(name)s] %(message)s"
_DATE_FMT = "%Y-%m-%d %H:%M:%S"


def setup_logging(level: int = logging.DEBUG) -> None:
    """
    初始化根 logger（幂等，重复调用安全）。

    - RotatingFileHandler → logs/app.log，DEBUG 全量记录
    - StreamHandler       → stdout，INFO+ 输出（减少控制台噪音）
    - uvicorn access log  → 降到 WARNING，避免与应用日志混杂
    """
    root = logging.getLogger()
    if root.handlers:
        # 已配置（支持 --reload 热重载场景），跳过重复初始化
        return

    _LOG_DIR.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(_FMT, datefmt=_DATE_FMT)

    # ── 文件 handler ──────────────────────────────────────────────────────────
    file_handler = logging.handlers.RotatingFileHandler(
        filename    = str(_LOG_FILE),
        maxBytes    = 10 * 1024 * 1024,  # 10 MB
        backupCount = 5,
        encoding    = "utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)

    # ── 控制台 handler ────────────────────────────────────────────────────────
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    stream_handler.setLevel(logging.INFO)

    root.setLevel(level)
    root.addHandler(file_handler)
    root.addHandler(stream_handler)

    # uvicorn 自带的 access log 很冗余，降级到 WARNING
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    logging.getLogger("logging_config").info(
        "日志系统初始化完成: file=%s", _LOG_FILE
    )


def get_log_path() -> Path:
    """返回当前日志文件路径（供 API 端点使用）。"""
    return _LOG_FILE
