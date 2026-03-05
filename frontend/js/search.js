/**
 * search.js — 搜索模块
 * 依赖：window.App（由 app.js 提供）
 */

// ──────────────────────────────────────────────
// 文件类型视觉配置
// ──────────────────────────────────────────────
const FILE_TYPE_CONFIG = {
  gis_vector:  { label: 'GIS 矢量', icon: 'map',         bgClass: 'bg-emerald-50',  textClass: 'text-emerald-600',  barColor: '#059669'  },
  gis_raster:  { label: 'GIS 栅格', icon: 'grid-3x3',    bgClass: 'bg-violet-50',   textClass: 'text-violet-700',   barColor: '#7C3AED'  },
  mapgis:      { label: 'MapGIS',   icon: 'layers',      bgClass: 'bg-cyan-50',     textClass: 'text-cyan-700',     barColor: '#0E7490'  },
  fme:         { label: 'FME',      icon: 'workflow',    bgClass: 'bg-orange-50',   textClass: 'text-orange-700',   barColor: '#C2410C'  },
  survey:      { label: '测量数据', icon: 'compass',     bgClass: 'bg-yellow-50',   textClass: 'text-yellow-700',   barColor: '#A16207'  },
  cad:         { label: 'CAD',      icon: 'pen-tool',    bgClass: 'bg-blue-50',     textClass: 'text-blue-700',     barColor: '#1D4ED8'  },
  image:       { label: '图片',     icon: 'image',       bgClass: 'bg-pink-50',     textClass: 'text-pink-700',     barColor: '#BE185D'  },
  document:    { label: '文档',     icon: 'file-text',   bgClass: 'bg-indigo-50',   textClass: 'text-indigo-700',   barColor: '#4338CA'  },
  spreadsheet: { label: '表格',     icon: 'table-2',     bgClass: 'bg-green-50',    textClass: 'text-green-700',    barColor: '#15803D'  },
  video:       { label: '视频',     icon: 'film',        bgClass: 'bg-rose-50',     textClass: 'text-rose-700',     barColor: '#9D174D'  },
  audio:       { label: '音频',     icon: 'music',       bgClass: 'bg-purple-50',   textClass: 'text-purple-700',   barColor: '#6D28D9'  },
  archive:     { label: '压缩包',   icon: 'archive',     bgClass: 'bg-amber-50',    textClass: 'text-amber-800',    barColor: '#92400E'  },
  other:       { label: '其他',     icon: 'file',        bgClass: 'bg-stone-100',   textClass: 'text-stone-600',    barColor: '#57534E'  },
};

const TYPE_FILTERS = [
  { key: 'all',         label: '全部' },
  { key: 'document',    label: '文档' },
  { key: 'spreadsheet', label: '表格' },
  { key: 'image',       label: '图片' },
  { key: 'gis_vector',  label: 'GIS矢量' },
  { key: 'gis_raster',  label: 'GIS栅格' },
  { key: 'mapgis',      label: 'MapGIS' },
  { key: 'fme',         label: 'FME' },
  { key: 'cad',         label: 'CAD' },
  { key: 'survey',      label: '测量数据' },
  { key: 'archive',     label: '压缩包' },
];

// ──────────────────────────────────────────────
// 模块状态
// ──────────────────────────────────────────────
let _searchState = {
  query: '',
  type: '',
  sort: 'relevance',
  page: 1,
  pageSize: 20,
  results: [],
  totalResults: 0,
  totalPages: 0,
  isLoading: false,
};

let _searchTimer = null;

// ──────────────────────────────────────────────
// 初始化
// ──────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  _initSearchInput();
  _initTypeFilters();
  _initSortControl();
  _initPagination();
  _initGlobalKeyboardShortcuts();

  // 监听来自 dashboard 的搜索请求
  document.addEventListener('app:searchRequested', e => {
    const { q, type } = e.detail;
    if (q !== undefined) {
      _searchState.query = q;
      const input = document.getElementById('search-input');
      if (input) { input.value = q; _updateClearButton(); }
    }
    if (type !== undefined) {
      _searchState.type = type;
      _updateFilterUI();
    }
    _searchState.page = 1;
    _doSearch();
  });

  // 切换到搜索视图时，自动聚焦搜索框
  document.addEventListener('app:viewChanged', e => {
    if (e.detail.view === 'search') {
      setTimeout(() => document.getElementById('search-input')?.focus(), 50);
    }
  });
});

// ──────────────────────────────────────────────
// 搜索输入框
// ──────────────────────────────────────────────
function _initSearchInput() {
  const input = document.getElementById('search-input');
  const clearBtn = document.getElementById('search-clear-btn');

  if (!input) return;

  // 输入事件：防抖处理
  input.addEventListener('input', e => {
    _searchState.query = e.target.value.trim();
    _updateClearButton();

    if (_searchTimer) clearTimeout(_searchTimer);

    if (_searchState.query.length > 0) {
      _searchTimer = setTimeout(() => {
        _searchState.page = 1;
        _doSearch();
      }, 300);
    } else if (!_searchState.type) {
      _showEmptyState();
    }
  });

  // 回车搜索
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter') {
      e.preventDefault();
      if (_searchTimer) clearTimeout(_searchTimer);
      _searchState.page = 1;
      _doSearch();
    }
  });

  // 清除按钮
  if (clearBtn) {
    clearBtn.addEventListener('click', () => {
      input.value = '';
      _searchState.query = '';
      _searchState.page = 1;
      _updateClearButton();
      input.focus();
      // 如果有 type 筛选，仍然按类型浏览；否则显示空状态
      if (_searchState.type) {
        _doSearch();
      } else {
        _showEmptyState();
      }
    });
  }
}

function _updateClearButton() {
  const clearBtn = document.getElementById('search-clear-btn');
  const input = document.getElementById('search-input');
  if (clearBtn && input) {
    clearBtn.classList.toggle('hidden', !input.value);
  }
}

// ──────────────────────────────────────────────
// 类型筛选标签
// ──────────────────────────────────────────────
function _initTypeFilters() {
  const container = document.getElementById('search-type-filters');
  if (!container) return;

  // 定义颜色映射
  const colorMap = {
    all:         { bg: '#FFFFFF', border: '#DDD8D0', text: '#6B6560' },
    document:    { bg: '#E0E7FF', border: '#4338CA', text: '#4338CA' },
    spreadsheet: { bg: '#DCFCE7', border: '#15803D', text: '#15803D' },
    image:       { bg: '#FDF2F8', border: '#BE185D', text: '#BE185D' },
    gis_vector:  { bg: '#D1FAE5', border: '#059669', text: '#059669' },
    gis_raster:  { bg: '#EDE9FE', border: '#7C3AED', text: '#7C3AED' },
    mapgis:      { bg: '#CFFAFE', border: '#0E7490', text: '#0E7490' },
    fme:         { bg: '#FED7AA', border: '#C2410C', text: '#C2410C' },
    cad:         { bg: '#DBEAFE', border: '#1D4ED8', text: '#1D4ED8' },
    survey:      { bg: '#FEF08A', border: '#A16207', text: '#A16207' },
    archive:     { bg: '#FEF3C7', border: '#92400E', text: '#92400E' },
  };

  container.innerHTML = TYPE_FILTERS.map((filter, idx) => {
    const colors = colorMap[filter.key] || { bg: '#F4F4F4', border: '#D1D5DB', text: '#6B7280' };

    return `
      <button
        data-type="${filter.key}"
        class="px-3 py-1.5 rounded-lg border transition-all duration-150 cursor-pointer text-xs font-medium hover:brightness-95"
        style="background-color: ${colors.bg}; border-color: ${colors.border}; color: ${colors.text}; opacity: 0.6;"
      >
        ${filter.label}
      </button>
    `;
  }).join('');

  // 绑定点击事件
  container.querySelectorAll('button').forEach(btn => {
    btn.addEventListener('click', () => {
      const type = btn.dataset.type;
      if (type === 'all') {
        _searchState.type = '';
      } else {
        _searchState.type = _searchState.type === type ? '' : type;
      }
      _updateFilterUI();
      _searchState.page = 1;
      _doSearch();
    });
  });

  _updateFilterUI();
}

function _updateFilterUI() {
  const container = document.getElementById('search-type-filters');
  if (!container) return;

  container.querySelectorAll('button').forEach(btn => {
    const type = btn.dataset.type;
    const isSelected = type === 'all' ? !_searchState.type : _searchState.type === type;

    // 更新样式
    if (isSelected) {
      btn.style.opacity = '1';
      btn.style.boxShadow = '0 0 0 2px white, 0 0 0 4px currentColor, 0 1px 2px rgba(45,41,38,0.08)';
      btn.style.fontWeight = '600';
    } else {
      btn.style.opacity = '0.6';
      btn.style.boxShadow = 'none';
      btn.style.fontWeight = '500';
    }
  });
}

// ──────────────────────────────────────────────
// 排序控制
// ──────────────────────────────────────────────
function _initSortControl() {
  const select = document.getElementById('search-sort');
  if (!select) return;

  select.addEventListener('change', e => {
    _searchState.sort = e.target.value;
    _searchState.page = 1;
    _doSearch();
  });
}

// ──────────────────────────────────────────────
// 分页
// ──────────────────────────────────────────────
function _initPagination() {
  document.getElementById('search-prev-page')?.addEventListener('click', () => {
    if (_searchState.page > 1) {
      _searchState.page--;
      _doSearch();
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }
  });

  document.getElementById('search-next-page')?.addEventListener('click', () => {
    if (_searchState.page < _searchState.totalPages) {
      _searchState.page++;
      _doSearch();
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }
  });
}

function _updatePaginationUI() {
  const pagination = document.getElementById('search-pagination');
  const prevBtn = document.getElementById('search-prev-page');
  const nextBtn = document.getElementById('search-next-page');
  const currentPageEl = document.getElementById('search-current-page');
  const totalPagesEl = document.getElementById('search-total-pages');

  if (pagination && _searchState.totalPages > 1) {
    pagination.classList.remove('hidden');
    if (prevBtn) prevBtn.disabled = _searchState.page <= 1;
    if (nextBtn) nextBtn.disabled = _searchState.page >= _searchState.totalPages;
    if (currentPageEl) currentPageEl.textContent = _searchState.page;
    if (totalPagesEl) totalPagesEl.textContent = _searchState.totalPages;
  } else if (pagination) {
    pagination.classList.add('hidden');
  }
}

// ──────────────────────────────────────────────
// 搜索请求
// ──────────────────────────────────────────────
async function _doSearch() {
  if (!_searchState.query && !_searchState.type) {
    _showEmptyState();
    return;
  }

  _searchState.isLoading = true;
  _showLoading();

  try {
    const params = new URLSearchParams({
      q: _searchState.query,
      type: _searchState.type,
      sort: _searchState.sort,
      page: _searchState.page,
      size: _searchState.pageSize,
    });

    const url = `${App.API_BASE}/api/search?${params}`;
    const res = await fetch(url);

    if (!res.ok) {
      const errData = await res.text();
      App.showToast(`搜索失败 (${res.status}): ${res.statusText}`, 'error');
      _showEmptyResults();
      return;
    }

    const data = await res.json();

    _searchState.results = data.items || data.results || [];
    _searchState.totalResults = data.total || 0;
    _searchState.totalPages = Math.ceil(_searchState.totalResults / _searchState.pageSize) || 1;

    if (_searchState.results.length === 0) {
      _showEmptyResults();
    } else {
      _renderResults();
      _updatePaginationUI();
      _showResultsSection();
    }

  } catch (err) {
    App.showToast(`搜索失败: ${err.message}`, 'error');
    _showEmptyResults();
  } finally {
    _searchState.isLoading = false;
  }
}

// ──────────────────────────────────────────────
// 渲染搜索结果
// ──────────────────────────────────────────────
function _renderResults() {
  const resultsList = document.getElementById('search-results-list');
  const header = document.getElementById('search-result-header');

  if (!resultsList) return;

  if (_searchState.results.length === 0) {
    _showEmptyResults();
    return;
  }

  resultsList.innerHTML = _searchState.results.map((file) => {
    const cfg = FILE_TYPE_CONFIG[file.file_type] || FILE_TYPE_CONFIG.other;
    // API 返回 file_path 而不是 path
    const filePath = file.file_path || file.path || '';
    // 优先使用 parent_dir，否则从 file_path 中提取
    const parentPath = file.parent_dir ? _getParentPath(file.parent_dir) : _getParentPath(filePath);
    const modTime = _fmtDate(file.modified_time);
    // API 返回 file_size 而不是 size
    const fileSize = _fmtSize(file.file_size || file.size);
    // API 返回 file_name 而不是 name
    const fileName = _highlightQuery(file.file_name || file.name, _searchState.query);

    // Shapefile 分组处理
    let shapefileMarker = '';
    if (file.shapefile_group && file.related_count && file.related_count > 0) {
      shapefileMarker = `<span class="text-xs text-stone-400 ml-2">Shapefile（含 ${file.related_count} 个关联文件）</span>`;
    }

    return `
      <div class="group flex items-center gap-3 px-4 py-3 rounded-xl bg-white border border-stone-100 hover:border-stone-200 hover:bg-stone-50 hover:shadow-warm-sm transition-all duration-150 cursor-pointer">
        <!-- 左侧类型色条 + 图标 -->
        <div class="w-1 h-10 rounded-full flex-shrink-0" style="background-color: ${cfg.barColor}"></div>
        <div class="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0 ${cfg.bgClass}">
          <i data-lucide="${cfg.icon}" class="w-5 h-5 ${cfg.textClass}"></i>
        </div>

        <!-- 文件信息（左侧） -->
        <div class="flex-1 min-w-0 cursor-pointer" onclick="Preview.show('${file.id}'); event.stopPropagation();">
          <div class="flex items-center gap-2">
            <p class="text-sm font-medium text-stone-800 truncate group-hover:text-blue-600 transition-colors">${fileName}</p>
            ${shapefileMarker}
          </div>
          <p class="text-xs text-stone-400 truncate mt-0.5">${parentPath}</p>
        </div>

        <!-- 右侧元数据 -->
        <div class="flex-shrink-0 text-right mr-3">
          <span class="text-xs text-stone-500 font-mono tabular-nums block">${fileSize}</span>
          <span class="text-xs text-stone-400 block mt-0.5">${modTime}</span>
        </div>

        <!-- 操作按钮（hover 显示） -->
        <div class="flex-shrink-0 opacity-0 group-hover:opacity-100 transition-opacity duration-150 flex gap-1">
          <button
            aria-label="打开文件"
            class="p-1.5 rounded-md hover:bg-stone-100 cursor-pointer text-stone-400 hover:text-stone-700 transition-colors"
            onclick="Search.openFile('${file.id}', event)"
          >
            <i data-lucide="external-link" class="w-4 h-4"></i>
          </button>
          <button
            aria-label="打开所在文件夹"
            class="p-1.5 rounded-md hover:bg-stone-100 cursor-pointer text-stone-400 hover:text-stone-700 transition-colors"
            onclick="Search.openDir('${file.id}', event)"
          >
            <i data-lucide="folder-open" class="w-4 h-4"></i>
          </button>
          <button
            aria-label="复制路径"
            class="p-1.5 rounded-md hover:bg-stone-100 cursor-pointer text-stone-400 hover:text-stone-700 transition-colors"
            onclick="Search.copyPath('${file.id}', event)"
          >
            <i data-lucide="clipboard-copy" class="w-4 h-4"></i>
          </button>
        </div>
      </div>
    `;
  }).join('');

  // 刷新 Lucide 图标
  lucide.createIcons({ nodes: [resultsList] });

  // 显示结果计数
  if (header) {
    header.classList.remove('hidden');
    const countEl = document.getElementById('search-result-count');
    if (countEl) countEl.textContent = _searchState.totalResults.toLocaleString();
  }
}

// ──────────────────────────────────────────────
// 高亮关键词（先转义 HTML，再高亮）
// ──────────────────────────────────────────────
function _highlightQuery(text, query) {
  if (!text) return '';
  // 先转义 HTML，防止 XSS
  const escaped = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
  if (!query || query.length === 0) return escaped;
  // 转义正则特殊字符
  const safeQuery = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const regex = new RegExp(`(${safeQuery})`, 'gi');
  return escaped.replace(regex, '<strong class="text-blue-600 font-semibold">$1</strong>');
}

// ──────────────────────────────────────────────
// 文件操作
// ──────────────────────────────────────────────
async function _openFile(fileId) {
  try {
    const res = await fetch(`${App.API_BASE}/api/files/${fileId}/open`, {
      method: 'POST',
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      const msg = err.detail || `打开文件失败（${res.status}）`;
      App.showToast(msg, 'error');
    } else {
      App.showToast('已打开文件', 'success', 2000);
    }
  } catch (err) {
    App.showToast('无法连接后端服务', 'error');
  }
}

async function _openDir(fileId) {
  try {
    const res = await fetch(`${App.API_BASE}/api/files/${fileId}/open-dir`, {
      method: 'POST',
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      const msg = err.detail || `打开文件夹失败（${res.status}）`;
      App.showToast(msg, 'error');
    } else {
      App.showToast('已打开文件夹', 'success', 2000);
    }
  } catch (err) {
    App.showToast('无法连接后端服务', 'error');
  }
}

async function _copyPath(fileId) {
  try {
    const res = await fetch(`${App.API_BASE}/api/files/${fileId}/path`);
    if (!res.ok) throw new Error(`获取路径失败 (${res.status})`);

    const data = await res.json();
    const path = data.file_path || data.path || '';

    if (!path) {
      App.showToast('无法获取文件路径', 'error');
      return;
    }

    await navigator.clipboard.writeText(path);
    App.showToast('已复制路径', 'success', 2000);
  } catch (err) {
    App.showToast(`复制失败: ${err.message}`, 'error');
  }
}

// ──────────────────────────────────────────────
// UI 状态切换
// ──────────────────────────────────────────────
function _showLoading() {
  const skeleton = document.getElementById('search-skeleton');
  const resultsList = document.getElementById('search-results-list');
  const header = document.getElementById('search-result-header');
  const pagination = document.getElementById('search-pagination');

  if (skeleton) skeleton.classList.remove('hidden');
  if (resultsList) resultsList.innerHTML = '';
  if (header) header.classList.add('hidden');
  if (pagination) pagination.classList.add('hidden');

  const emptyIdle = document.getElementById('search-empty-idle');
  const emptyResults = document.getElementById('search-empty-results');
  if (emptyIdle) emptyIdle.classList.add('hidden');
  if (emptyResults) emptyResults.classList.add('hidden');
}

function _showEmptyState() {
  const emptyIdle = document.getElementById('search-empty-idle');
  const emptyResults = document.getElementById('search-empty-results');
  const skeleton = document.getElementById('search-skeleton');
  const header = document.getElementById('search-result-header');
  const pagination = document.getElementById('search-pagination');
  const resultsList = document.getElementById('search-results-list');

  if (emptyIdle) emptyIdle.classList.remove('hidden');
  if (emptyResults) emptyResults.classList.add('hidden');
  if (skeleton) skeleton.classList.add('hidden');
  if (header) header.classList.add('hidden');
  if (pagination) pagination.classList.add('hidden');
  if (resultsList) resultsList.innerHTML = '';
}

function _showEmptyResults() {
  const emptyIdle = document.getElementById('search-empty-idle');
  const emptyResults = document.getElementById('search-empty-results');
  const skeleton = document.getElementById('search-skeleton');
  const header = document.getElementById('search-result-header');
  const pagination = document.getElementById('search-pagination');
  const resultsList = document.getElementById('search-results-list');

  if (emptyIdle) emptyIdle.classList.add('hidden');
  if (emptyResults) emptyResults.classList.remove('hidden');
  if (skeleton) skeleton.classList.add('hidden');
  if (header) header.classList.add('hidden');
  if (pagination) pagination.classList.add('hidden');
  if (resultsList) resultsList.innerHTML = '';
}

function _showResultsSection() {
  const emptyIdle = document.getElementById('search-empty-idle');
  const emptyResults = document.getElementById('search-empty-results');
  const skeleton = document.getElementById('search-skeleton');

  if (emptyIdle) emptyIdle.classList.add('hidden');
  if (emptyResults) emptyResults.classList.add('hidden');
  if (skeleton) skeleton.classList.add('hidden');
}

// ──────────────────────────────────────────────
// 全局键盘快捷键
// ──────────────────────────────────────────────
function _initGlobalKeyboardShortcuts() {
  document.addEventListener('keydown', e => {
    // "/" 聚焦搜索框（在输入框内按 / 时忽略）
    if (e.key === '/' && !e.ctrlKey && !e.metaKey && !e.shiftKey) {
      const activeEl = document.activeElement;
      const isEditable = activeEl && (
        activeEl.tagName === 'INPUT' ||
        activeEl.tagName === 'TEXTAREA' ||
        activeEl.isContentEditable
      );
      if (!isEditable) {
        e.preventDefault();
        if (App.currentView !== 'search') {
          App.switchView('search');
          setTimeout(() => document.getElementById('search-input')?.focus(), 60);
        } else {
          document.getElementById('search-input')?.focus();
        }
      }
    }
  });
}

// ──────────────────────────────────────────────
// 工具函数
// ──────────────────────────────────────────────
function _fmtSize(bytes) {
  if (!bytes && bytes !== 0) return '--';
  if (bytes === 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0, v = bytes;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

function _fmtDate(iso) {
  if (!iso) return '--';
  try {
    const d = new Date(iso);
    const pad = n => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  } catch { return iso; }
}

function _getParentPath(fullPath) {
  if (!fullPath) return '';
  // 返回末尾两级路径
  const parts = fullPath.replace(/\\/g, '/').split('/').filter(p => p);
  if (parts.length <= 2) return fullPath;
  return parts.slice(-2).join('/');
}

// ──────────────────────────────────────────────
// 公共 API
// ──────────────────────────────────────────────
window.Search = {
  openFile(fileId, e) {
    e.preventDefault();
    e.stopPropagation();
    _openFile(fileId);
  },
  openDir(fileId, e) {
    e.preventDefault();
    e.stopPropagation();
    _openDir(fileId);
  },
  copyPath(fileId, e) {
    e.preventDefault();
    e.stopPropagation();
    _copyPath(fileId);
  },
};
