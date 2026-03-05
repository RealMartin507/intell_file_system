# 设置页面功能说明

## 概述

设置页面（Settings）已实现完整的配置管理界面，用户可以在此管理：
- **扫描路径** - 添加/删除扫描根目录
- **排除规则** - 管理排除目录和文件模式
- **自动扫描** - 启用/禁用自动扫描，设置扫描间隔
- **系统信息** - 查看数据库大小、索引文件数等

## 功能清单

### 1️⃣ 扫描路径管理

**位置**：设置页面顶部卡片

**功能**：
- 显示已配置的扫描路径列表
- 每条路径显示：路径、磁盘标签
- **添加路径**：点击"添加路径"按钮
  - 输入路径（如 `E:\`）
  - 输入磁盘标签（可选，如"工作数据盘"）
  - 确认添加
- **删除路径**：Hover 行项目，点击"删除"按钮，确认后删除

**数据结构**：
```json
{
  "scan_roots": [
    {
      "path": "E:\\",
      "disk_label": "工作数据盘",
      "disk_serial": ""
    }
  ]
}
```

---

### 2️⃣ 排除规则

#### 排除目录
**位置**：设置页面中部卡片

**功能**：
- 显示排除目录列表（默认：`$RECYCLE.BIN`、`System Volume Information`、`.Trash`）
- **添加目录**：点击"添加"按钮，输入目录名称（如 `node_modules`）
- **删除目录**：Hover 行项目，点击"删除"按钮

**数据结构**：
```json
{
  "exclude_dirs": [
    "$RECYCLE.BIN",
    "System Volume Information",
    ".Trash"
  ]
}
```

#### 排除文件模式
**位置**：设置页面中部卡片下方

**功能**：
- 显示文件模式列表（默认：`~$*`、`*.tmp`、`Thumbs.db`、`desktop.ini`）
- **添加模式**：点击"添加"按钮，输入通配符模式（如 `*.log`）
- **删除模式**：Hover 行项目，点击"删除"按钮

**数据结构**：
```json
{
  "exclude_patterns": [
    "~$*",
    "*.tmp",
    "Thumbs.db",
    "desktop.ini"
  ]
}
```

---

### 3️⃣ 自动扫描设置

**位置**：设置页面中部卡片

**功能**：
- **启用切换**：切换开关启用/禁用自动扫描
  - 启用状态：蓝色（#3B82F6）
  - 禁用状态：灰色（#D3D3D3）
- **扫描间隔**：输入框，单位分钟，范围 1-1440
  - 当切换关闭时，输入框禁用
  - 默认值：30 分钟
- **建议范围**：15-60 分钟

**数据结构**：
```json
{
  "auto_scan_interval_minutes": 30  // 0 表示禁用
}
```

---

### 4️⃣ 系统信息

**位置**：设置页面下部卡片

**显示内容**：
| 项目 | 内容 | 数据源 |
|------|------|--------|
| 应用版本 | 1.0.0 | 静态 |
| 索引文件总数 | 动态加载 | `/api/stats/overview` - `total_files` |
| 数据库文件大小 | 动态加载 | `/api/stats/overview` - `db_size_bytes`（自动转换为 MB/GB） |
| 配置文件路径 | config.json | 静态 |

**自动刷新**：切换到设置页面时自动加载系统信息

---

## 交互流程

### 用户操作流程
```
1. 点击侧边栏"设置"导航
   ↓
2. 设置页面加载（自动调用 Settings.init()）
   ↓
3. 加载当前配置（GET /api/config）
   ↓
4. 渲染 UI 和系统信息
   ↓
5. 用户编辑配置（添加/删除项目）
   ↓
6. 点击"保存设置"按钮
   ↓
7. 发送 PUT /api/config 请求
   ↓
8. 服务器保存配置文件
   ↓
9. 显示 Toast 成功提示
```

---

## API 接口

### GET /api/config
**功能**：获取当前配置

**响应示例**：
```json
{
  "scan_roots": [
    {
      "path": "E:\\",
      "disk_label": "工作数据盘",
      "disk_serial": ""
    }
  ],
  "exclude_dirs": ["$RECYCLE.BIN", "System Volume Information"],
  "exclude_patterns": ["~$*", "*.tmp"],
  "auto_scan_interval_minutes": 30,
  "server_port": 8000,
  "thumbnail_cache_dir": "./data/thumbnails"
}
```

### PUT /api/config
**功能**：更新配置

**请求体**：与 GET 响应相同的 JSON 结构

**响应**：
```json
{
  "status": "ok"
}
```

---

## 代码架构

### 文件结构
```
frontend/
├── index.html              # 主 HTML（已更新，导入 settings.js）
├── js/
│   ├── app.js             # 全局应用逻辑（已更新，监听视图切换）
│   ├── settings.js        # ⭐ 新增：设置页面核心逻辑
│   ├── dashboard.js       # 仪表盘
│   ├── search.js          # 搜索
│   └── preview.js         # 预览
└── css/
    └── style.css          # 样式（包含动画）
```

### Settings 对象结构
```javascript
const Settings = {
  currentConfig: null,      // 当前配置副本
  hasChanges: false,        // 是否有未保存的更改

  // 初始化
  async init()              // 加载配置并渲染 UI

  // 数据加载
  async loadConfig()        // GET /api/config
  async loadSystemInfo()    // 加载系统信息

  // 事件绑定
  bindEvents()             // 绑定所有交互事件
  bindToggleAnimation()    // 绑定切换开关动画

  // UI 渲染
  renderUI()                      // 渲染整个页面
  renderScanRootsList()           // 渲染路径列表
  renderExcludeDirsList()         // 渲染排除目录列表
  renderExcludePatternsList()     // 渲染排除模式列表

  // 模态框
  showAddScanRootModal()          // 添加路径对话框
  showAddExcludeDirModal()        // 添加排除目录对话框
  showAddExcludePatternModal()    // 添加排除模式对话框

  // CRUD 操作
  removeScanRoot(index)           // 删除路径
  removeExcludeDir(index)         // 删除排除目录
  removeExcludePattern(index)     // 删除排除模式

  // 数据保存
  async saveSettings()            // 保存所有设置
  resetUI()                       // 重置 UI（撤销未保存更改）

  // 工具函数
  formatNumber(num)               // 格式化数字
  formatBytes(bytes)              // 格式化字节（转换为 MB/GB）
  escapeHtml(text)                // HTML 转义
};
```

---

## 设计规范遵循

### 配色方案
- **卡片背景**：白色（#FFFFFF）
- **按钮**：
  - Primary（保存）：蓝色（#2563EB）
  - Secondary（取消）：灰色（#F4F2EE）
  - Danger（删除）：红色（#DC2626）
- **切换开关**：蓝色/灰色（见自动扫描部分）

### 间距
- 页面顶部 margin：`mb-6`
- 卡片内 padding：`p-5`
- 卡片间距：`gap-4` 或 `space-y-4`
- 列表行内 padding：`px-3 py-2.5`
- 底部操作栏：`pt-4` 和 `gap-3`

### 圆角
- 卡片、按钮、输入框：`rounded-lg` 或 `rounded-xl`

### 字体
- 标题：`text-2xl font-bold`
- 卡片标题：`text-sm font-semibold`
- 正文：`text-sm` 或 `text-xs`

### 动效
- Hover 状态：`transition-colors duration-150`
- 保存按钮加载：Spinner 动画 `animate-spin`

---

## 测试清单

- [ ] **加载配置**：切换到设置页面，验证配置是否正确加载
- [ ] **扫描路径**：
  - [ ] 添加新路径
  - [ ] 删除现有路径（带确认对话框）
  - [ ] 验证路径重复检查
- [ ] **排除规则**：
  - [ ] 添加排除目录
  - [ ] 添加排除模式
  - [ ] 删除规则（带确认对话框）
- [ ] **自动扫描**：
  - [ ] 切换开关启用/禁用
  - [ ] 修改扫描间隔
  - [ ] 验证禁用时输入框被禁用
- [ ] **系统信息**：
  - [ ] 验证版本号显示
  - [ ] 验证文件数格式化（带千分位）
  - [ ] 验证数据库大小格式化（B/KB/MB/GB）
- [ ] **保存功能**：
  - [ ] 点击"保存设置"
  - [ ] 验证 PUT /api/config 请求
  - [ ] 显示成功 Toast
  - [ ] 重新加载配置验证
- [ ] **取消功能**：
  - [ ] 修改后点击"取消"
  - [ ] 验证 UI 重置（未保存的更改丢弃）
- [ ] **Toast 通知**：
  - [ ] 添加成功/已删除/已保存：显示成功 Toast
  - [ ] 错误情况：显示错误 Toast
- [ ] **响应式设计**：
  - [ ] 在 1280×800 分辨率下完整可用
  - [ ] 长路径名称 truncate 处理

---

## 已知限制

1. **磁盘状态检测**：目前磁盘标签和磁盘序列号仅供参考，后端 `/api/disk/status` 还未实现在线状态检测
2. **自动扫描**：前端设置值，但后端尚未实现定时任务功能
3. **路径输入验证**：前端仅做字符串验证，后端应额外验证路径有效性
4. **批量操作**：暂不支持批量删除

---

## 后续增强方向

1. **磁盘检测**：实现 `/api/disk/status` 接口，在路径旁显示在线状态指示器
2. **自动扫描后台任务**：后端实现基于 `auto_scan_interval_minutes` 的定时扫描
3. **高级排除编辑**：提供可视化编辑器，支持正则表达式
4. **配置备份/恢复**：导出/导入配置文件
5. **搜索路径快速编辑**：在搜索页面快速调整路径或排除规则

---

## 调试建议

### 浏览器控制台
```javascript
// 查看当前配置
console.log(Settings.currentConfig);

// 手动加载配置
Settings.loadConfig().then(() => console.log('配置已加载'));

// 手动渲染 UI
Settings.renderUI();

// 查看 Toast
window.App.showToast('测试消息', 'success');
```

### 后端测试（curl）
```bash
# 获取配置
curl http://localhost:8000/api/config

# 更新配置
curl -X PUT http://localhost:8000/api/config \
  -H "Content-Type: application/json" \
  -d '{
    "scan_roots": [{"path": "E:\\", "disk_label": "测试", "disk_serial": ""}],
    "exclude_dirs": ["$RECYCLE.BIN"],
    "exclude_patterns": ["*.tmp"],
    "auto_scan_interval_minutes": 30,
    "server_port": 8000,
    "thumbnail_cache_dir": "./data/thumbnails"
  }'

# 获取统计信息
curl http://localhost:8000/api/stats/overview
```

---

## 总结

设置页面实现了完整的配置管理界面，用户可以通过直观的 UI 管理所有关键参数。所有修改都持久化保存到 `config.json`，后端会在启动时加载。
