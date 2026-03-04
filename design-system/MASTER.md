# 本地文件智能管理系统 — 设计系统 MASTER

> **版本**：1.0.0 | **技术栈**：原生 HTML + Tailwind CSS CDN + 原生 JS
> **风格基调**：Data-Dense Dashboard × Minimalism — 专业、克制、温暖、信息密度适中
> **参考气质**：claude.ai 奶油色温暖感 + VS Code 文件管理器的专业效率感

---

## 目录

1. [配色方案](#1-配色方案)
2. [字体方案](#2-字体方案)
3. [间距与圆角规范](#3-间距与圆角规范)
4. [组件规范](#4-组件规范)
5. [布局规范](#5-布局规范)
6. [图标规范](#6-图标规范)
7. [动效规范](#7-动效规范)
8. [Tailwind 配置扩展](#8-tailwind-配置扩展)
9. [交付前自查清单](#9-交付前自查清单)

---

## 1. 配色方案

### 1.1 色彩哲学

整体取 claude.ai 的「温暖米白 + 深灰文字」气质，拒绝纯白纯黑的刺眼对比。主色从工程蓝（#1E40AF）调整为更克制的温暖石青色，让数据界面在长时间使用中不产生视觉疲劳。

### 1.2 基础色板（浅色主题）

| Token 名称              | Hex       | Tailwind 近似值          | 用途说明                         |
|------------------------|-----------|--------------------------|----------------------------------|
| `--color-bg-base`      | `#FAF9F7` | `stone-50` 调暖           | 页面主背景（米白/奶油白）         |
| `--color-bg-surface`   | `#F4F2EE` | `stone-100`              | 卡片、侧边栏背景                 |
| `--color-bg-elevated`  | `#FFFFFF` | `white`                  | 悬浮卡片、模态框、输入框背景      |
| `--color-bg-hover`     | `#EDE9E3` | `stone-200`              | hover 状态背景                   |
| `--color-bg-active`    | `#E4DFD8` | `stone-300`              | 选中/active 状态背景             |
| `--color-border`       | `#DDD8D0` | `stone-200` 深一档        | 普通分割线、卡片边框              |
| `--color-border-focus` | `#A67C52` | `amber-700` 调深          | focus 状态边框（温暖棕）         |
| `--color-text-primary` | `#2D2926` | `stone-900`              | 主要文本（深暖灰，非纯黑）        |
| `--color-text-secondary`| `#6B6560`| `stone-500`              | 次要文本、描述、标签              |
| `--color-text-muted`   | `#9E9892` | `stone-400`              | 占位符、禁用状态                 |
| `--color-text-inverse` | `#FAF9F7` | `stone-50`               | 深色背景上的文字                 |

### 1.3 主色（Primary — 石青蓝）

呼应测绘/地理信息的专业感，选用带绿调的深蓝（石青色系），而非纯冷蓝。

| Token 名称                | Hex       | 用途                      |
|--------------------------|-----------|---------------------------|
| `--color-primary-50`     | `#EFF6FF` | 极淡主色背景（标签底色）    |
| `--color-primary-100`    | `#DBEAFE` | 浅主色（hover 辅助）        |
| `--color-primary-500`    | `#3B82F6` | 中间态                    |
| `--color-primary-600`    | `#2563EB` | **主操作色**（按钮、链接） |
| `--color-primary-700`    | `#1D4ED8` | 主色 hover/active         |
| `--color-primary-900`    | `#1E3A8A` | 深主色（侧边栏选中文字）   |

### 1.4 强调色（Accent — 温暖琥珀）

用于核心 CTA、高亮徽章、重要计数，与米白底色形成温暖呼应。

| Token 名称               | Hex       | 用途                     |
|-------------------------|-----------|--------------------------|
| `--color-accent-400`    | `#FBBF24` | 徽章高亮、星标文件        |
| `--color-accent-500`    | `#F59E0B` | **CTA 按钮**、警告提示    |
| `--color-accent-600`    | `#D97706` | 强调色 hover              |
| `--color-accent-800`    | `#92400E` | 深强调文字（标签文字）    |

### 1.5 语义色（Semantic）

| 语义    | 颜色名称 | Hex       | Tailwind          | 用途                    |
|--------|---------|-----------|-------------------|-------------------------|
| 成功   | 绿      | `#16A34A` | `green-600`       | 扫描完成、文件正常在线   |
| 警告   | 橙      | `#EA580C` | `orange-600`      | 文件离线、扫描警告       |
| 错误   | 红      | `#DC2626` | `red-600`         | 操作失败、扫描错误       |
| 信息   | 蓝      | `#2563EB` | `blue-600`        | 提示信息、进度状态       |
| 中性   | 石灰    | `#6B6560` | `stone-500`       | 次要状态、普通标签       |

### 1.6 文件类型分类色（File Type Colors）

每种文件类型对应独立色彩语义，用于文件列表左侧色条、图标背景、类型标签。

| 文件类型         | 分类名称        | 色彩        | Hex       | Tailwind 近似       | 图标参考             |
|----------------|----------------|------------|-----------|---------------------|---------------------|
| GIS 矢量数据    | `gis_vector`   | 翠绿        | `#059669` | `emerald-600`       | 多边形线条图标       |
| GIS 栅格数据    | `gis_raster`   | 蓝紫        | `#7C3AED` | `violet-700`        | 网格/像素图标        |
| MapGIS 文件    | `mapgis`        | 深蓝绿      | `#0E7490` | `cyan-700`          | 地图瓦片图标         |
| FME 工作台     | `fme`           | 橙红        | `#C2410C` | `orange-700`        | 管道/流程图标        |
| 测量/勘察数据   | `survey`        | 棕土黄      | `#A16207` | `yellow-700`        | 测量仪器图标         |
| CAD 文件       | `cad`           | 深蓝        | `#1D4ED8` | `blue-700`          | 工程制图图标         |
| 图片文件       | `image`          | 品红        | `#BE185D` | `pink-700`          | 图片/相机图标        |
| 文档文件       | `document`       | 靛蓝        | `#4338CA` | `indigo-700`        | 文档图标             |
| 表格文件       | `spreadsheet`    | 草绿        | `#15803D` | `green-700`         | 表格图标             |
| 视频文件       | `video`          | 玫红        | `#9D174D` | `pink-800`          | 播放器图标           |
| 音频文件       | `audio`          | 紫          | `#6D28D9` | `violet-700`        | 波形图标             |
| 压缩包         | `archive`        | 暖棕        | `#92400E` | `amber-800`         | 压缩箱图标           |
| 其他           | `other`          | 石灰        | `#57534E` | `stone-600`         | 通用文件图标         |

### 1.7 深色主题预留（Dark Mode Token 映射）

```css
/* 在 HTML 根元素添加 class="dark" 即可切换 */
.dark {
  --color-bg-base:      #1C1917;   /* stone-900 */
  --color-bg-surface:   #292524;   /* stone-800 */
  --color-bg-elevated:  #3A3632;   /* stone-750 */
  --color-bg-hover:     #44403C;   /* stone-700 */
  --color-border:       #57534E;   /* stone-600 */
  --color-text-primary: #F5F0EB;   /* stone-100 */
  --color-text-secondary:#A8A29E;  /* stone-400 */
  --color-text-muted:   #78716C;   /* stone-500 */
}
```

---

## 2. 字体方案

### 2.1 字体设计决策

中文界面优先使用系统字体栈，避免依赖 CDN 加载中文字体（单字体包 10MB+，严重影响首屏）。英文标题/数字/代码 使用 Google Fonts 按需加载。

### 2.2 字体栈定义

```css
/* ===== 正文（中英混排）===== */
--font-body: -apple-system, "PingFang SC", "Hiragino Sans GB",
             "Microsoft YaHei UI", "Microsoft YaHei",
             "Source Han Sans SC", "Noto Sans SC",
             "Segoe UI", system-ui, sans-serif;

/* ===== 数字 / 统计数据（保持等宽精准）===== */
--font-mono: "JetBrains Mono", "Fira Code", "Cascadia Code",
             "Consolas", "SF Mono", monospace;

/* ===== 英文界面标题（装饰性）===== */
--font-display: "Inter", "Segoe UI", system-ui, sans-serif;
```

### 2.3 Google Fonts 引入（仅英文/数字）

```html
<!-- 在 <head> 中引入 —— 仅 JetBrains Mono 用于数字显示 -->
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
```

### 2.4 字体尺寸规范

| 级别         | 尺寸       | 行高   | 字重   | 用途                         |
|-------------|-----------|--------|--------|------------------------------|
| `text-xs`   | 11px      | 1.4    | 400    | 文件扩展名、时间戳、角标       |
| `text-sm`   | 13px      | 1.5    | 400    | 列表副文本、标签、辅助说明     |
| `text-base` | 15px      | 1.6    | 400    | **主要正文**（中文阅读最优）   |
| `text-lg`   | 17px      | 1.5    | 500    | 列表主文件名、卡片标题         |
| `text-xl`   | 20px      | 1.4    | 600    | 区块标题、面板大标题           |
| `text-2xl`  | 24px      | 1.3    | 700    | 统计数字（仪表盘 KPI）         |
| `text-3xl`  | 30px      | 1.2    | 700    | 仪表盘主要大数字               |
| `text-4xl`  | 36px      | 1.1    | 800    | 首屏超大统计数字               |

> **中文排版关键规则**：
> - 正文 `line-height: 1.6`（中文比英文需要更大行高）
> - 中英文混排时汉字与字母/数字之间自动添加半角空格（推荐前端配合 pangu.js）
> - 标题字重用 600-700，正文不超过 500

---

## 3. 间距与圆角规范

### 3.1 间距系统（基于 4px 网格）

| Token           | px   | Tailwind    | 适用场景                     |
|----------------|------|-------------|------------------------------|
| `--space-1`    | 4px  | `p-1`       | 紧凑内边距（图标内衬）        |
| `--space-2`    | 8px  | `p-2`       | 列表行内边距、小标签          |
| `--space-3`    | 12px | `p-3`       | 按钮 padding-y、卡片内衬      |
| `--space-4`    | 16px | `p-4`       | 卡片标准内边距                |
| `--space-5`    | 20px | `p-5`       | 面板区块内边距                |
| `--space-6`    | 24px | `p-6`       | 大面板、内容区内边距          |
| `--space-8`    | 32px | `p-8`       | 页面级边距                   |
| `--space-12`   | 48px | `p-12`      | 模态框内边距                  |
| `--space-16`   | 64px | `p-16`      | 首屏顶部空间                  |

### 3.2 组件内部间距速查

```
文件列表行：   px-4 py-2.5（水平 16px，垂直 10px）
搜索结果卡片： p-4（16px 全向）
KPI 统计卡：   p-5（20px 全向）
模态框内容区： px-6 py-5
侧边栏导航项： px-3 py-2（水平 12px，垂直 8px）
```

### 3.3 圆角规范

| Token              | 值    | Tailwind        | 适用场景                     |
|-------------------|-------|-----------------|------------------------------|
| `--radius-sm`     | 4px   | `rounded`       | 标签、小徽章、文件类型 badge  |
| `--radius-md`     | 8px   | `rounded-lg`    | 按钮、输入框、小卡片          |
| `--radius-lg`     | 12px  | `rounded-xl`    | 内容卡片、面板、搜索框        |
| `--radius-xl`     | 16px  | `rounded-2xl`   | 模态框、大卡片                |
| `--radius-full`   | 9999px| `rounded-full`  | 头像、状态指示器、圆形按钮    |

> **原则**：侧边栏导航项选中态用 `rounded-lg`（8px），卡片用 `rounded-xl`（12px），整体避免过于方正或过于圆润。

### 3.4 阴影规范

```css
/* 不使用 Tailwind 默认阴影，改用温暖中性色调 */
--shadow-sm:  0 1px 2px rgba(45,41,38,0.06);
--shadow-md:  0 4px 12px rgba(45,41,38,0.08), 0 1px 3px rgba(45,41,38,0.04);
--shadow-lg:  0 8px 24px rgba(45,41,38,0.10), 0 2px 6px rgba(45,41,38,0.05);
--shadow-xl:  0 16px 40px rgba(45,41,38,0.12), 0 4px 12px rgba(45,41,38,0.06);
/* 模态框遮罩阴影 */
--shadow-modal: 0 20px 60px rgba(45,41,38,0.20);
```

---

## 4. 组件规范

### 4.1 按钮（Button）

#### 主要按钮（Primary）— 扫描、确认操作
```html
<button class="
  inline-flex items-center gap-2
  px-4 py-2 rounded-lg
  bg-blue-600 hover:bg-blue-700 active:bg-blue-800
  text-white text-sm font-medium
  transition-colors duration-150
  focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2
  disabled:opacity-50 disabled:cursor-not-allowed
  cursor-pointer
">
  <svg ...></svg>
  开始扫描
</button>
```

#### 次要按钮（Secondary）— 辅助操作
```html
<button class="
  inline-flex items-center gap-2
  px-4 py-2 rounded-lg
  bg-stone-100 hover:bg-stone-200 active:bg-stone-300
  text-stone-700 text-sm font-medium border border-stone-200
  transition-colors duration-150
  focus:outline-none focus:ring-2 focus:ring-stone-400 focus:ring-offset-2
  cursor-pointer
">
  打开文件夹
</button>
```

#### 幽灵按钮（Ghost）— 列表行操作
```html
<button class="
  inline-flex items-center gap-1.5
  px-3 py-1.5 rounded-md
  text-stone-500 hover:text-stone-800 hover:bg-stone-100
  text-sm transition-colors duration-150
  cursor-pointer
">
  在文件夹中显示
</button>
```

#### 危险按钮（Danger）— 删除/清空
```html
<button class="
  inline-flex items-center gap-2
  px-4 py-2 rounded-lg
  bg-red-600 hover:bg-red-700
  text-white text-sm font-medium
  transition-colors duration-150
  cursor-pointer
">
  清空数据库
</button>
```

#### 图标按钮（Icon Only）
```html
<button
  aria-label="刷新"
  class="
    p-2 rounded-lg
    text-stone-500 hover:text-stone-800 hover:bg-stone-100
    transition-colors duration-150
    focus:outline-none focus:ring-2 focus:ring-stone-400
    cursor-pointer
  "
>
  <svg class="w-4 h-4" ...></svg>
</button>
```

#### 加载状态（Loading）
```html
<button disabled class="... opacity-75 cursor-not-allowed">
  <svg class="w-4 h-4 animate-spin" ...><!-- spinner --></svg>
  扫描中...
</button>
```

---

### 4.2 输入框（Input）

#### 搜索主输入框（核心 UI，需突出）
```html
<div class="relative">
  <!-- 搜索图标 -->
  <div class="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none">
    <svg class="w-5 h-5 text-stone-400" ...></svg>
  </div>
  <input
    type="search"
    placeholder="搜索文件名、路径、扩展名..."
    class="
      w-full pl-12 pr-4 py-3 rounded-xl
      bg-white border border-stone-200
      text-base text-stone-800 placeholder-stone-400
      shadow-sm
      focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500
      transition-shadow duration-200
    "
  >
  <!-- 清除按钮（有内容时显示） -->
  <button class="absolute inset-y-0 right-0 pr-4 flex items-center cursor-pointer">
    <svg class="w-4 h-4 text-stone-400 hover:text-stone-600" ...></svg>
  </button>
</div>
```

#### 普通文本输入框
```html
<input
  type="text"
  class="
    w-full px-3 py-2 rounded-lg
    bg-white border border-stone-200
    text-sm text-stone-800 placeholder-stone-400
    focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500
    transition-colors duration-150
  "
>
```

#### 下拉选择框（文件类型过滤）
```html
<select class="
  px-3 py-2 pr-8 rounded-lg
  bg-white border border-stone-200
  text-sm text-stone-700
  focus:outline-none focus:ring-2 focus:ring-blue-500
  cursor-pointer appearance-none
  bg-[url('data:image/svg+xml,...')] bg-no-repeat bg-right-3
">
  <option value="">所有类型</option>
  <option value="gis_vector">GIS 矢量</option>
  ...
</select>
```

---

### 4.3 卡片（Card）

#### 统计卡片（KPI Card — 仪表盘）
```html
<div class="
  bg-white rounded-xl p-5
  border border-stone-200
  shadow-[0_1px_2px_rgba(45,41,38,0.06)]
  hover:shadow-[0_4px_12px_rgba(45,41,38,0.08)]
  transition-shadow duration-200
">
  <div class="flex items-center justify-between mb-3">
    <span class="text-sm text-stone-500 font-medium">总文件数</span>
    <!-- 文件类型图标 -->
    <div class="w-8 h-8 rounded-lg bg-blue-50 flex items-center justify-center">
      <svg class="w-4 h-4 text-blue-600" ...></svg>
    </div>
  </div>
  <p class="text-3xl font-bold text-stone-900 font-mono tabular-nums">352,814</p>
  <p class="text-xs text-stone-400 mt-1">较上次扫描 +1,234</p>
</div>
```

#### 搜索结果文件卡片
```html
<div class="
  group flex items-center gap-3
  px-4 py-3 rounded-xl
  bg-white border border-stone-100
  hover:border-stone-200 hover:bg-stone-50
  hover:shadow-[0_2px_8px_rgba(45,41,38,0.07)]
  transition-all duration-150
  cursor-pointer
">
  <!-- 左侧类型色条 -->
  <div class="w-1 h-10 rounded-full bg-emerald-500 flex-shrink-0"></div>
  <!-- 文件图标 -->
  <div class="w-9 h-9 rounded-lg bg-emerald-50 flex items-center justify-center flex-shrink-0">
    <svg class="w-5 h-5 text-emerald-600" ...></svg>
  </div>
  <!-- 文件信息 -->
  <div class="flex-1 min-w-0">
    <p class="text-sm font-medium text-stone-800 truncate group-hover:text-blue-600 transition-colors">
      roads_2024.shp
    </p>
    <p class="text-xs text-stone-400 truncate mt-0.5">
      E:\GIS\Projects\城市交通\roads_2024.shp
    </p>
  </div>
  <!-- 右侧元数据 -->
  <div class="flex-shrink-0 text-right">
    <span class="text-xs text-stone-400">128 MB</span>
    <p class="text-xs text-stone-400 mt-0.5">2024-01-15</p>
  </div>
  <!-- 操作按钮组（hover 显示） -->
  <div class="flex-shrink-0 opacity-0 group-hover:opacity-100 transition-opacity duration-150 flex gap-1">
    <button aria-label="打开文件" class="p-1.5 rounded-md hover:bg-stone-100 cursor-pointer text-stone-400 hover:text-stone-700">
      <svg class="w-4 h-4" ...></svg>
    </button>
    <button aria-label="打开所在文件夹" class="p-1.5 rounded-md hover:bg-stone-100 cursor-pointer text-stone-400 hover:text-stone-700">
      <svg class="w-4 h-4" ...></svg>
    </button>
  </div>
</div>
```

---

### 4.4 标签（Badge / Tag）

#### 文件类型标签
```html
<!-- GIS 矢量 -->
<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-emerald-50 text-emerald-700 border border-emerald-200">
  <span class="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
  GIS 矢量
</span>

<!-- 文件离线 -->
<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-orange-50 text-orange-700 border border-orange-200">
  <svg class="w-3 h-3" ...></svg>
  文件不在线
</span>

<!-- 计数徽章 -->
<span class="inline-flex items-center justify-center w-5 h-5 rounded-full bg-blue-600 text-white text-xs font-bold">
  3
</span>
```

---

### 4.5 模态框（Modal）

```html
<!-- 遮罩层 -->
<div class="fixed inset-0 z-50 flex items-center justify-center p-4">
  <!-- 背景遮罩 -->
  <div class="absolute inset-0 bg-stone-900/40 backdrop-blur-sm"></div>

  <!-- 模态框主体 -->
  <div class="
    relative z-10 w-full max-w-lg
    bg-white rounded-2xl
    shadow-[0_20px_60px_rgba(45,41,38,0.20)]
    flex flex-col max-h-[80vh]
  ">
    <!-- Header -->
    <div class="flex items-center justify-between px-6 py-4 border-b border-stone-100">
      <h2 class="text-lg font-semibold text-stone-800">文件详情</h2>
      <button aria-label="关闭" class="p-1.5 rounded-lg hover:bg-stone-100 text-stone-400 hover:text-stone-600 cursor-pointer transition-colors">
        <svg class="w-5 h-5" ...></svg>
      </button>
    </div>

    <!-- Body（可滚动）-->
    <div class="flex-1 overflow-y-auto px-6 py-5">
      <!-- 内容 -->
    </div>

    <!-- Footer -->
    <div class="flex items-center justify-end gap-3 px-6 py-4 border-t border-stone-100">
      <button class="... secondary-button">取消</button>
      <button class="... primary-button">确认</button>
    </div>
  </div>
</div>
```

---

### 4.6 表格行（Table Row — 文件列表）

```html
<table class="w-full text-sm">
  <!-- 表头 -->
  <thead>
    <tr class="border-b border-stone-200">
      <th class="px-4 py-2.5 text-left text-xs font-semibold text-stone-500 uppercase tracking-wide">文件名</th>
      <th class="px-4 py-2.5 text-left text-xs font-semibold text-stone-500 uppercase tracking-wide">类型</th>
      <th class="px-4 py-2.5 text-right text-xs font-semibold text-stone-500 uppercase tracking-wide">大小</th>
      <th class="px-4 py-2.5 text-right text-xs font-semibold text-stone-500 uppercase tracking-wide">修改时间</th>
      <th class="px-4 py-2.5 w-20"></th>
    </tr>
  </thead>
  <!-- 表格行 -->
  <tbody class="divide-y divide-stone-100">
    <tr class="group hover:bg-stone-50 transition-colors duration-100 cursor-pointer">
      <!-- 文件名列（含类型色条）-->
      <td class="px-4 py-3">
        <div class="flex items-center gap-2.5">
          <div class="w-1 h-8 rounded-full bg-emerald-500"></div>
          <div class="w-7 h-7 rounded-md bg-emerald-50 flex items-center justify-center">
            <svg class="w-4 h-4 text-emerald-600" ...></svg>
          </div>
          <div class="min-w-0">
            <p class="font-medium text-stone-800 truncate max-w-xs">roads_2024.shp</p>
            <p class="text-xs text-stone-400 truncate max-w-xs">...城市交通/</p>
          </div>
        </div>
      </td>
      <td class="px-4 py-3">
        <span class="badge-gis-vector">GIS 矢量</span>
      </td>
      <td class="px-4 py-3 text-right text-stone-500 font-mono tabular-nums">128 MB</td>
      <td class="px-4 py-3 text-right text-stone-400">2024-01-15</td>
      <!-- 操作列：hover 显示 -->
      <td class="px-4 py-3">
        <div class="opacity-0 group-hover:opacity-100 flex items-center gap-1 justify-end transition-opacity">
          <button aria-label="打开" class="icon-button">...</button>
          <button aria-label="定位" class="icon-button">...</button>
        </div>
      </td>
    </tr>
  </tbody>
</table>
```

---

### 4.7 Skeleton 骨架屏（加载态）

```html
<!-- 文件列表骨架屏 -->
<div class="space-y-2 animate-pulse">
  <div class="flex items-center gap-3 px-4 py-3 rounded-xl bg-stone-50">
    <div class="w-1 h-10 rounded-full bg-stone-200"></div>
    <div class="w-9 h-9 rounded-lg bg-stone-200"></div>
    <div class="flex-1 space-y-2">
      <div class="h-3.5 bg-stone-200 rounded w-3/5"></div>
      <div class="h-2.5 bg-stone-200 rounded w-4/5"></div>
    </div>
    <div class="h-3 bg-stone-200 rounded w-12"></div>
  </div>
  <!-- 重复 5-8 条 -->
</div>
```

---

### 4.8 进度条（扫描进度）

```html
<div class="space-y-1.5">
  <div class="flex justify-between text-xs text-stone-500">
    <span>正在扫描 E:\GIS\</span>
    <span class="font-mono">68,234 / 352,000</span>
  </div>
  <div class="h-1.5 bg-stone-200 rounded-full overflow-hidden">
    <div
      class="h-full bg-blue-500 rounded-full transition-all duration-300 ease-out"
      style="width: 19%"
    ></div>
  </div>
</div>
```

---

## 5. 布局规范

### 5.1 整体布局结构

```
┌──────────────────────────────────────────┐
│  TopBar（仅移动端，桌面端隐藏）           │
├────────────┬─────────────────────────────┤
│            │                             │
│  侧边栏    │       主内容区              │
│  Sidebar   │       Main Content          │
│  240px     │       flex-1                │
│  (固定)    │       (滚动)                │
│            │                             │
│            │                             │
└────────────┴─────────────────────────────┘
```

### 5.2 侧边栏（Sidebar）

```html
<aside class="
  fixed left-0 top-0 bottom-0
  w-60 flex flex-col
  bg-[#F4F2EE] border-r border-stone-200
  z-30
">
  <!-- Logo 区域 -->
  <div class="px-5 py-4 border-b border-stone-200">
    <div class="flex items-center gap-2.5">
      <div class="w-7 h-7 rounded-lg bg-blue-600 flex items-center justify-center">
        <svg class="w-4 h-4 text-white" ...></svg>
      </div>
      <span class="font-semibold text-stone-800 text-sm">文件智能管理</span>
    </div>
  </div>

  <!-- 主导航 -->
  <nav class="flex-1 px-3 py-4 space-y-0.5 overflow-y-auto">
    <!-- 导航组标题 -->
    <p class="px-3 mb-1 text-xs font-semibold text-stone-400 uppercase tracking-wider">核心功能</p>

    <!-- 导航项（active 态）-->
    <a href="#" class="
      flex items-center gap-2.5 px-3 py-2 rounded-lg
      bg-white text-blue-700 font-medium text-sm
      shadow-sm border border-stone-200
      cursor-pointer
    ">
      <svg class="w-4 h-4" ...></svg>
      搜索
    </a>

    <!-- 导航项（普通态）-->
    <a href="#" class="
      flex items-center gap-2.5 px-3 py-2 rounded-lg
      text-stone-600 hover:text-stone-900 hover:bg-stone-100
      text-sm transition-colors duration-150
      cursor-pointer
    ">
      <svg class="w-4 h-4" ...></svg>
      仪表盘
    </a>
  </nav>

  <!-- 底部操作区（扫描、设置）-->
  <div class="px-3 py-3 border-t border-stone-200 space-y-1">
    <button class="
      w-full flex items-center gap-2.5 px-3 py-2 rounded-lg
      bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium
      transition-colors duration-150 cursor-pointer
    ">
      <svg class="w-4 h-4" ...></svg>
      开始扫描
    </button>
  </div>
</aside>
```

### 5.3 主内容区

```html
<main class="ml-60 min-h-screen bg-[#FAF9F7]">
  <!-- 顶部搜索栏（粘性）-->
  <div class="sticky top-0 z-20 bg-[#FAF9F7]/90 backdrop-blur-sm border-b border-stone-200 px-6 py-3">
    <!-- 搜索框 + 过滤器 -->
  </div>

  <!-- 内容区 -->
  <div class="px-6 py-5">
    <!-- 页面内容 -->
  </div>
</main>
```

### 5.4 响应式断点

| 断点  | 宽度       | 布局变化                                     |
|------|-----------|----------------------------------------------|
| `sm` | 640px+    | —                                            |
| `md` | 768px+    | 侧边栏以抽屉形式出现                          |
| `lg` | 1024px+   | 侧边栏固定显示（240px），内容区展示 2 列      |
| `xl` | 1280px+   | **目标主视图**，内容区宽松                    |
| `2xl`| 1536px+   | 内容区最大宽度 `max-w-screen-xl` 居中        |

> **设计首要目标**：`1280px × 800px` 桌面环境（Windows 办公场景主流分辨率）。移动端不是核心场景，但保证 `768px` 可用。

### 5.5 内容区最大宽度

```html
<!-- 搜索结果页：列表为主，无需限制宽度 -->
<div class="px-6 py-5">...</div>

<!-- 仪表盘：卡片网格，限制最大宽度 -->
<div class="px-6 py-5 max-w-7xl">...</div>

<!-- 设置页：表单为主，限制宽度提升可读性 -->
<div class="px-6 py-5 max-w-2xl">...</div>
```

### 5.6 搜索结果布局规范

```
搜索栏（粘性顶部）
├── 过滤器行（类型 / 排序 / 结果计数）
└── 结果列表（虚拟滚动，每项约 64px 高）
    ├── 文件行 × N
    └── 加载更多 / 分页
```

---

## 6. 图标规范

### 6.1 图标库选择

使用 **Lucide Icons**（MIT 协议，与 Tailwind 配合最佳）。通过 CDN 引入：

```html
<!-- 在 <head> 引入 Lucide Icons -->
<script src="https://unpkg.com/lucide@latest/dist/umd/lucide.min.js"></script>
<!-- 使用方式：<i data-lucide="search" class="w-4 h-4"></i> -->
<!-- 初始化：lucide.createIcons(); -->
```

### 6.2 图标尺寸规范

| 场景             | 尺寸          | Tailwind      |
|----------------|--------------|---------------|
| 导航栏图标       | 16×16 px     | `w-4 h-4`     |
| 列表行图标       | 16×16 px     | `w-4 h-4`     |
| 卡片/面板图标    | 18×18 px     | `w-4.5 h-4.5` |
| 文件类型图标（小）| 18×18 px    | `w-4.5 h-4.5` |
| 文件类型图标（中）| 20×20 px    | `w-5 h-5`     |
| KPI 卡片图标    | 18×18 px     | `w-4.5 h-4.5` |
| 模态框/操作图标  | 20×20 px     | `w-5 h-5`     |
| 空状态大图标     | 48×48 px     | `w-12 h-12`   |

### 6.3 文件类型图标映射

| 文件类型       | Lucide 图标名            | 背景色 Tailwind     | 图标色 Tailwind     |
|--------------|------------------------|---------------------|---------------------|
| `gis_vector` | `map`                  | `bg-emerald-50`     | `text-emerald-600`  |
| `gis_raster` | `grid-3x3`             | `bg-violet-50`      | `text-violet-700`   |
| `mapgis`     | `layers`               | `bg-cyan-50`        | `text-cyan-700`     |
| `fme`        | `workflow`             | `bg-orange-50`      | `text-orange-700`   |
| `survey`     | `compass`              | `bg-yellow-50`      | `text-yellow-700`   |
| `cad`        | `pen-tool`             | `bg-blue-50`        | `text-blue-700`     |
| `image`      | `image`                | `bg-pink-50`        | `text-pink-700`     |
| `document`   | `file-text`            | `bg-indigo-50`      | `text-indigo-700`   |
| `spreadsheet`| `table-2`              | `bg-green-50`       | `text-green-700`    |
| `video`      | `film`                 | `bg-rose-50`        | `text-rose-700`     |
| `audio`      | `music`                | `bg-purple-50`      | `text-purple-700`   |
| `archive`    | `archive`              | `bg-amber-50`       | `text-amber-800`    |
| `other`      | `file`                 | `bg-stone-100`      | `text-stone-600`    |

### 6.4 文件类型图标组件实现

```javascript
// file_types.js — 文件类型视觉配置
const FILE_TYPE_CONFIG = {
  gis_vector:  { label: 'GIS 矢量', icon: 'map',       bgClass: 'bg-emerald-50', textClass: 'text-emerald-600', barClass: 'bg-emerald-500', badgeBg: 'bg-emerald-50',  badgeText: 'text-emerald-700', badgeBorder: 'border-emerald-200' },
  gis_raster:  { label: 'GIS 栅格', icon: 'grid-3x3',  bgClass: 'bg-violet-50',  textClass: 'text-violet-700',  barClass: 'bg-violet-500',  badgeBg: 'bg-violet-50',   badgeText: 'text-violet-700',  badgeBorder: 'border-violet-200'  },
  mapgis:      { label: 'MapGIS',   icon: 'layers',     bgClass: 'bg-cyan-50',    textClass: 'text-cyan-700',    barClass: 'bg-cyan-500',    badgeBg: 'bg-cyan-50',     badgeText: 'text-cyan-700',    badgeBorder: 'border-cyan-200'    },
  fme:         { label: 'FME',      icon: 'workflow',   bgClass: 'bg-orange-50',  textClass: 'text-orange-700',  barClass: 'bg-orange-500',  badgeBg: 'bg-orange-50',   badgeText: 'text-orange-700',  badgeBorder: 'border-orange-200'  },
  survey:      { label: '测量数据', icon: 'compass',    bgClass: 'bg-yellow-50',  textClass: 'text-yellow-700',  barClass: 'bg-yellow-500',  badgeBg: 'bg-yellow-50',   badgeText: 'text-yellow-700',  badgeBorder: 'border-yellow-200'  },
  cad:         { label: 'CAD',      icon: 'pen-tool',   bgClass: 'bg-blue-50',    textClass: 'text-blue-700',    barClass: 'bg-blue-500',    badgeBg: 'bg-blue-50',     badgeText: 'text-blue-700',    badgeBorder: 'border-blue-200'    },
  image:       { label: '图片',     icon: 'image',      bgClass: 'bg-pink-50',    textClass: 'text-pink-700',    barClass: 'bg-pink-500',    badgeBg: 'bg-pink-50',     badgeText: 'text-pink-700',    badgeBorder: 'border-pink-200'    },
  document:    { label: '文档',     icon: 'file-text',  bgClass: 'bg-indigo-50',  textClass: 'text-indigo-700',  barClass: 'bg-indigo-500',  badgeBg: 'bg-indigo-50',   badgeText: 'text-indigo-700',  badgeBorder: 'border-indigo-200'  },
  spreadsheet: { label: '表格',     icon: 'table-2',    bgClass: 'bg-green-50',   textClass: 'text-green-700',   barClass: 'bg-green-500',   badgeBg: 'bg-green-50',    badgeText: 'text-green-700',   badgeBorder: 'border-green-200'   },
  video:       { label: '视频',     icon: 'film',       bgClass: 'bg-rose-50',    textClass: 'text-rose-700',    barClass: 'bg-rose-500',    badgeBg: 'bg-rose-50',     badgeText: 'text-rose-700',    badgeBorder: 'border-rose-200'    },
  audio:       { label: '音频',     icon: 'music',      bgClass: 'bg-purple-50',  textClass: 'text-purple-700',  barClass: 'bg-purple-500',  badgeBg: 'bg-purple-50',   badgeText: 'text-purple-700',  badgeBorder: 'border-purple-200'  },
  archive:     { label: '压缩包',   icon: 'archive',    bgClass: 'bg-amber-50',   textClass: 'text-amber-800',   barClass: 'bg-amber-500',   badgeBg: 'bg-amber-50',    badgeText: 'text-amber-800',   badgeBorder: 'border-amber-200'   },
  other:       { label: '其他',     icon: 'file',       bgClass: 'bg-stone-100',  textClass: 'text-stone-600',   barClass: 'bg-stone-400',   badgeBg: 'bg-stone-100',   badgeText: 'text-stone-600',   badgeBorder: 'border-stone-300'   },
};

function getFileTypeConfig(type) {
  return FILE_TYPE_CONFIG[type] || FILE_TYPE_CONFIG.other;
}
```

### 6.5 通用 UI 图标速查

| 功能         | Lucide 图标名      |
|------------|------------------|
| 搜索         | `search`         |
| 刷新/扫描   | `refresh-cw`     |
| 设置         | `settings`       |
| 文件夹定位  | `folder-open`    |
| 打开文件    | `external-link`  |
| 复制路径    | `clipboard-copy` |
| 预览        | `eye`            |
| 关闭        | `x`              |
| 展开/折叠   | `chevron-right`  |
| 排序        | `arrow-up-down`  |
| 过滤        | `filter`         |
| 仪表盘      | `layout-dashboard`|
| AI 对话    | `message-circle` |
| 历史记录    | `history`        |
| 统计图表    | `bar-chart-2`    |
| 磁盘        | `hard-drive`     |
| 离线状态    | `wifi-off`       |
| 成功        | `check-circle-2` |
| 警告        | `alert-triangle` |
| 错误        | `x-circle`       |

---

## 7. 动效规范

### 7.1 核心原则

- **功能优先**：动效服务于信息传达，不做装饰
- **克制**：持续时间控制在 150-300ms，禁止超过 500ms 的普通交互动效
- **尊重偏好**：所有动效需检查 `prefers-reduced-motion`
- **GPU 优化**：只用 `transform` 和 `opacity` 做动画，禁止动画 `width/height/top/left`

```css
/* 全局：尊重减少动效偏好 */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}
```

### 7.2 时间与缓动函数

| 场景             | 时长   | 缓动函数                    | Tailwind 类                      |
|----------------|--------|----------------------------|----------------------------------|
| 颜色/背景切换   | 150ms  | `ease-in-out`              | `transition-colors duration-150` |
| 透明度变化      | 150ms  | `ease-in-out`              | `transition-opacity duration-150`|
| 阴影过渡        | 200ms  | `ease-out`                 | `transition-shadow duration-200` |
| 面板展开/收起   | 200ms  | `ease-out`                 | `transition-all duration-200`    |
| 进度条更新      | 300ms  | `ease-out`                 | `transition-all duration-300`    |
| 模态框出现      | 200ms  | `cubic-bezier(0,0,0.2,1)` | `duration-200 ease-out`          |
| 模态框消失      | 150ms  | `ease-in`                  | `duration-150 ease-in`           |
| 搜索结果淡入    | 200ms  | `ease-out`                 | `transition-opacity duration-200`|
| Tooltip 出现   | 100ms  | `ease-out`                 | `duration-100`                   |

### 7.3 具体动效实现

#### 搜索结果列表淡入
```css
/* 搜索完成后，结果列表整体淡入 */
.search-results-enter {
  animation: fadeInUp 200ms ease-out both;
}
@keyframes fadeInUp {
  from { opacity: 0; transform: translateY(4px); }
  to   { opacity: 1; transform: translateY(0);   }
}
```

#### 模态框动效
```css
.modal-enter { animation: modalIn 200ms cubic-bezier(0, 0, 0.2, 1) both; }
.modal-leave { animation: modalOut 150ms ease-in both; }
@keyframes modalIn  { from { opacity: 0; transform: scale(0.96) translateY(-8px); } to { opacity: 1; transform: scale(1) translateY(0); } }
@keyframes modalOut { from { opacity: 1; transform: scale(1); } to { opacity: 0; transform: scale(0.97); } }
.overlay-enter { animation: overlayIn 200ms ease-out both; }
@keyframes overlayIn { from { opacity: 0; } to { opacity: 1; } }
```

#### 扫描进度实时更新
```javascript
// 进度条平滑更新（每 500ms 轮询一次，过渡 300ms 平滑）
function updateProgress(percent) {
  progressBar.style.width = `${percent}%`;
  // CSS: transition: width 300ms ease-out
}
```

#### 骨架屏动画
```html
<!-- Tailwind animate-pulse 实现骨架屏 -->
<div class="animate-pulse space-y-2">
  <div class="h-4 bg-stone-200 rounded w-3/4"></div>
  <div class="h-4 bg-stone-200 rounded w-1/2"></div>
</div>
```

#### hover 交互规范
```html
<!-- 文件行 hover：背景色 + 边框 + 阴影联动 -->
<div class="
  hover:bg-stone-50
  hover:border-stone-200
  hover:shadow-[0_2px_8px_rgba(45,41,38,0.07)]
  transition-all duration-150
">
<!-- 按钮操作组：opacity 渐显 -->
<div class="opacity-0 group-hover:opacity-100 transition-opacity duration-150">
```

#### 通知/Toast 动效
```css
.toast-enter { animation: toastIn 250ms ease-out both; }
.toast-leave { animation: toastOut 200ms ease-in both; }
@keyframes toastIn  { from { opacity: 0; transform: translateX(100%); } to { opacity: 1; transform: translateX(0); } }
@keyframes toastOut { from { opacity: 1; transform: translateX(0); }    to { opacity: 0; transform: translateX(100%); } }
```

### 7.4 加载状态规范

| 场景              | 加载方式          | 实现                          |
|-----------------|-----------------|-------------------------------|
| 搜索请求（<200ms）| 不显示 loader    | 无需处理                      |
| 搜索请求（>200ms）| 搜索框 spinner   | `animate-spin` 在输入框右侧   |
| 文件列表首次加载  | 骨架屏           | `animate-pulse` 列表占位      |
| 扫描进行中        | 进度条 + 计数    | 实时轮询 `/api/scan/status`   |
| 缩略图加载中      | 图片占位背景     | `bg-stone-100 animate-pulse`  |
| 统计数据加载      | 数字骨架         | `animate-pulse` 宽度固定      |

---

## 8. Tailwind 配置扩展

在 `<script>` 标签中通过 Tailwind CDN 配置项覆盖默认主题：

```html
<script>
  tailwind.config = {
    theme: {
      extend: {
        colors: {
          // 项目主色调（温暖石青蓝）
          primary: {
            50:  '#EFF6FF',
            100: '#DBEAFE',
            500: '#3B82F6',
            600: '#2563EB',
            700: '#1D4ED8',
            900: '#1E3A8A',
          },
          // 强调色（温暖琥珀）
          accent: {
            400: '#FBBF24',
            500: '#F59E0B',
            600: '#D97706',
            800: '#92400E',
          },
          // 项目背景色（温暖米白）
          warm: {
            50:  '#FAF9F7',  // bg-base
            100: '#F4F2EE',  // bg-surface
            200: '#EDE9E3',  // bg-hover
            300: '#E4DFD8',  // bg-active
            400: '#DDD8D0',  // border
          },
        },
        fontFamily: {
          sans: ['-apple-system', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei UI', 'Microsoft YaHei', 'Segoe UI', 'system-ui', 'sans-serif'],
          mono: ['JetBrains Mono', 'Fira Code', 'Cascadia Code', 'Consolas', 'monospace'],
        },
        boxShadow: {
          'warm-sm': '0 1px 2px rgba(45,41,38,0.06)',
          'warm-md': '0 4px 12px rgba(45,41,38,0.08), 0 1px 3px rgba(45,41,38,0.04)',
          'warm-lg': '0 8px 24px rgba(45,41,38,0.10), 0 2px 6px rgba(45,41,38,0.05)',
          'warm-xl': '0 16px 40px rgba(45,41,38,0.12), 0 4px 12px rgba(45,41,38,0.06)',
          'modal':   '0 20px 60px rgba(45,41,38,0.20)',
        },
        borderRadius: {
          'xl': '12px',
          '2xl': '16px',
        },
        transitionDuration: {
          '0': '0ms',
        },
      },
    },
  }
</script>
```

---

## 9. 交付前自查清单

### 视觉质量
- [ ] 无 emoji 用作 UI 图标（全部使用 Lucide SVG）
- [ ] 所有图标来自 Lucide 同一图标集，尺寸统一
- [ ] hover 状态不产生布局偏移（不用 scale 位移）
- [ ] 文件列表行使用色条 + 图标背景区分类型
- [ ] 数字统计使用等宽字体 `font-mono tabular-nums`

### 交互体验
- [ ] 所有可点击元素有 `cursor-pointer`
- [ ] hover 提供明确视觉反馈（颜色/阴影变化）
- [ ] 过渡动效 150-300ms，使用合适缓动函数
- [ ] 键盘导航 focus 状态可见（`focus:ring-2`）
- [ ] 按钮异步操作期间禁用并显示 spinner

### 布局与响应
- [ ] 侧边栏 240px 固定，主内容 `ml-60`
- [ ] 搜索栏粘性顶部 `sticky top-0 z-20`
- [ ] 文件名超长时 `truncate` 省略，不破坏布局
- [ ] 在 `1280px × 800px` 分辨率下完整可用

### 无障碍
- [ ] 图标按钮有 `aria-label`
- [ ] 颜色对比度 ≥ 4.5:1（正文），≥ 3:1（大文字）
- [ ] 表单输入框有关联 `label`
- [ ] 颜色不是唯一信息传达手段（配合图标/文字）
- [ ] 实现 `prefers-reduced-motion` 媒体查询

### 性能
- [ ] 图片懒加载 `loading="lazy"`
- [ ] 大列表使用虚拟滚动（超过 100 条）
- [ ] 占位符预留空间避免内容跳动（CLS = 0）

---

*设计系统由 ui-ux-pro-max skill 辅助生成，结合项目具体需求定制。*
*更新记录：v1.0.0 — 2026-03-04 初始版本*
