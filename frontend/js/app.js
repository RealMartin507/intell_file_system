/**
 * app.js — 全局应用逻辑
 * 负责：视图切换、Toast 通知、磁盘/后端状态检测、加载遮罩
 */

const API_BASE = '';

// ----------------------------------------------------------------
// 视图配置
// ----------------------------------------------------------------
const VIEWS = {
  dashboard: { title: '仪表盘',  viewId: 'view-dashboard' },
  search:    { title: '搜索文件', viewId: 'view-search'    },
  ai:        { title: 'AI 问答', viewId: 'view-ai'        },
  settings:  { title: '设置',    viewId: 'view-settings'  },
};

let _currentView = 'dashboard';

// ----------------------------------------------------------------
// DOM 引用（DOMContentLoaded 之后才访问）
// ----------------------------------------------------------------
let _pageTitle;
let _navItems;
let _toastContainer;
let _loadingOverlay;

// ----------------------------------------------------------------
// 初始化
// ----------------------------------------------------------------
document.addEventListener('DOMContentLoaded', () => {
  // 缓存常用 DOM 引用
  _pageTitle       = document.getElementById('page-title');
  _navItems        = document.querySelectorAll('.nav-item[data-view]');
  _toastContainer  = document.getElementById('toast-container');
  _loadingOverlay  = document.getElementById('loading-overlay');

  // 初始化 Lucide 图标
  lucide.createIcons();

  // 绑定导航点击
  _navItems.forEach(item => {
    item.addEventListener('click', () => switchView(item.dataset.view));
  });

  // 绑定顶部扫描按钮：非仪表盘时切换过去；仪表盘内的扫描滚动由 dashboard.js 接管
  document.getElementById('btn-scan')?.addEventListener('click', () => {
    if (_currentView !== 'dashboard') switchView('dashboard');
  });

  // 监听视图切换，初始化相应模块
  document.addEventListener('app:viewChanged', (e) => {
    const viewName = e.detail.view;
    if (viewName === 'settings' && window.Settings) {
      setTimeout(() => Settings.init(), 0);
    }
  });

  // 初始视图
  switchView('dashboard');

  // 开始磁盘状态检测（立即检测一次，此后每 30 秒复查）
  _checkDiskStatus();
  setInterval(_checkDiskStatus, 30_000);
});

// ----------------------------------------------------------------
// 视图切换
// ----------------------------------------------------------------
function switchView(viewName) {
  if (!VIEWS[viewName]) return;

  _currentView = viewName;
  const cfg = VIEWS[viewName];

  // 更新顶部标题
  if (_pageTitle) _pageTitle.textContent = cfg.title;

  // 切换视图显示
  Object.keys(VIEWS).forEach(name => {
    const el = document.getElementById(VIEWS[name].viewId);
    if (!el) return;
    if (name === viewName) {
      // 如果视图有 flex 类，使用 flex 显示；否则使用 block
      el.style.display = el.classList.contains('flex') ? 'flex' : 'block';
    } else {
      el.style.display = 'none';
    }
  });

  // 更新导航选中状态
  _navItems?.forEach(item => {
    const isActive = item.dataset.view === viewName;
    // 清除旧状态
    item.classList.remove(
      'bg-white', 'text-blue-700', 'font-medium', 'border', 'border-warm-400',
      'text-stone-600', 'hover:text-stone-900', 'hover:bg-warm-200'
    );
    if (isActive) {
      // 选中态：白底 + 蓝字 + 细边框 + 轻阴影
      item.classList.add('bg-white', 'text-blue-700', 'font-medium', 'border', 'border-warm-400');
      item.style.boxShadow = '0 1px 2px rgba(45,41,38,0.06)';
    } else {
      // 普通态
      item.classList.add('text-stone-600', 'hover:text-stone-900', 'hover:bg-warm-200');
      item.style.boxShadow = '';
    }
  });

  // 通知页面模块视图已切换
  document.dispatchEvent(new CustomEvent('app:viewChanged', { detail: { view: viewName } }));
}

// ----------------------------------------------------------------
// 磁盘 / 后端状态检测
// ----------------------------------------------------------------
async function _checkDiskStatus() {
  const dot  = document.getElementById('disk-status-dot');
  const text = document.getElementById('disk-status-text');
  const sub  = document.getElementById('disk-status-sub');
  if (!dot) return;

  try {
    const res = await fetch(`${API_BASE}/api/stats/overview`, {
      signal: AbortSignal.timeout(3000),
    });
    if (res.ok) {
      dot.style.backgroundColor  = '#16A34A'; // green-600
      text.textContent = '服务在线';
      sub.textContent  = '已连接至本地后端';
    } else {
      _setOfflineStatus(dot, text, sub);
    }
  } catch {
    _setOfflineStatus(dot, text, sub);
  }
}

function _setOfflineStatus(dot, text, sub) {
  dot.style.backgroundColor = '#9CA3AF'; // gray-400
  text.textContent = '服务离线';
  sub.textContent  = '请启动后端服务';
}

// ----------------------------------------------------------------
// Toast 通知
// ----------------------------------------------------------------
const _TOAST_CONFIG = {
  success: { icon: 'check-circle-2', bg: 'bg-green-50', border: 'border-green-200', text: 'text-green-800', iconColor: 'text-green-600' },
  error:   { icon: 'x-circle',       bg: 'bg-red-50',   border: 'border-red-200',   text: 'text-red-800',   iconColor: 'text-red-600'   },
  warning: { icon: 'alert-triangle', bg: 'bg-amber-50', border: 'border-amber-200', text: 'text-amber-800', iconColor: 'text-amber-600' },
  info:    { icon: 'info',           bg: 'bg-blue-50',  border: 'border-blue-200',  text: 'text-blue-800',  iconColor: 'text-blue-600'  },
};

/**
 * 显示 Toast 通知
 * @param {string} message
 * @param {'success'|'error'|'warning'|'info'} type
 * @param {number} duration  ms
 */
function showToast(message, type = 'info', duration = 3500) {
  if (!_toastContainer) return;

  const cfg = _TOAST_CONFIG[type] || _TOAST_CONFIG.info;

  const toast = document.createElement('div');
  toast.className = [
    'pointer-events-auto flex items-center gap-3 px-4 py-3 rounded-xl border',
    cfg.bg, cfg.border,
    'max-w-sm w-80 toast-enter',
  ].join(' ');
  toast.style.boxShadow = '0 4px 12px rgba(45,41,38,0.08), 0 1px 3px rgba(45,41,38,0.04)';

  toast.innerHTML = `
    <i data-lucide="${cfg.icon}" class="w-4 h-4 flex-shrink-0 ${cfg.iconColor}"></i>
    <p class="text-sm font-medium ${cfg.text} flex-1 leading-snug">${message}</p>
    <button
      aria-label="关闭"
      class="flex-shrink-0 p-0.5 rounded cursor-pointer opacity-50 hover:opacity-100 transition-opacity ${cfg.text}"
    >
      <i data-lucide="x" class="w-3.5 h-3.5"></i>
    </button>
  `;

  // 关闭按钮
  toast.querySelector('button').addEventListener('click', () => _dismissToast(toast));

  _toastContainer.appendChild(toast);
  lucide.createIcons({ nodes: [toast] });

  // 自动消失
  setTimeout(() => _dismissToast(toast), duration);
}

function _dismissToast(toast) {
  if (!toast.isConnected) return;
  toast.classList.replace('toast-enter', 'toast-leave');
  toast.addEventListener('animationend', () => toast.remove(), { once: true });
}

// ----------------------------------------------------------------
// 全局加载遮罩
// ----------------------------------------------------------------
const LoadingOverlay = {
  show(title = '处理中...', desc = '请稍候') {
    if (!_loadingOverlay) return;
    document.getElementById('loading-title').textContent = title;
    document.getElementById('loading-desc').textContent  = desc;
    document.getElementById('loading-progress-bar').style.width  = '0%';
    document.getElementById('loading-progress-text').textContent = '准备中';
    document.getElementById('loading-progress-count').textContent = '--';
    _loadingOverlay.style.display = 'flex';
  },

  hide() {
    if (_loadingOverlay) _loadingOverlay.style.display = 'none';
  },

  /**
   * 更新进度
   * @param {string} text    当前路径/状态描述
   * @param {string} count   "68,234 / 352,000"
   * @param {number} percent  0-100
   */
  updateProgress(text, count, percent) {
    const bar = document.getElementById('loading-progress-bar');
    if (bar) bar.style.width = `${Math.min(100, percent)}%`;
    const txt = document.getElementById('loading-progress-text');
    if (txt) txt.textContent = text;
    const cnt = document.getElementById('loading-progress-count');
    if (cnt) cnt.textContent = count;
  },
};

// ----------------------------------------------------------------
// 全局暴露（供 dashboard.js / search.js 等模块调用）
// ----------------------------------------------------------------
window.App = {
  API_BASE,
  get currentView() { return _currentView; },
  switchView,
  showToast,
  LoadingOverlay,
};
