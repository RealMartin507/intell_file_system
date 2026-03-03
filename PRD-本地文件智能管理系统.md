# 本地文件智能管理系统 — 产品需求文档（PRD）

> 版本：v1.0 | 日期：2026-03-01 | 状态：待评审

---

## 一、产品概述

### 1.1 产品定位

一个运行在 Windows 本地的 Web 端文件智能管理系统，面向拥有大量工作文件（35万+文件，2TB 移动硬盘）的测绘地理信息行业个人用户，替代现有的"Excel 索引表"工作流，实现文件的快速搜索、定位、预览和打开。

### 1.2 核心问题

用户当前工作流：手动维护一张 Excel 表，记录文件路径、名称、类型等信息，用于在填报系统时快速找到文件并上传。

痛点：

- Excel 表体量大（35万行级别）导致操作卡顿
- 手动维护成本高，新增文件容易遗漏
- 无法预览文件内容
- 无法进行语义搜索
- GIS/CAD 专业文件（Shapefile、GeoTIFF、DWG 等）管理困难

### 1.3 目标用户

个人使用，经常需要将找到的文件分享给同事或上传到业务系统。

---

## 二、数据现状分析

| 维度   | 详情                                          |
| ---- | ------------------------------------------- |
| 存储介质 | 2TB 移动硬盘（USB 连接，盘符可能变化）+ 一个本地磁盘（D）下的一个工作文件夹 |
| 文件总量 | 约 35 万个，持续增长                                |
| 目录结构 | 最深约 15 层；存在大目录（如数千个图斑号命名的子文件夹，每个内几十张照片）     |
| 增长模式 | 随日常工作持续新增，偶尔有批量导入                           |

文件类型分布：

- **办公文档**：Excel (.xlsx/.xls)、Word (.docx/.doc)、PPT (.pptx/.ppt)、PDF（政策文档、审批文件）
- **图片**：.jpg/.jpeg/.png/.bmp 等（含手机拍照、外业照片、扫描件）
- **GIS 矢量**：Shapefile 全家族 (.shp/.shx/.dbf/.prj 等)、FileGDB (.gdb)、Personal GDB (.mdb)、GeoPackage (.gpkg)、KML/KMZ、ArcGIS 工程文件 (.mxd/.aprx)
- **GIS 栅格**：GeoTIFF (.tif/.tiff)、ERDAS (.img)、DEM、JP2 等
- **MapGIS**：工程文件 (.mpj)、点/线/区文件 (.wp/.wl/.wt)、属性 (.wat/.mat) 等
- **FME**：工作空间 (.fmw/.fmwt)、日志 (.ffs) 等
- **CAD**：AutoCAD (.dwg/.dxf)、MicroStation (.dgn)
- **测量数据**：点云 (.las/.laz)、GNSS 数据、控制测量数据

---

## 三、功能需求

### 3.1 阶段总览

| 阶段 | 核心目标 | 完成标志 | 预估周期 |
|------|----------|----------|----------|
| 第一阶段 | 文件扫描 + 元数据索引 + 关键词搜索 + 文件预览 | 能搜到文件、预览、直接打开 | 2-3 周 |
| 第二阶段 | 文档全文提取 + RAG 语义搜索 | 能用自然语言描述找到文件内容 | 3-4 周 |
| 第三阶段 | 接入 Ollama 本地模型 + AI 问答 | 能对话式查询知识库 | 2-3 周 |
| 第四阶段 | 离线盘联动 + 界面优化 + 高级功能 | 插拔盘逻辑完善，整体好用 | 2-3 周 |

---

### 3.2 第一阶段：文件扫描与搜索（MVP）

#### 3.2.1 文件扫描

**首次全量扫描：**

- 用户指定扫描根目录（如 `E:\` 或 `E:\工作文件`）
- 递归遍历所有子目录，提取每个文件的元数据
- 元数据字段：文件名、扩展名、文件大小、创建时间、修改时间、完整路径、父目录路径、目录层级深度
- 扫描进度实时展示（已扫描文件数 / 当前目录 / 预估剩余时间）
- 35 万文件首次扫描目标时间：5 分钟以内

**增量更新（快照模式）：**

- 采用"快照对比"机制：每次扫描生成当前文件系统快照（路径 + 修改时间 + 文件大小），与上一次快照对比，找出新增、删除、修改的文件
- 增量扫描目标时间：1 分钟以内
- 支持手动触发扫描
- 支持后台自动扫描（可配置间隔，默认每 30 分钟）
- 记录每次扫描的时间戳和变更统计（新增 N 个 / 删除 N 个 / 修改 N 个）

**扫描排除规则：**

- 默认排除：系统文件夹（`$RECYCLE.BIN`、`System Volume Information`）、临时文件（`~$*`、`.tmp`）
- 用户可自定义排除目录或文件类型
- 特殊目录处理：`.gdb` 后缀的文件夹视为 GIS 数据文件，记录为单条 gis_vector 类型记录，不递归扫描其内部

#### 3.2.2 搜索功能

**关键词搜索：**

- 搜索范围：文件名（主要）、文件路径
- 支持模糊匹配（输入"审批"能匹配"建设用地审批表.pdf"）
- 支持多关键词组合（空格分隔，AND 逻辑）
- 搜索响应时间目标：< 500ms（35万文件）

**筛选过滤：**

- 按文件类型筛选：文档（Word/Excel/PPT/PDF）、图片、GIS 矢量、GIS 栅格、MapGIS、FME、CAD、测量数据、全部
- 类型筛选以 tag 形式展示，可多选

**搜索结果展示：**

- 列表模式：文件名、文件类型图标、文件大小、修改时间、所在目录（显示末尾两级路径）
- 结果排序：默认按相关度，可切换为按修改时间、文件名、文件大小排序
- 分页加载或虚拟滚动（结果可能上万条）

#### 3.2.3 文件预览

- **图片**：缩略图预览（点击可放大查看）
- **PDF**：首页预览（嵌入式 PDF 查看器）
- **Office 文档**（Word/Excel/PPT）：显示文件基本信息（页数/Sheet数、文件大小），暂不做内容预览
- **GIS 矢量**（.shp/.gdb 等）：显示文件基本信息 + 关联文件列表（如 Shapefile 的 .shp/.shx/.dbf/.prj 作为一组展示）
- **GIS 栅格**（.tif/.img 等）：显示文件大小；GeoTIFF 可尝试生成缩略图
- **CAD**（.dwg/.dxf）：显示文件基本信息，暂不做图形预览
- **点云**（.las/.laz）：显示文件大小和基本信息
- **其他文件**：显示文件图标 + 元信息

#### 3.2.4 文件操作

- **打开文件**：调用系统默认程序打开（通过后端 `os.startfile()`）
- **打开所在目录**：在资源管理器中打开文件所在文件夹并选中该文件
- **复制文件路径**：一键复制完整文件路径到剪贴板
- **复制文件**：将文件复制到指定位置（方便发给同事）

#### 3.2.5 GIS/CAD 文件专项处理

**Shapefile 关联分组：**

- Shapefile 由多个同名文件组成（.shp/.shx/.dbf/.prj/.cpg 等），搜索时自动识别并作为一组展示
- 搜索结果中显示为一条记录，标注"Shapefile（含 N 个关联文件）"
- 打开/复制操作时，提供选项：打开主文件（.shp）或复制全套文件

**FileGDB 处理：**

- .gdb 实际上是文件夹，扫描时识别为 GIS 数据而非普通目录
- 不递归扫描 .gdb 内部文件

**GIS 工程文件关联：**

- .mxd / .aprx（ArcGIS 工程）、.qgs / .qgz（QGIS 工程）搜索时高亮展示
- 这些文件通常是项目入口，在搜索结果中优先排列

**CAD 文件：**

- .dwg / .dxf 按普通文件索引即可
- 打开操作调用系统关联程序（AutoCAD / 看图软件）

#### 3.2.6 首页仪表盘

- 文件总数统计
- 文件类型分布（饼图或柱状图）
- 最近扫描时间和变更统计
- 磁盘使用情况（已用/总容量）
- 快速搜索入口

---

### 3.3 第二阶段：全文检索与 RAG 语义搜索

#### 3.3.1 文档内容提取

- **PDF**（文本型）：pdfplumber 提取文字
- **Word**（.docx）：python-docx 提取文字
- **Excel**（.xlsx）：提取 Sheet 名和单元格文本
- **PPT**（.pptx）：提取幻灯片文本
- **扫描件/图片型 PDF**：使用 OCR（PaddleOCR）提取文字
- **手机拍照的审批文件**：同上 OCR 处理
- **GIS 矢量文件**：提取属性表字段名和字段值摘要（geopandas 读取 .dbf 属性表）
- **GIS 栅格文件**：提取元数据——坐标系、分辨率、波段数、范围（rasterio 读取）
- **CAD 文件**：提取图层名列表（ezdxf 读取 .dxf；.dwg 需转换后处理）
- 提取的文本存入 SQLite（`content_text` 字段）并建立全文索引（FTS5）
- 内容提取为后台任务，不阻塞搜索功能

#### 3.3.2 向量化与语义搜索

- 使用 ChromaDB 存储文档向量
- Embedding 模型：Ollama 本地运行（优先选中文模型，如 `bge-large-zh-v1.5`）
- 对提取的文本进行分块（chunk），每块 500-1000 字，有重叠
- 搜索时同时执行关键词搜索和语义搜索，合并排序结果
- 语义搜索结果展示匹配的文本片段（高亮关键词）

---

### 3.4 第三阶段：AI 问答

- 接入 Ollama 本地大模型（推荐 `qwen2.5` 系列）
- 基于 RAG 检索结果构建 Prompt，回答用户自然语言问题
- 对话界面：支持多轮对话，显示引用来源（点击可跳转到文件）
- 典型问答场景：
  - "XX项目的审批文件在哪？"
  - "去年关于土地政策的文件有哪些？"
  - "图斑号 XXX 的外业照片"
  - "包含某个地块编号的 Shapefile"
  - "哪些 CAD 文件里有某某图层？"
  - "坐标系是 CGCS2000 的栅格数据有哪些？"

---

### 3.5 第四阶段：离线盘联动与完善

#### 3.5.1 移动硬盘管理

- 首次配置：用户指定盘符和磁盘标识（卷标或序列号）
- 盘符变化检测：启动时检测已配置磁盘是否在线，若盘符变化则提示用户确认更新
- 在线状态：正常使用所有功能
- 离线状态：搜索功能正常（基于已有索引）；文件预览显示已缓存的缩略图/摘要（如有）；打开文件时提示"磁盘未连接，请插入移动硬盘"；状态栏显示磁盘离线图标

#### 3.5.2 界面优化

- 响应式布局适配不同屏幕
- 深色/浅色主题切换
- 键盘快捷键（`/` 聚焦搜索、`Enter` 打开文件、`Esc` 关闭预览）
- 搜索历史记录

---

## 四、技术架构

### 4.1 技术栈

| 层级 | 技术选型 | 说明 |
|------|----------|------|
| 后端框架 | Python + FastAPI | 异步支持好，性能高 |
| 文件索引数据库 | SQLite + FTS5 | 零配置，FTS5 做全文索引 |
| 向量数据库 | ChromaDB | 本地嵌入式，pip 安装 |
| 文档解析 | python-docx / openpyxl / pdfplumber / python-pptx | 各格式对应 |
| GIS 数据解析 | geopandas / rasterio / ezdxf / fiona | 第二阶段用 |
| OCR | PaddleOCR | 扫描件文字提取，中文效果好 |
| RAG 框架 | LangChain | 文件加载器 + 文本分块 |
| 本地模型 | Ollama | 管理本地 LLM 和 Embedding 模型 |
| 前端 | HTML + CSS + JavaScript | 不引入框架，降低复杂度 |
| 前端图表 | Chart.js | 仪表盘图表 |
| 平台 | Windows localhost | 本地运行，隐私安全 |

### 4.2 系统架构图

```
浏览器 (localhost:8000)
├── 搜索页面
├── 仪表盘
└── AI 问答（第三阶段）
        │
        │  HTTP API
        ▼
FastAPI 后端
├── 文件扫描模块 ──→ SQLite（元数据）
├── 搜索引擎模块 ──→ FTS5（全文索引）
└── RAG / AI 模块 ──→ ChromaDB（向量存储）
                          │
                          ▼
                   Ollama 本地模型
                   (Embedding / LLM)
```

### 4.3 数据库设计（第一阶段）

**文件索引主表：**

```sql
CREATE TABLE files (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    file_name         TEXT NOT NULL,           -- 文件名（含扩展名）
    file_name_no_ext  TEXT NOT NULL,           -- 文件名（不含扩展名）
    extension         TEXT,                     -- 扩展名（小写，如 .pdf）
    file_size         INTEGER,                  -- 文件大小（字节）
    created_time      TEXT,                     -- 创建时间（ISO 格式）
    modified_time     TEXT,                     -- 修改时间（ISO 格式）
    file_path         TEXT NOT NULL UNIQUE,     -- 完整路径
    parent_dir        TEXT,                     -- 父目录路径
    dir_depth         INTEGER,                  -- 目录层级深度
    file_type         TEXT,                     -- 分类，见下方映射
    shapefile_group   TEXT,                     -- Shapefile 分组标识
    disk_label        TEXT,                     -- 所属磁盘标识
    is_available      INTEGER DEFAULT 1,        -- 磁盘是否在线
    content_text      TEXT,                     -- 预留：提取的文本内容
    content_indexed   INTEGER DEFAULT 0,        -- 预留：是否已内容索引
    thumbnail_path    TEXT,                     -- 预留：缩略图路径
    created_at        TEXT DEFAULT (datetime('now')),
    updated_at        TEXT DEFAULT (datetime('now'))
);
```

file_type 取值：document / image / spreadsheet / presentation / gis_vector / gis_raster / mapgis / fme / cad / survey / archive / other

**全文搜索虚拟表：**

```sql
CREATE VIRTUAL TABLE files_fts USING fts5(
    file_name,
    file_name_no_ext,
    file_path,
    content='files',
    content_rowid='id'
);
```

**扫描记录表：**

```sql
CREATE TABLE scan_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_type   TEXT,         -- full / incremental
    root_path   TEXT,
    started_at  TEXT,
    finished_at TEXT,
    total_files INTEGER,
    added       INTEGER DEFAULT 0,
    deleted     INTEGER DEFAULT 0,
    modified    INTEGER DEFAULT 0,
    status      TEXT          -- running / completed / failed
);
```

**快照表（用于增量对比）：**

```sql
CREATE TABLE file_snapshots (
    file_path     TEXT PRIMARY KEY,
    modified_time TEXT,
    file_size     INTEGER,
    scan_id       INTEGER,
    FOREIGN KEY (scan_id) REFERENCES scan_logs(id)
);
```

**索引：**

```sql
CREATE INDEX idx_files_extension  ON files(extension);
CREATE INDEX idx_files_file_type  ON files(file_type);
CREATE INDEX idx_files_modified   ON files(modified_time);
CREATE INDEX idx_files_parent_dir ON files(parent_dir);
CREATE INDEX idx_files_shp_group  ON files(shapefile_group);
```

### 4.4 API 设计（第一阶段）

**扫描相关：**

```
POST  /api/scan/start          启动扫描（参数：root_path, scan_type）
GET   /api/scan/status          获取当前扫描进度
GET   /api/scan/logs            扫描历史记录
```

**搜索相关：**

```
GET   /api/search               搜索（参数：q, type, sort, page, size）
GET   /api/files/{id}           获取单个文件详情
GET   /api/files/{id}/preview   获取文件预览
```

**文件操作：**

```
POST  /api/files/{id}/open      用系统程序打开文件
POST  /api/files/{id}/open-dir  打开文件所在目录
POST  /api/files/{id}/copy      复制文件到指定路径
GET   /api/files/{id}/path      获取文件路径
```

**统计相关：**

```
GET   /api/stats/overview       仪表盘统计数据
GET   /api/stats/types          文件类型分布
```

**配置相关：**

```
GET   /api/config               获取配置
PUT   /api/config               更新配置
GET   /api/disk/status          磁盘在线状态
```

### 4.5 文件分类映射

```python
FILE_TYPE_MAP = {
    "document": [
        ".doc", ".docx", ".pdf", ".txt", ".rtf", ".odt", ".wps"
    ],
    "spreadsheet": [
        ".xls", ".xlsx", ".csv", ".ods", ".et"
    ],
    "presentation": [
        ".ppt", ".pptx", ".odp", ".dps"
    ],
    "image": [
        ".jpg", ".jpeg", ".png", ".gif", ".bmp",
        ".webp", ".raw", ".cr2", ".nef", ".heic"
    ],
    "gis_vector": [
        # Shapefile 系列
        ".shp", ".shx", ".dbf", ".prj", ".cpg", ".sbn", ".sbx",
        # Geodatabase
        ".gdb", ".mdb",                      # FileGDB / Personal GDB
        # 其他矢量格式
        ".gpkg", ".geojson",
        ".kml", ".kmz",
        # MapInfo
        ".tab", ".map", ".id",
        # ArcGIS 工程/图层文件
        ".mxd", ".aprx", ".lyr", ".lyrx",
        ".mpk", ".ppkx",
        # QGIS 工程文件
        ".qgs", ".qgz",
    ],
    "gis_raster": [
        ".tif", ".tiff", ".img",         # GeoTIFF / ERDAS
        ".dem", ".adf",                   # DEM / ArcInfo Grid
        ".ecw", ".sid", ".jp2",           # 压缩栅格
        ".nc", ".hdf", ".hdf5",           # 科学数据格式
        ".msi",                            # MapGIS 影像
    ],
    "mapgis": [
        ".mpj",                            # MapGIS 工程文件
        ".wp", ".wl", ".wt",              # MapGIS 点/线/区文件
        ".wat", ".mat",                    # MapGIS 属性
        ".clr", ".lib",                    # MapGIS 颜色库/符号库
    ],
    "fme": [
        ".fmw",                            # FME 工作空间
        ".fmwt",                           # FME 模板
        ".ffs",                            # FME 特征存储
    ],
    "cad": [
        ".dwg", ".dxf",                   # AutoCAD
        ".dgn",                            # MicroStation
    ],
    "survey": [
        ".las", ".laz",                    # 点云数据
        ".e57",                             # 三维扫描
        ".rinex",                           # GNSS 数据
        ".cor", ".obs",                     # 控制测量
    ],
    "archive": [
        ".zip", ".rar", ".7z", ".tar", ".gz"
    ],
    "other": []  # 兜底
}

# Shapefile 关联文件（搜索时将同目录同名文件视为一组）
SHAPEFILE_EXTENSIONS = {
    ".shp", ".shx", ".dbf", ".prj", ".cpg",
    ".sbn", ".sbx", ".xml"
}
```

---

## 五、性能要求

| 指标 | 目标 |
|------|------|
| 首次全量扫描（35万文件） | ≤ 5 分钟 |
| 增量扫描 | ≤ 1 分钟 |
| 关键词搜索响应 | ≤ 500ms |
| 搜索结果渲染（首屏） | ≤ 1 秒 |
| 内存占用（后端常驻） | ≤ 200MB |
| SQLite 数据库文件大小 | ≤ 100MB |

---

## 六、性能优化策略

### 6.1 扫描优化

- 使用 `os.scandir()` 替代 `os.walk()`（减少系统调用）
- 批量写入 SQLite（每 1000 条一次 commit）
- 扫描过程使用异步（asyncio + 线程池）避免阻塞 API 响应

### 6.2 搜索优化

- FTS5 全文索引（文件名搜索核心）
- 常用字段建索引（extension、file_type、modified_time）
- 搜索结果分页（默认每页 20 条）
- 前端虚拟滚动（大结果集场景）

### 6.3 快照对比优化

- 快照仅存储：文件路径 + 修改时间 + 文件大小
- 对比算法：新旧快照做集合运算（新增 = 新有旧无；删除 = 旧有新无；修改 = 路径相同但时间或大小不同）
- 数据库层面使用临时表实现高效对比

---

## 七、项目目录结构

```
file-manager/
├── backend/
│   ├── main.py                    # FastAPI 入口
│   ├── config.py                  # 配置管理
│   ├── database.py                # SQLite 连接和初始化
│   ├── models.py                  # 数据模型
│   ├── routers/
│   │   ├── scan.py                # 扫描相关 API
│   │   ├── search.py              # 搜索相关 API
│   │   ├── files.py               # 文件操作 API
│   │   ├── stats.py               # 统计 API
│   │   └── config_router.py       # 配置 API
│   ├── services/
│   │   ├── scanner.py             # 文件扫描服务
│   │   ├── indexer.py             # 索引管理服务
│   │   └── file_ops.py            # 文件操作服务
│   └── utils/
│       ├── file_types.py          # 文件类型映射
│       └── path_utils.py          # 路径处理工具
├── frontend/
│   ├── index.html                 # 主页面
│   ├── css/
│   │   └── style.css
│   ├── js/
│   │   ├── app.js                 # 主逻辑
│   │   ├── search.js              # 搜索模块
│   │   ├── preview.js             # 预览模块
│   │   └── dashboard.js           # 仪表盘模块
│   └── assets/
│       └── icons/                 # 文件类型图标
├── data/
│   └── file_index.db             # SQLite 数据库文件
├── config.json                    # 用户配置文件
├── requirements.txt
├── start.bat                      # Windows 一键启动
└── README.md
```

---

## 八、配置项

```json
{
    "scan_roots": [
        {
            "path": "E:\\",
            "disk_label": "工作数据盘",
            "disk_serial": "XXXXXXXX"
        }
    ],
    "exclude_dirs": [
        "$RECYCLE.BIN",
        "System Volume Information",
        ".Trash"
    ],
    "exclude_patterns": [
        "~$*",
        "*.tmp",
        "Thumbs.db",
        "desktop.ini"
    ],
    "auto_scan_interval_minutes": 30,
    "server_port": 8000,
    "thumbnail_cache_dir": "./data/thumbnails"
}
```

---

## 九、启动与部署

**安装步骤：**

```bash
# 1. 安装 Python 依赖
pip install -r requirements.txt

# 2. 启动服务（双击 start.bat 或手动运行）
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000

# 3. 浏览器访问
http://localhost:8000
```

**start.bat 内容：**

```batch
@echo off
echo 正在启动文件管理系统...
cd /d %~dp0
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

---

## 十、第一阶段验收标准

1. 能配置扫描路径，完成 35 万文件的全量扫描（≤ 5 分钟）
2. 能通过关键词搜索到目标文件（响应 ≤ 500ms）
3. 搜索结果列表展示文件信息，支持按类型筛选（含 GIS/MapGIS/FME/CAD 分类）
4. 点击文件能用系统程序直接打开
5. 点击"打开目录"能在资源管理器中定位文件
6. 图片类型能显示缩略图预览
7. Shapefile 搜索结果自动分组展示
8. 仪表盘显示文件统计信息
9. 增量扫描正常工作，能检测到新增/删除/修改
10. 系统稳定运行，内存占用合理

---

## 十一、后续阶段路标

| 阶段 | 关键技术点 | 前置条件 |
|------|------------|----------|
| 第二阶段 | pdfplumber + python-docx 提取文本；PaddleOCR 处理扫描件；geopandas 提取矢量属性表；rasterio 提取栅格元数据；ezdxf 提取 CAD 图层；FTS5 全文索引；ChromaDB + bge-large-zh 向量化 | 第一阶段稳定运行 2 周+ |
| 第三阶段 | Ollama 安装 qwen2.5 模型；LangChain RAG Pipeline；对话界面开发 | 第二阶段语义搜索可用 |
| 第四阶段 | 磁盘序列号识别（wmic）；盘符变更自动检测；缩略图缓存；UI 打磨 | 第三阶段 AI 问答可用 |

---

## 十二、风险与应对

| 风险 | 影响 | 应对策略 |
|------|------|----------|
| 35万文件扫描慢 | 用户体验差 | 多线程 + 批量写入 + 进度展示 |
| SQLite 大数据量查询慢 | 搜索卡顿 | FTS5 索引 + 合理分页 + WAL 模式 |
| 移动硬盘断开 | 功能不可用 | 离线索引可查 + 状态提示 |
| OCR 识别率低 | 扫描件搜索不准 | PaddleOCR 中文效果好；提供手动修正入口 |
| 内存占用过高 | 影响日常办公 | 流式处理 + 限制缓存大小 |
| .tif 文件分类歧义 | 普通图片和 GeoTIFF 都用 .tif | 第一阶段按所在目录上下文推断；第二阶段用 rasterio 检测地理坐标精确分类 |
| Shapefile 散落文件 | .shp/.dbf/.prj 分散存放匹配不上 | 仅对同目录同名文件做分组，异常记日志 |
