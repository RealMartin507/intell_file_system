# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

本地文件智能管理系统，面向测绘地理信息行业个人用户，支持35万+文件的高效扫描、检索与管理。技术栈：FastAPI + SQLite（WAL + FTS5）+ Vanilla JavaScript。

## 运行与开发

**启动服务**（必须使用项目专用 Python 环境）：
```bash
C:/Users/mmm/.conda/envs/file-manager/python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
# 开发时加 --reload 避免手动重启
```

**端口冲突处理**：
```bash
netstat -ano | findstr :8000
taskkill //F //PID <pid>
```

**数据库调试**：
```bash
sqlite3 data/file_index.db
```

**API 快速验证**：
```bash
curl -X POST http://localhost:8000/api/scan/start -H "Content-Type: application/json" -d '{"root_path":"E:\\","scan_type":"full"}'
curl "http://localhost:8000/api/search?q=roads&type=gis_vector&page=1&size=20"
curl http://localhost:8000/api/stats/overview
```

## 代码架构

### 后端（已完成）

**入口**：`backend/main.py` — 挂载所有 router，前端静态文件挂载到 `/`，`/` 返回 `frontend/index.html`。

**数据库**（`backend/database.py`）：
- `files` 主表（18字段）+ `files_fts` FTS5虚拟表（content='files'，unicode61 tokenizer）
- `file_snapshots` 快照表（支持增量扫描对比）
- `scan_logs` 历史表
- 启动时自动 `init_db()`，WAL模式 + 32MB cache

**扫描服务**（`backend/services/scanner.py`）：
- 全局 `_state: ScanState` 暴露进度
- 全量扫描：清空表 → `os.scandir()` 递归 → 每1000条批量 commit → 重建FTS5
- 增量扫描：快照对比（mtime + size）→ 分批处理 added/deleted/modified → 有变更才重建FTS5
- 特殊规则：`.gdb` 目录作为单条 `gis_vector` 记录（不递归）；同目录同名文件自动组成 Shapefile 组（`shapefile_group = parent_dir/stem`）
- 在 `ThreadPoolExecutor(max_workers=1)` 线程中运行

**搜索**（`backend/routers/search.py`）：
- `q` 有值：FTS5（`"词1" "词2"` AND 逻辑）+ LIKE 兜底取并集，Python 侧按 FTS5命中 > 文件名命中 > 路径命中 > 修改时间排序
- `q` 为空 + `type` 有值：直接 SQL 分页浏览
- `_MAX_HITS = 800`（防超 SQLite 参数限制）
- Shapefile 分组：同 `shapefile_group` 合并，选 `.shp` 为代表，`related_count` 记组内匹配数

**文件操作**（`backend/routers/files.py`）：
- 缩略图：Pillow 懒加载，生成 256×256 JPEG 缓存到 `data/thumbnails/{id}.jpg`
- 打开文件：`os.startfile()`；定位到文件夹：`Popen('explorer /select,"path"', shell=True)`
- 文件离线时：open-dir 降级打开父目录

**配置**（`backend/config.py` + `config.json`）：
- 单例模式，`get_config()` 从内存读，`reload_config()` 强制重载
- 支持多扫描根 `scan_roots`、排除目录/通配符模式

### 前端（待实现）

前端位于 `frontend/`，目前 `index.html` 和 `style.css` 已有骨架，以下 JS 文件为空壳待实现：
- `app.js`：DOMContentLoaded 全局初始化
- `dashboard.js`：调用 `/api/stats/overview` 填充统计卡片
- `search.js`：搜索框监听、调用 `/api/search`、渲染结果列表、点击调用 open/open-dir
- `preview.js`：调用 `/api/files/{id}/preview` 展示预览面板

UI 设计参考：`UI-DESIGN/file-manager-ui.html`（完整设计稿）。

## 关键约定

- **文件类型分类**：见 `backend/utils/file_types.py` `FILE_TYPE_MAP`，13类，未知扩展名统一归 `other`
- **GIS 特殊类型**：`gis_vector`（含 Shapefile、GeoDatabase）、`gis_raster`、`mapgis`、`fme`、`survey`
- 排除规则：`$RECYCLE.BIN`、`System Volume Information`、`~$*`、`*.tmp` 等
- 前端无任何框架依赖，仅用原生 Fetch API 与后端通信
