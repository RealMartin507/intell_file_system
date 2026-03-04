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

// ──────────────────────────────────────────────
// 初始化
// ──────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  _initQuickSearch();
  _initScanControls();
  _loadDashboard();

  // 检查是否有扫描正在进行
  _pollOnce();
});

// 切换到仪表盘时刷新
document.addEventListener('app:viewChanged', (e) => {
  if (e.detail.view === 'dashboard') _loadDashboard();
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
  // 文件总数
  _setText('kpi-total', _fmtNum(data.total_files));
  _setText('chart-center-num', _fmtNum(data.total_files));

  // 上次扫描时间
  const lastScan = data.last_scan ? `上次扫描：${_fmtDate(data.last_scan)}` : '尚未扫描';
  _setText('kpi-last-scan', lastScan);

  // 数据库大小
  _setText('kpi-db-size', data.db_size_mb != null ? `${data.db_size_mb.toFixed(1)} MB` : '--');
}

function _renderOverviewEmpty() {
  ['kpi-total', 'kpi-last-scan', 'kpi-db-size'].forEach(id => _setText(id, '--'));
  _setText('chart-center-num', '--');
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
  _setText('kpi-changes-time', log.start_time ? _fmtDate(log.start_time) : '--');
}

// ──────────────────────────────────────────────
// 文件类型分布图（Chart.js Donut）
// ──────────────────────────────────────────────
function _renderTypeChart(typesData) {
  const dist = (typesData.distribution || [])
    .filter(d => d.count > 0)
    .sort((a, b) => b.count - a.count);

  _typeData = dist;

  if (dist.length === 0) { _showTypeChartEmpty(); return; }

  document.getElementById('type-chart-wrap')?.classList.remove('hidden');
  document.getElementById('type-chart-empty')?.classList.add('hidden');

  const labels  = dist.map(d => (FILE_TYPE_CFG[d.file_type] || { label: d.file_type }).label);
  const counts  = dist.map(d => d.count);
  const colors  = dist.map(d => (FILE_TYPE_CFG[d.file_type] || { color: '#57534E' }).color);

  const canvas = document.getElementById('type-chart');
  if (!canvas) return;

  if (_typeChart) { _typeChart.destroy(); _typeChart = null; }

  _typeChart = new Chart(canvas, {
    type: 'doughnut',
    data: {
      labels,
      datasets: [{
        data: counts,
        backgroundColor: colors,
        borderWidth: 2,
        borderColor: '#FFFFFF',
        hoverBorderColor: '#FFFFFF',
        hoverOffset: 4,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      cutout: '68%',
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: ctx => ` ${ctx.label}：${ctx.parsed.toLocaleString()} 个`,
          },
          backgroundColor: '#1C1917',
          padding: 10,
          titleFont: { size: 12 },
          bodyFont: { size: 12 },
        },
      },
      onClick: (_evt, elements) => {
        if (elements.length > 0) {
          const idx = elements[0].index;
          Dashboard.filterByType(_typeData[idx]?.file_type);
        }
      },
      animation: { duration: 400 },
    },
  });

  _renderTypeLegend(dist);
}

function _renderTypeLegend(dist) {
  const legend = document.getElementById('type-legend');
  if (!legend) return;

  const total = dist.reduce((s, d) => s + d.count, 0);
  legend.innerHTML = dist.map(d => {
    const cfg  = FILE_TYPE_CFG[d.file_type] || { label: d.file_type, color: '#57534E' };
    const pct  = total > 0 ? ((d.count / total) * 100).toFixed(1) : '0.0';
    return `
      <button
        onclick="Dashboard.filterByType('${d.file_type}')"
        class="w-full flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-stone-50 transition-colors duration-100 cursor-pointer text-left group"
        title="点击筛选 ${cfg.label}"
      >
        <span class="w-2 h-2 rounded-full flex-shrink-0" style="background-color:${cfg.color}"></span>
        <span class="flex-1 text-xs text-stone-600 group-hover:text-stone-900 truncate transition-colors">${cfg.label}</span>
        <span class="text-xs font-mono text-stone-400 tabular-nums">${d.count.toLocaleString()}</span>
        <span class="text-xs text-stone-300 w-10 text-right tabular-nums">${pct}%</span>
      </button>`;
  }).join('');
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

  const recent = logs.slice(0, 5);
  tbody.innerHTML = recent.map(log => {
    const added    = log.files_added    ?? log.added    ?? 0;
    const deleted  = log.files_deleted  ?? log.deleted  ?? 0;
    const modified = log.files_modified ?? log.modified ?? 0;
    const changes  = `<span class="text-green-600">+${added}</span> <span class="text-red-500">-${deleted}</span> <span class="text-amber-500">~${modified}</span>`;
    const typeLabel = _SCAN_TYPE_LABEL[log.scan_type] || log.scan_type;
    const badge    = _SCAN_STATUS_BADGE[log.status] || `<span class="text-xs text-stone-400">${log.status || '--'}</span>`;

    return `
      <tr class="hover:bg-stone-50 transition-colors duration-100">
        <td class="py-3 pr-3 text-xs text-stone-500 whitespace-nowrap">${_fmtDate(log.start_time)}</td>
        <td class="py-3 pr-3">
          <span class="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium ${log.scan_type === 'full' ? 'bg-blue-50 text-blue-700' : 'bg-stone-100 text-stone-600'}">
            ${typeLabel}
          </span>
        </td>
        <td class="py-3 pr-3 text-center text-xs font-mono">${changes}</td>
        <td class="py-3 text-right">${badge}</td>
      </tr>`;
  }).join('');
}

function _renderScanLogsEmpty() {
  const tbody = document.getElementById('scan-logs-body');
  if (tbody) tbody.innerHTML = `<tr><td colspan="4" class="py-8 text-center text-sm text-stone-400">暂无扫描记录</td></tr>`;
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
    // 通知 search 模块执行搜索
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
    // app.js 会处理切换视图
  });
}

async function _startScan(scanType) {
  if (_isScanning) return;

  const rootPath = (document.getElementById('scan-root-input')?.value || 'E:\\').trim();
  if (!rootPath) { App.showToast('请输入扫描根目录', 'warning'); return; }

  // ── 立即给用户视觉反馈（同步，不等网络）──
  _isScanning = true;
  _setScanningUI(true);

  try {
    const res = await fetch(`${App.API_BASE}/api/scan/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ root_path: rootPath, scan_type: scanType }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      // 恢复 UI
      _isScanning = false;
      _setScanningUI(false);
      App.showToast(err.detail || `启动扫描失败（${res.status}）`, 'error');
      return;
    }

    const result = await res.json().catch(() => ({}));
    const actualType = (result.scan_type || scanType).includes('incremental') ? '增量' : '全量';
    App.showToast(`${actualType}扫描已启动`, 'success');
    _startPolling();

  } catch (e) {
    _isScanning = false;
    _setScanningUI(false);
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
    // 后端返回 status 字段（'running' / 'idle' / 'completed' / 'error'）
    if (data.status === 'running') {
      _isScanning = true;
      _setScanningUI(true);
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

    // 后端用 status 字段（不是 is_running）
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
  // 后端字段：scanned_count（不是 files_found），current_dir（不是 current_path）
  _setText('scan-count',        `${_fmtNum(data.scanned_count)} 个文件`);
  _setText('scan-current-path', data.current_dir || '扫描中...');
  _setText('scan-status-label', '扫描进行中...');
}

function _onScanComplete(data) {
  _stopPolling();
  _setScanningUI(false);

  const added    = _fmtNum(data.added    ?? 0);
  const deleted  = _fmtNum(data.deleted  ?? 0);
  const modified = _fmtNum(data.modified ?? 0);
  App.showToast(`扫描完成！新增 ${added}，删除 ${deleted}，修改 ${modified}`, 'success', 5000);

  // 刷新数据
  _loadDashboard();
}

function _onScanError() {
  _stopPolling();
  _setScanningUI(false);
  App.showToast('扫描状态获取失败，请检查后端服务', 'error');
}

function _stopPolling() {
  if (_scanTimer) { clearInterval(_scanTimer); _scanTimer = null; }
  _isScanning = false;
}

function _setScanningUI(scanning, scanType = '') {
  _isScanning = scanning;

  const fullBtn = document.getElementById('btn-full-scan');
  const incrBtn = document.getElementById('btn-incremental-scan');
  const panel   = document.getElementById('scan-progress-panel');

  if (fullBtn) fullBtn.disabled = scanning;
  if (incrBtn) incrBtn.disabled = scanning;

  // 扫描中：显示进度面板，更新按钮图标
  if (panel) {
    panel.classList.toggle('hidden', !scanning);
  }

  if (scanning && fullBtn) {
    const icon = fullBtn.querySelector('i[data-lucide]');
    if (icon) { icon.dataset.lucide = 'loader-2'; icon.classList.add('animate-spin'); lucide.createIcons({ nodes: [fullBtn] }); }
  } else if (!scanning && fullBtn) {
    const icon = fullBtn.querySelector('i[data-lucide]');
    if (icon) { icon.dataset.lucide = 'database'; icon.classList.remove('animate-spin'); lucide.createIcons({ nodes: [fullBtn] }); }
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

// ──────────────────────────────────────────────
// 公共 API
// ──────────────────────────────────────────────
window.Dashboard = {
  /** 点击图例 / 图表跳转到搜索并筛选类型 */
  filterByType(fileType) {
    if (!fileType) return;
    document.dispatchEvent(new CustomEvent('app:searchRequested', { detail: { q: '', type: fileType } }));
    App.switchView('search');
  },
  reload: _loadDashboard,
};
