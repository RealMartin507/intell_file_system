/**
 * dashboard.js — 仪表盘模块
 * 依赖：window.App（由 app.js 提供）
 */

// ──────────────────────────────────────────────
// 文件类型视觉配置（与设计系统 MASTER.md 对齐）
// ──────────────────────────────────────────────
const FILE_TYPE_CFG = {
  gis_vector:  { label: 'GIS 矢量', color: '#059669' },
  gis_raster:  { label: 'GIS 栅格', color: '#7C3AED' },
  mapgis:      { label: 'MapGIS',   color: '#0E7490' },
  fme:         { label: 'FME',      color: '#C2410C' },
  survey:      { label: '测量数据', color: '#A16207' },
  cad:         { label: 'CAD',      color: '#1D4ED8' },
  image:       { label: '图片',     color: '#BE185D' },
  document:    { label: '文档',     color: '#4338CA' },
  spreadsheet: { label: '表格',     color: '#15803D' },
  video:       { label: '视频',     color: '#9D174D' },
  audio:       { label: '音频',     color: '#6D28D9' },
  archive:     { label: '压缩包',   color: '#92400E' },
  other:       { label: '其他',     color: '#57534E' },
};

// ──────────────────────────────────────────────
// 模块状态
// ──────────────────────────────────────────────
let _typeChart    = null;   // Chart.js 实例
let _typeData     = [];     // 当前类型分布数据
let _scanTimer    = null;   // 轮询定时器
let _isScanning   = false;

// 终端相关
let _terminalLines        = [];
const _MAX_TERM_LINES     = 200;
let _terminalUserScrolled = false;
let _lastTermPhase        = '';
let _lastTermDir          = '';

// ──────────────────────────────────────────────
// 初始化
// ──────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  _initQuickSearch();
  _initScanControls();
  _loadDashboard();
  _loadScanRootFromConfig();

  // 检查是否有扫描正在进行
  _pollOnce();
});

// 切换到仪表盘时刷新
document.addEventListener('app:viewChanged', (e) => {
  if (e.detail.view === 'dashboard') {
    _loadDashboard();
    _loadScanRootFromConfig();
  }
});

// 设置页保存扫描路径后立即同步输入框
document.addEventListener('app:configChanged', (e) => {
  const roots = e.detail?.scan_roots || [];
  if (roots.length === 0) return;
  const first = roots[0];
  const path = typeof first === 'string' ? first : (first.path || '');
  const input = document.getElementById('scan-root-input');
  if (input && path) input.value = path;
});

// ──────────────────────────────────────────────
// 数据加载
// ──────────────────────────────────────────────
async function _loadDashboard() {
  const base = App.API_BASE;
  const [overviewRes, typesRes, logsRes] = await Promise.allSettled([
    fetch(`${base}/api/stats/overview`).then(r => r.ok ? r.json() : Promise.reject(r.status)),
    fetch(`${base}/api/stats/types`).then(r => r.ok ? r.json() : Promise.reject(r.status)),
    fetch(`${base}/api/scan/logs`).then(r => r.ok ? r.json() : Promise.reject(r.status)),
  ]);

  if (overviewRes.status === 'fulfilled') {
    _renderOverview(overviewRes.value);
  } else {
    _renderOverviewEmpty();
  }

  if (typesRes.status === 'fulfilled') {
    _renderTypeChart(typesRes.value);
    _renderKpiSize(typesRes.value);
  } else {
    _showTypeChartEmpty();
  }

  if (logsRes.status === 'fulfilled') {
    const logs = Array.isArray(logsRes.value) ? logsRes.value : (logsRes.value.logs || []);
    _renderScanLogs(logs);
    if (logs.length > 0) _renderKpiChanges(logs[0]);
  } else {
    _renderScanLogsEmpty();
  }
}

// ──────────────────────────────────────────────
// KPI 渲染
// ──────────────────────────────────────────────
function _renderOverview(data) {
  _setText('kpi-total', _fmtNum(data.total_files));

  const lastScan = data.last_scan ? `上次扫描：${_fmtDate(data.last_scan)}` : '尚未扫描';
  _setText('kpi-last-scan', lastScan);

  _setText('kpi-db-size', data.db_size_mb != null ? `${data.db_size_mb.toFixed(1)} MB` : '--');
}

function _renderOverviewEmpty() {
  ['kpi-total', 'kpi-last-scan', 'kpi-db-size'].forEach(id => _setText(id, '--'));
}

function _renderKpiSize(typesData) {
  const dist = typesData.distribution || [];
  const totalBytes = dist.reduce((s, d) => s + (d.total_size || 0), 0);
  const typeCount  = dist.filter(d => d.count > 0).length;

  _setText('kpi-size', _fmtSize(totalBytes));
  _setText('kpi-size-sub', `${typeCount} 个文件类型`);

  // 进度条：以 1TB 为满格参考
  const pct = Math.min(100, (totalBytes / (1024 ** 4)) * 100);
  const bar = document.getElementById('kpi-size-bar');
  if (bar) bar.style.width = `${Math.max(2, pct)}%`;
}

function _renderKpiChanges(log) {
  _setText('kpi-added',    _fmtNum(log.files_added    ?? log.added    ?? 0));
  _setText('kpi-deleted',  _fmtNum(log.files_deleted  ?? log.deleted  ?? 0));
  _setText('kpi-modified', _fmtNum(log.files_modified ?? log.modified ?? 0));
  _setText('kpi-changes-time', _fmtDate(log.start_time ?? log.started_at));
}

// ──────────────────────────────────────────────
// 文件类型分布图（Chart.js 水平柱状图）
// ──────────────────────────────────────────────
function _renderTypeChart(typesData) {
  const dist = (typesData.distribution || [])
    .filter(d => d.count > 0)
    .sort((a, b) => b.count - a.count);

  _typeData = dist;

  if (dist.length === 0) { _showTypeChartEmpty(); return; }

  document.getElementById('type-chart-wrap')?.classList.remove('hidden');
  document.getElementById('type-chart-empty')?.classList.add('hidden');

  const labels = dist.map(d => (FILE_TYPE_CFG[d.file_type] || { label: d.file_type }).label);
  const counts = dist.map(d => d.count);
  const colors = dist.map(d => (FILE_TYPE_CFG[d.file_type] || { color: '#57534E' }).color);

  const canvas = document.getElementById('type-chart');
  if (!canvas) return;

  if (_typeChart) { _typeChart.destroy(); _typeChart = null; }

  // 动态调整容器高度（每行 40px + 上下 padding）
  const rowHeight = 40;
  const newHeight = Math.max(200, dist.length * rowHeight + 40);
  const wrap = document.getElementById('type-chart-wrap');
  if (wrap) wrap.style.height = `${newHeight}px`;

  _typeChart = new Chart(canvas, {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        data: counts,
        backgroundColor: colors.map(c => c + 'CC'),
        borderColor: colors,
        borderWidth: 1,
        borderRadius: 4,
        borderSkipped: false,
      }],
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: ctx => ` ${ctx.parsed.x.toLocaleString()} 个文件`,
          },
          backgroundColor: '#1C1917',
          padding: 10,
          bodyFont: { size: 12, family: 'monospace' },
        },
      },
      scales: {
        x: {
          grid: { color: 'rgba(168,162,158,0.15)', drawTicks: false },
          border: { dash: [4, 4] },
          ticks: {
            color: '#A8A29E',
            font: { size: 11 },
            callback: v => v >= 1000 ? `${(v / 1000).toFixed(0)}k` : v,
          },
        },
        y: {
          grid: { display: false },
          ticks: {
            color: '#57534E',
            font: { size: 12 },
          },
        },
      },
      onClick: (_evt, elements) => {
        if (elements.length > 0) {
          Dashboard.filterByType(_typeData[elements[0].index]?.file_type);
        }
      },
      animation: { duration: 400, easing: 'easeOutQuart' },
    },
  });
}

function _showTypeChartEmpty() {
  document.getElementById('type-chart-wrap')?.classList.add('hidden');
  const empty = document.getElementById('type-chart-empty');
  if (empty) { empty.classList.remove('hidden'); empty.classList.add('flex'); }
}

// ──────────────────────────────────────────────
// 扫描历史表格
// ──────────────────────────────────────────────
const _SCAN_TYPE_LABEL = { full: '全量', incremental: '增量' };
const _SCAN_STATUS_BADGE = {
  completed: `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-green-50 text-green-700 border border-green-200"><span class="w-1.5 h-1.5 rounded-full bg-green-500"></span>完成</span>`,
  running:   `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-blue-50 text-blue-700 border border-blue-200"><span class="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse"></span>进行中</span>`,
  failed:    `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-red-50 text-red-700 border border-red-200"><span class="w-1.5 h-1.5 rounded-full bg-red-500"></span>失败</span>`,
};

function _renderScanLogs(logs) {
  const tbody = document.getElementById('scan-logs-body');
  if (!tbody) return;

  if (!logs || logs.length === 0) { _renderScanLogsEmpty(); return; }

  const recent = logs.slice(0, 8);
  tbody.innerHTML = recent.map(log => {
    const added    = log.files_added    ?? log.added    ?? 0;
    const deleted  = log.files_deleted  ?? log.deleted  ?? 0;
    const modified = log.files_modified ?? log.modified ?? 0;
    const changes  = `<span class="text-green-600">+${added}</span> <span class="text-red-500">-${deleted}</span> <span class="text-amber-500">~${modified}</span>`;
    const typeLabel = _SCAN_TYPE_LABEL[log.scan_type] || log.scan_type;
    const badge    = _SCAN_STATUS_BADGE[log.status] || `<span class="text-xs text-stone-400">${log.status || '--'}</span>`;

    const rootPath  = log.root_path || '--';
    const shortPath = _shortenPath(rootPath, 45);

    // 计算耗时
    let elapsed = '';
    if (log.started_at && log.finished_at) {
      const sec = Math.round((new Date(log.finished_at) - new Date(log.started_at)) / 1000);
      elapsed = sec >= 60 ? `${Math.floor(sec/60)}m${sec%60}s` : `${sec}s`;
    }

    return `
      <tr class="hover:bg-stone-50 transition-colors duration-100">
        <td class="py-3 pr-3 text-xs text-stone-500 whitespace-nowrap">${_fmtDate(log.start_time ?? log.started_at)}</td>
        <td class="py-3 pr-3 max-w-xs">
          <span class="text-xs font-mono text-stone-600 truncate block" title="${rootPath}">${shortPath}</span>
        </td>
        <td class="py-3 pr-3 whitespace-nowrap">
          <span class="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium ${log.scan_type === 'full' ? 'bg-blue-50 text-blue-700' : 'bg-stone-100 text-stone-600'}">
            ${typeLabel}
          </span>
        </td>
        <td class="py-3 pr-3 text-center text-xs font-mono whitespace-nowrap">${changes}</td>
        <td class="py-3 text-right whitespace-nowrap">
          ${badge}
          ${elapsed ? `<div class="text-[10px] text-stone-400 mt-0.5">${elapsed}</div>` : ''}
        </td>
      </tr>`;
  }).join('');
}

function _renderScanLogsEmpty() {
  const tbody = document.getElementById('scan-logs-body');
  if (tbody) tbody.innerHTML = `<tr><td colspan="5" class="py-8 text-center text-sm text-stone-400">暂无扫描记录</td></tr>`;
}

// ──────────────────────────────────────────────
// 快速搜索
// ──────────────────────────────────────────────
function _initQuickSearch() {
  const input = document.getElementById('dash-search-input');
  const btn   = document.getElementById('dash-search-btn');
  if (!input || !btn) return;

  const doSearch = () => {
    const q = input.value.trim();
    document.dispatchEvent(new CustomEvent('app:searchRequested', { detail: { q, type: '' } }));
    App.switchView('search');
  };

  input.addEventListener('keydown', e => { if (e.key === 'Enter') doSearch(); });
  btn.addEventListener('click', doSearch);
}

// ──────────────────────────────────────────────
// 扫描控制
// ──────────────────────────────────────────────
function _initScanControls() {
  document.getElementById('btn-full-scan')?.addEventListener('click',        () => _startScan('full'));
  document.getElementById('btn-incremental-scan')?.addEventListener('click', () => _startScan('incremental'));

  // 顶部全局扫描按钮：切到仪表盘后滚动到扫描区
  document.getElementById('btn-scan')?.addEventListener('click', () => {
    if (App.currentView === 'dashboard') {
      document.getElementById('btn-full-scan')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  });

  // 监听终端滚动，用户手动滚动时暂停自动滚到底部
  const terminal = document.getElementById('scan-terminal');
  if (terminal) {
    terminal.addEventListener('scroll', () => {
      const atBottom = terminal.scrollHeight - terminal.scrollTop - terminal.clientHeight < 10;
      _terminalUserScrolled = !atBottom;
    });
  }
}

async function _loadScanRootFromConfig() {
  try {
    const res = await fetch(`${App.API_BASE}/api/config`);
    if (!res.ok) return;
    const cfg = await res.json();
    const roots = cfg.scan_roots || [];
    if (roots.length === 0) return;
    const first = roots[0];
    const path = typeof first === 'string' ? first : (first.path || '');
    const input = document.getElementById('scan-root-input');
    if (input && path) input.value = path;
  } catch { /* 加载失败静默忽略 */ }
}

async function _startScan(scanType) {
  if (_isScanning) return;

  const rootPath = (document.getElementById('scan-root-input')?.value || '').trim();
  if (!rootPath) { App.showToast('请先在设置中添加扫描路径，或在输入框中填写路径', 'warning'); return; }

  _isScanning = true;
  _setScanningUI(true);

  // 清空终端并写入启动消息
  _termClear();
  _termWrite(`启动${scanType === 'full' ? '全量' : '增量'}扫描：${rootPath}`, 'info');

  try {
    const res = await fetch(`${App.API_BASE}/api/scan/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ root_path: rootPath, scan_type: scanType }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      _isScanning = false;
      _setScanningUI(false);
      _termWrite(`启动失败：${err.detail || res.status}`, 'error');
      App.showToast(err.detail || `启动扫描失败（${res.status}）`, 'error');
      return;
    }

    const result = await res.json().catch(() => ({}));
    const actualType = (result.scan_type || scanType).includes('incremental') ? '增量' : '全量';
    _termWrite(`${actualType}扫描任务已提交，开始监控进度...`, 'dim');
    App.showToast(`${actualType}扫描已启动`, 'success');
    _startPolling();

  } catch (e) {
    _isScanning = false;
    _setScanningUI(false);
    _termWrite('无法连接后端服务，请确认服务已启动（端口 8000）', 'error');
    App.showToast('无法连接后端服务，请确认服务已启动（端口 8000）', 'error');
  }
}

// ──────────────────────────────────────────────
// 扫描进度轮询
// ──────────────────────────────────────────────
async function _pollOnce() {
  try {
    const res  = await fetch(`${App.API_BASE}/api/scan/status`);
    if (!res.ok) return;
    const data = await res.json();
    if (data.status === 'running') {
      _isScanning = true;
      _setScanningUI(true);
      _termWrite('检测到扫描正在进行中，接管进度监控...', 'dim');
      _updateProgress(data);
      _startPolling();
    }
  } catch { /* 后端离线，忽略 */ }
}

function _startPolling() {
  if (_scanTimer) return;
  _scanTimer = setInterval(_doPoll, 1000);
}

async function _doPoll() {
  try {
    const res  = await fetch(`${App.API_BASE}/api/scan/status`);
    if (!res.ok) { _onScanError(); return; }
    const data = await res.json();

    if (data.status === 'running') {
      _updateProgress(data);
    } else {
      _onScanComplete(data);
    }
  } catch {
    _onScanError();
  }
}

function _updateProgress(data) {
  const isMft = data.scan_method === 'mft';

  // 更新终端顶栏 badge
  const badge = document.getElementById('scan-method-badge');
  if (badge) {
    badge.textContent = isMft ? '⚡ MFT 直读' : '📂 普通扫描';
    badge.className = isMft
      ? 'ml-auto px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-900/60 text-amber-400 whitespace-nowrap'
      : 'ml-auto px-1.5 py-0.5 rounded text-[10px] font-medium bg-blue-900/60 text-blue-400 whitespace-nowrap';
  }

  // 阶段变化时写入终端
  const phase = data.current_phase || '';
  if (phase && phase !== _lastTermPhase) {
    _termWrite(`[阶段] ${phase}`, 'warn');
    _lastTermPhase = phase;
  }

  // 当前目录变化时写入终端
  const dir = data.current_dir || '';
  if (dir && dir !== _lastTermDir) {
    _termWrite(dir, 'path');
    _lastTermDir = dir;
  }

  // 原地刷新文件计数行
  _termUpdateCount(data.scanned_count, data.added, data.deleted, data.modified);
}

function _onScanComplete(data) {
  _stopPolling();
  _setScanningUI(false);
  _lastTermPhase = '';
  _lastTermDir   = '';

  const added    = _fmtNum(data.added    ?? 0);
  const deleted  = _fmtNum(data.deleted  ?? 0);
  const modified = _fmtNum(data.modified ?? 0);

  _termWrite('─'.repeat(50), 'dim');
  _termWrite(`扫描完成  新增 ${added}  删除 ${deleted}  修改 ${modified}`, 'success');
  App.showToast(`扫描完成！新增 ${added}，删除 ${deleted}，修改 ${modified}`, 'success', 5000);

  _loadDashboard();
}

function _onScanError() {
  _stopPolling();
  _setScanningUI(false);
  _lastTermPhase = '';
  _lastTermDir   = '';
  _termWrite('扫描状态获取失败，请检查后端服务', 'error');
  App.showToast('扫描状态获取失败，请检查后端服务', 'error');
}

function _stopPolling() {
  if (_scanTimer) { clearInterval(_scanTimer); _scanTimer = null; }
  _isScanning = false;
}

function _setScanningUI(scanning) {
  _isScanning = scanning;

  const fullBtn = document.getElementById('btn-full-scan');
  const incrBtn = document.getElementById('btn-incremental-scan');

  if (fullBtn) fullBtn.disabled = scanning;
  if (incrBtn) incrBtn.disabled = scanning;

  if (scanning && fullBtn) {
    const icon = fullBtn.querySelector('i[data-lucide]');
    if (icon) { icon.dataset.lucide = 'loader-2'; icon.classList.add('animate-spin'); lucide.createIcons({ nodes: [fullBtn] }); }
  } else if (!scanning && fullBtn) {
    const icon = fullBtn.querySelector('i[data-lucide]');
    if (icon) { icon.dataset.lucide = 'database'; icon.classList.remove('animate-spin'); lucide.createIcons({ nodes: [fullBtn] }); }
  }
}

// ──────────────────────────────────────────────
// CLI 终端函数
// ──────────────────────────────────────────────
const _TERM_COUNT_MARKER = 'data-role="count"';

function _termWrite(text, type = 'info') {
  const colorMap = {
    info:    'text-blue-600',
    success: 'text-emerald-600 font-semibold',
    warn:    'text-amber-600',
    dim:     'text-stone-400',
    path:    'text-stone-600',
    error:   'text-red-500',
  };
  const cls = colorMap[type] || 'text-blue-600';

  const now = new Date();
  const ts  = `${String(now.getHours()).padStart(2,'0')}:${String(now.getMinutes()).padStart(2,'0')}:${String(now.getSeconds()).padStart(2,'0')}`;

  // HTML 转义防 XSS
  const escaped = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

  const line = `<p class="${cls}"><span class="text-stone-300 select-none">[${ts}]</span> ${escaped}</p>`;

  _terminalLines.push(line);
  if (_terminalLines.length > _MAX_TERM_LINES) _terminalLines.shift();

  _termFlush();
}

function _termClear() {
  _terminalLines = [];
  _terminalUserScrolled = false;
  const body = document.getElementById('terminal-log-body');
  if (body) body.innerHTML = '<p class="text-stone-400 italic">等待扫描启动...</p>';
}

function _termUpdateCount(scanned, added, deleted, modified) {
  const text = `已扫描 ${_fmtNum(scanned ?? 0)} 个文件  ` +
    `<span class="text-emerald-600">+${added ?? 0}</span> ` +
    `<span class="text-red-500">-${deleted ?? 0}</span> ` +
    `<span class="text-amber-600">~${modified ?? 0}</span>`;

  const countLine = `<p class="text-stone-600" ${_TERM_COUNT_MARKER}>${text}</p>`;

  const lastIdx = _terminalLines.length - 1;
  if (lastIdx >= 0 && _terminalLines[lastIdx].includes(_TERM_COUNT_MARKER)) {
    _terminalLines[lastIdx] = countLine;
  } else {
    _terminalLines.push(countLine);
    if (_terminalLines.length > _MAX_TERM_LINES) _terminalLines.shift();
  }

  _termFlush();
}

function _termFlush() {
  const body = document.getElementById('terminal-log-body');
  if (!body) return;
  body.innerHTML = _terminalLines.join('');

  if (!_terminalUserScrolled) {
    const terminal = document.getElementById('scan-terminal');
    if (terminal) terminal.scrollTop = terminal.scrollHeight;
  }
}

// ──────────────────────────────────────────────
// 工具函数
// ──────────────────────────────────────────────
function _setText(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

function _fmtNum(n) {
  if (n === null || n === undefined) return '--';
  return Number(n).toLocaleString();
}

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

function _shortenPath(path, maxLen = 45) {
  if (!path || path === '--') return path;
  if (path.length <= maxLen) return path;
  const parts = path.replace(/\\/g, '/').split('/').filter(Boolean);
  if (parts.length <= 3) return path;
  return parts[0] + '/.../' + parts.slice(-2).join('/');
}

// ──────────────────────────────────────────────
// 公共 API
// ──────────────────────────────────────────────
window.Dashboard = {
  /** 点击图表跳转到搜索并筛选类型 */
  filterByType(fileType) {
    if (!fileType) return;
    document.dispatchEvent(new CustomEvent('app:searchRequested', { detail: { q: '', type: fileType } }));
    App.switchView('search');
  },
  reload: _loadDashboard,
};
