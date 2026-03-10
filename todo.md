# 扫描优化 & 架构调整 Todo

> 项目：本地文件智能管理系统（FastAPI + SQLite WAL + FTS5 + Vanilla JS）
> Python：`C:/Users/mmm/.conda/envs/file-manager/python.exe`
> 目标：支持百万级文件，扫描速度达到 WizTree 级别

---

## 执行顺序

```
第一阶段（稳定性，必须先做）
  Task 1 → Task 2 → Task 3

第二阶段（速度飞跃，按优先级）
  Task 4 → Task 5 → Task 6（可选）
```

---

## 第一阶段：架构稳定性修复

### ✅ Task 1：增量扫描改为 DB 侧 SQL JOIN 对比 ✅

**问题**：`_run_incremental_scan()` 把全部 `file_snapshots` 加载进 Python dict 做集合对比，百万文件直接 OOM。
**目标**：改为临时表 + SQL JOIN，全程不把快照加载进内存。

**执行提示词（直接粘贴）**：

```
项目：本地文件智能管理系统，FastAPI + SQLite，Python C:/Users/mmm/.conda/envs/file-manager/python.exe

修改 backend/services/scanner.py 的增量扫描逻辑，解决百万文件 OOM 问题：

当前问题：_run_incremental_scan() 里把 file_snapshots 全表加载进内存 dict，然后 Python 集合对比找新增/删除/修改，百万文件会 OOM。

改造目标：改为数据库侧操作，全程不把快照加载进内存：
1. 扫描文件系统时，把新快照批量写入临时表 temp_scan_snapshot（字段：path TEXT, mtime REAL, size INTEGER）
2. 写完后用 SQL 三条语句找差异：
   - 新增：SELECT path FROM temp_scan_snapshot WHERE path NOT IN (SELECT path FROM file_snapshots)
   - 删除：SELECT path FROM file_snapshots WHERE path NOT IN (SELECT path FROM temp_scan_snapshot)
   - 修改：SELECT t.path FROM temp_scan_snapshot t JOIN file_snapshots s ON t.path=s.path WHERE t.mtime!=s.mtime OR t.size!=s.size
3. 差异处理完后用 temp_scan_snapshot 替换 file_snapshots（DELETE + INSERT 或 DROP + RENAME）
4. 保持现有 ScanState 进度字段（added/deleted/modified/scanned_count/current_dir）更新逻辑不变
5. 保持 start_incremental_scan() 函数签名不变，无快照时自动回退全量扫描的逻辑不变

database.py 中 get_db() 返回 sqlite3.Connection，WAL 模式，files 表有 id/path/name/size/mtime 等 18 个字段。
```

---

### ✅ Task 2：FTS5 改为增量同步，不再全量 rebuild ✅

**问题**：百万记录全量 `rebuild` 需数分钟，期间搜索全部返回空结果。
**目标**：插入/删除 `files` 时同步维护 `files_fts`，消除 rebuild。

**执行提示词（直接粘贴）**：

```
项目：本地文件智能管理系统，FastAPI + SQLite FTS5，Python C:/Users/mmm/.conda/envs/file-manager/python.exe

修改 backend/services/scanner.py 和 backend/database.py，将 FTS5 维护方式从"扫描结束后全量 rebuild"改为增量同步：

背景：
- files_fts 是 content='files' 的 FTS5 虚拟表，tokenizer='unicode61'，定义在 database.py init_db() 中
- 当前逻辑：扫描完所有文件后执行 INSERT INTO files_fts(files_fts) VALUES('rebuild')
- 问题：百万记录 rebuild 需要几分钟，期间搜索不可用

改造要求：
1. 全量扫描时：清空 files 同时执行 DELETE FROM files_fts，然后每批插入 files 后同步插入 files_fts（INSERT INTO files_fts(rowid, name, path, file_type) SELECT id, name, path, file_type FROM files WHERE id IN (...)）
2. 增量扫描时：
   - 新增文件插入 files 后同步插入 files_fts
   - 删除文件时先 DELETE FROM files_fts WHERE rowid=? 再删 files
   - 修改文件时先删 files_fts 旧行再插新行
3. 去掉扫描末尾所有的 rebuild 调用
4. 在 database.py 中封装 fts_insert(conn, file_id)、fts_delete(conn, file_id) 两个辅助函数供 scanner.py 调用

files_fts 索引的字段只需 name、path、file_type（不需要全部 18 个字段）。
```

---

### ✅ Task 3：批量提交粒度调大 + SQLite 缓存扩容 ✅

**问题**：`_BATCH_SIZE=1000` 产生过多 commit 事务；32MB 缓存不够百万级查询。

**执行提示词（直接粘贴）**：

```
项目：本地文件智能管理系统，FastAPI + SQLite

做两处简单修改：

1. backend/services/scanner.py 第 42 行附近：
   将 _BATCH_SIZE = 1000 改为 _BATCH_SIZE = 20000

2. backend/database.py 的 init_db() 中 SQLite pragma 配置：
   将 cache_size 从当前值改为 -262144（即 256MB，负数表示 KB 单位）
   如果有 page_size pragma，保持不变
   如果没有 mmap_size，新增 PRAGMA mmap_size = 536870912（512MB）

改完后验证语法正确即可，不需要运行测试。
```

---

## 第二阶段：扫描速度飞跃

### ✅ Task 4：USN Journal 事件驱动增量监控 ✅

**目标**：文件变更后毫秒级感知，彻底替代"定时扫描 + 快照对比"模式。
**新文件**：`backend/services/usn_monitor.py`

**执行提示词（直接粘贴）**：

```
项目：本地文件智能管理系统，FastAPI + SQLite，Windows NTFS 环境
Python：C:/Users/mmm/.conda/envs/file-manager/python.exe

新增 backend/services/usn_monitor.py，实现 NTFS USN Journal 变更监控：

功能需求：
1. 用 ctypes 调用 Windows API（DeviceIoControl + FSCTL_READ_USN_JOURNAL）监听 NTFS 卷的变更日志
2. 每个需要监控的卷（从 config.json scan_roots 提取盘符）独立开一个监控线程
3. 捕获到 FILE_ACTION_ADDED / MODIFIED / REMOVED 事件后：
   - ADDED/MODIFIED：读取文件元数据，更新 files 表和 files_fts 表（复用 scanner.py 的文件记录写入逻辑）
   - REMOVED：从 files 表和 files_fts 表删除对应记录
4. 只处理在 scan_roots 路径下的文件，跳过排除规则匹配的路径（复用 scanner.py 的 _should_exclude 逻辑）
5. 对外接口：start_monitoring(roots: list[str]) → stop_monitoring() → get_status() → dict
6. 在 ThreadPoolExecutor 线程中运行，不阻塞 FastAPI 主线程
7. 监控线程异常时自动重启（最多重试 3 次）

同时修改 backend/routers/scan.py，新增三个端点：
- POST /api/scan/monitor/start   body: {"roots": ["C:\\", "E:\\"]}
- POST /api/scan/monitor/stop
- GET  /api/scan/monitor/status  返回 {running: bool, watching_volumes: list, events_processed: int}

关键文件：
- backend/database.py：get_db() 返回 sqlite3.Connection
- backend/config.py：get_config() 返回配置，scan_roots 是 [{path, disk_label, ...}] 列表
- backend/utils/file_types.py：get_file_type(path) 识别文件类型
- backend/services/scanner.py：_should_exclude(path, config) 排除规则，_build_file_record(path) 构建文件记录
```

---

### ✅ Task 5：MFT 直读全量扫描（WizTree 同级）✅

**目标**：百万文件初次全扫从"数十分钟"降到"5~15 秒"。
**新文件**：`backend/services/mft_scanner.py`

**执行提示词（直接粘贴）**：

```
项目：本地文件智能管理系统，FastAPI + SQLite，Windows NTFS 环境
Python：C:/Users/mmm/.conda/envs/file-manager/python.exe

新增 backend/services/mft_scanner.py，实现 NTFS MFT 直读：

功能需求：
1. 用 ctypes 直接读取 NTFS MFT（打开 \\.\C: 卷句柄 + DeviceIoControl FSCTL_ENUM_USN_DATA）
2. 枚举卷内所有文件（跳过目录和系统隐藏文件），提取：路径、文件名、大小、修改时间
3. 对外接口：scan_volume(drive_letter: str, batch_callback: callable, batch_size: int = 20000)
   - batch_callback 接收 list[dict]，每个 dict 与 scanner.py 的文件记录格式相同
   - 返回 (total_count: int, elapsed_seconds: float)
4. 权限检测：调用前检测是否有管理员权限；无权限时抛出 PermissionError（调用方负责 fallback）
5. 错误处理：卷不存在、非 NTFS 格式等情况抛出明确异常

同时修改 backend/services/scanner.py 的 _run_full_scan()：
- 尝试 import mft_scanner 并调用 scan_volume()
- 成功 → 走 MFT 快速通道，batch_callback 内复用现有的批量写入 DB 逻辑
- 失败（PermissionError 或非 NTFS）→ 静默 fallback 到现有 os.scandir() 流程
- 在 ScanState 新增 scan_method: str 字段（值为 "mft" 或 "scandir"），供前端显示

关键文件：
- backend/services/scanner.py：_BATCH_SIZE、ScanState、批量写入 files 表的逻辑
- backend/database.py：get_db()、files 表 18 个字段定义
- backend/utils/file_types.py：get_file_type(path) → str
```

---

### ✅ Task 6：Everything SDK 可选集成（非必须，按需做）

**目标**：检测到 Everything 在运行时，走毫秒级查询通道替代扫描。
**新文件**：`backend/services/everything_scanner.py`

**执行提示词（直接粘贴）**：

```
项目：本地文件智能管理系统，FastAPI + SQLite，Windows 环境
Python：C:/Users/mmm/.conda/envs/file-manager/python.exe

新增 backend/services/everything_scanner.py，集成 Everything IPC：

功能需求：
1. 通过 ctypes 加载 Everything SDK DLL（Everything64.dll / Everything32.dll），尝试常见路径：
   - C:/Program Files/Everything/
   - C:/Program Files (x86)/Everything/
   - 未找到时标记不可用
2. is_available() → bool：检测 Everything 进程是否在运行（FindWindow "EVERYTHING"）
3. get_all_files(roots: list[str], excludes: list[str]) → Iterator[list[dict]]
   - 用 Everything_SetSearchW 发送查询，Everything_QueryW 执行，Everything_GetResultFullPathNameW 取路径
   - 按 roots 过滤，按 excludes 过滤
   - 以 20000 条为一批 yield list[dict]，dict 格式与 scanner.py 文件记录相同（name/path/size/mtime/file_type）

同时修改：
1. backend/services/scanner.py 的 _run_full_scan()：
   - 检查 config.use_everything 且 everything_scanner.is_available() 时走 Everything 通道
   - ScanState.scan_method 字段增加 "everything" 可选值
2. backend/routers/scan.py 新增：
   - GET /api/scan/everything/status → {available: bool, version: str|null}
3. frontend/js/settings.js 设置页面新增"使用 Everything 加速扫描"开关：
   - 调用 /api/scan/everything/status 显示是否可用（不可用时灰显并提示"需安装 Everything"）
   - 开关状态通过 PUT /api/config 保存 use_everything 字段
   - UI 风格沿用已有的 Tailwind + Lucide 图标规范

关键文件：
- backend/config.py：get_config() / reload_config()，config.json 结构
- frontend/js/settings.js：已有的开关组件写法（参考自动扫描开关的实现）
```

---

## 验收标准

| Task   | 验收命令 / 检查点                                                                    |
| ------ | ------------------------------------------------------------------------------------ |
| Task 1 | 增量扫描时 `htop`/任务管理器内存不随文件数线性增长                                   |
| Task 2 | 扫描过程中 `/api/search?q=test` 始终有返回（不再因 rebuild 阻塞）                    |
| Task 3 | `scanner.py` 中 `_BATCH_SIZE == 20000`，`database.py` cache_size pragma 值为 -262144 |
| Task 4 | 新建一个文件后 30 秒内 `/api/search?q=文件名` 能找到，不触发手动扫描                 |
| Task 5 | 全量扫描日志显示 `scan_method: mft`，10 万文件扫描 < 30 秒                           |
| Task 6 | Everything 运行时 `/api/scan/everything/status` 返回 `available: true`               |
