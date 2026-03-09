# 本地文件智能管理系统

面向**测绘地理信息行业**个人用户的本地文件索引与检索工具，支持 35 万+ 文件的高效扫描、全文搜索与管理。

## 功能特性

- **快速扫描**：支持全量 / 增量两种模式；管理员权限下自动启用 NTFS MFT 直读，速度提升 2~5×
- **全文搜索**：FTS5（unicode61）+ LIKE 双引擎，支持中英文混合检索
- **GIS 文件识别**：Shapefile 自动分组、FileGDB（.gdb）单条记录、13 种文件类型分类
- **文件操作**：一键打开文件 / 定位到文件夹、图片缩略图预览
- **扫描配置**：多扫描根目录、自定义排除目录与文件名通配符

## 技术栈

| 层次 | 技术 |
|------|------|
| 后端 | Python 3.11 · FastAPI · uvicorn |
| 数据库 | SQLite（WAL + FTS5） |
| 前端 | Vanilla JS · Tailwind CSS · Lucide Icons |
| MFT 扫描 | ctypes + `DeviceIoControl(FSCTL_ENUM_USN_DATA)` |

## 快速开始

### 环境要求

- Windows 10/11（MFT 加速仅限 NTFS 卷）
- [Miniconda](https://docs.conda.io/en/latest/miniconda.html) 已安装
- conda 环境 `file-manager`（含 FastAPI、uvicorn、Pillow）

### 启动服务

**普通模式**（os.scandir 扫描）：
```
双击 start.bat
```

**管理员模式**（NTFS MFT 直读，扫描更快）：
```
右键 start.bat → 以管理员身份运行
```

服务启动后访问：[http://127.0.0.1:8000](http://127.0.0.1:8000)

### 手动启动（开发调试）

```bash
C:/Users/mmm/.conda/envs/file-manager/python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

### 端口冲突处理

```bash
netstat -ano | findstr :8000
taskkill /F /PID <pid>
```

## 扫描模式说明

| 模式 | 触发条件 | 速度 |
|------|---------|------|
| MFT 直读 | 以管理员身份运行 + NTFS 卷 | 快（2~5×） |
| os.scandir | 非管理员 / 非 NTFS / MFT 失败 | 标准 |

增量扫描通过 mtime + size 快照对比，仅处理变更文件，日常使用首选增量模式。
当前使用的扫描方式可通过 `GET /api/scan/status` 的 `scan_method` 字段查看。

## 主要 API

```
POST /api/scan/start          # 启动扫描 {"root_path":"E:\\","scan_type":"full|incremental"}
GET  /api/scan/status         # 扫描进度与方式（scan_method: "mft" | "scandir"）
GET  /api/scan/logs           # 历史扫描记录

GET  /api/search              # 搜索 ?q=roads&type=gis_vector&page=1&size=20
GET  /api/stats/overview      # 文件总数、类型分布、数据库大小
GET  /api/stats/types         # 各类型文件数量与总大小

GET  /api/files/{id}          # 文件详情
GET  /api/files/{id}/preview  # 图片缩略图 / 基本信息
POST /api/files/{id}/open     # 打开文件
POST /api/files/{id}/open-dir # 在资源管理器中定位
```

## 项目结构

```
intell_file_system/
├── backend/
│   ├── main.py               # FastAPI 入口，挂载所有 router
│   ├── database.py           # SQLite 初始化、FTS5 表结构
│   ├── config.py             # 配置单例（读写 config.json）
│   ├── routers/
│   │   ├── scan.py           # 扫描控制 API
│   │   ├── search.py         # 搜索 API（FTS5 + LIKE）
│   │   ├── files.py          # 文件操作 API
│   │   └── stats.py          # 统计 API
│   ├── services/
│   │   ├── scanner.py        # 扫描调度（全量 / 增量 / MFT 集成）
│   │   └── mft_scanner.py    # NTFS MFT 直读（ctypes，需管理员权限）
│   └── utils/
│       └── file_types.py     # 13 种文件类型映射表
├── frontend/                 # 纯原生 JS 前端
├── data/                     # SQLite 数据库 + 缩略图缓存（git 忽略）
├── config.json               # 用户配置（扫描路径、排除规则）
└── start.bat                 # 一键启动脚本
```

## 支持的文件类型

`document` · `spreadsheet` · `presentation` · `image` · `cad`
`gis_vector`（Shapefile / GDB / GeoJSON / KML …）
`gis_raster`（GeoTIFF / IMG / ECW …）
`mapgis` · `fme` · `survey`（点云 LAS / E57）· `archive` · `other`
