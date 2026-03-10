# Vibe Publish (微信公众号协作平台)

<div align="center">
  <h3>✨ 一个集 Markdown 编辑、排版与公众号数据抓取分析于一体的现代化创作平台</h3>
  <p><b>高效 · 优雅 · 沉浸式 · 云端同步</b></p>
  <br/>
</div>

**Vibe Publish** 是一个专为微信公众号创作者打造的高效工具。它不仅仅是一个 Markdown 编辑器，更是一个集成了文章抓取、历史归档、发布策略分析的一站式工作台。

## 🚀 核心功能

### 1. 📝 Vibe Editor (沉浸式编辑器)
- **专业 Markdown 支持**：基于 CodeMirror 6 构建，支持 GFM 语法。
- **所见即所得**：实时预览渲染效果，完美适配微信公众号格式。
- **丰富组件支持**：内置 [Mermaid](https://mermaid-js.github.io/) 流程图、[KaTeX](https://katex.org/) 数学公式支持。
- **一键排版**：自动处理 CSS 样式，通过 `juice` 内联样式，直接复制即可粘贴到微信后台。

### 2. 🕷️ WeChat Crawler (智能抓取器)
- **多策略抓取**：支持线性扫描、指数搜索、二分查找等多种高效抓取算法。
- **智能策略建议**：根据目标抓取范围自动推荐最优算法。
- **数据可视化**：直观展示抓取进度、文章状态和历史归档，支持 2K/大屏响应式布局。
- **性能飞跃**：采用 **“预取 + 懒加载”** 策略，实现翻页零延迟无感切换。

### 3. ☁️ 云端同步与持久化 (Supabase CI/CD)
- **配置云端化**：Cookies、Token 及监控账号通过 Supabase 云端同步，支持跨设备无缝衔接。
- **三级容错机制**：云端 → LocalStorage → 默认值，确保极端网络下的配置可用性。
- **数据精准归档**：基于 `FakeID` 与公众号名称双重匹配的精确查询机制。
- **数据库集成**：内置 PostgreSQL 结构，支持数万级文章数据的秒级检索。

## 🛠️ 技术栈

本项目基于现代前端技术栈构建，注重性能与开发体验：

- **核心框架**: [Vue 3](https://vuejs.org/) (Composition API) + [TypeScript](https://www.typescriptlang.org/)
- **构建工具**: [Vite](https://vitejs.dev/)
- **样式方案**: [Tailwind CSS](https://tailwindcss.com/) + Vanilla CSS (极致动效)
- **状态管理**: [Pinia](https://pinia.vuejs.org/)
- **编辑器内核**: [CodeMirror 6](https://codemirror.net/)
- **后端服务**: [Supabase](https://supabase.com/) (PostgreSQL)
- **UI 增强**: [Lucide Vue](https://lucide.dev/) + 骨架屏加载 (Skeleton Screen)

## ⚡ 快速开始

### 环境要求
- Node.js >= 16.0.0
- npm 或 yarn

### 安装步骤

1. **克隆仓库**
   ```bash
   git clone https://github.com/RealMartin507/vibe-punlish.git
   cd vibe-punlish
   ```

2. **安装依赖**
   ```bash
   npm install
   ```

3. **启动开发服务器**
   ```bash
   npm run dev
   ```
   访问 `http://localhost:5173` 即可开始使用。

4. **构建生产版本**
   ```bash
   npm run build
   ```

## ⚙️ 配置说明

### 微信接口配置
为了正常使用公众号抓取功能，你需要获取微信后台的 Cookie 和 Token：
1. 登录 [微信公众平台](https://mp.weixin.qq.com/)。
2. 在 Vibe Publish 界面右上角点击 **设置**，填入 Token 和 Cookies 并保存。
3. 系统将自动同步至 Supabase 云端。

### 数据库初始化
请参考 [Supabase 配置指南](docs/SUPABASE_CONFIG_GUIDE.md) 进行数据库表结构初始化。

## 📂 目录结构

```
vibe-publish/
├── 📚 docs/                # 项目文档 (配置指南、设计文档等)
├── 🧪 tests/               # 测试文件
├── 🐛 debug/               # 调试空间 (已忽略)
├── 💻 src/                 # 源代码
│   ├── components/       # UI 组件
│   │   ├── 📝 editor/    # 编辑器模块
│   │   ├── 🎨 layout/    # 全局布局
│   │   └── 🕷️ wechat/    # 微信爬虫模块
│   ├── vibecore/         # 核心渲染与编辑器逻辑
│   ├── stores/           # Pinia 状态管理
│   └── main.ts           # 入口文件
├── ⚙️ 配置文件              # package.json, vite.config.ts 等
├── 📜 PROJECT_CHANGELOG.md # 变更日志
├── 📝 TODO.md              # 待办事项
└── 📖 README.md            # 项目说明
```

> 💡 **提示**：以上仅展示核心模块结构。关于完整的物理文件位置映射，请参阅 [docs/DIRECTORY_TREE.md](docs/DIRECTORY_TREE.md)。

## 📄 许可证

[MIT License](LICENSE)
