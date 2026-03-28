/**
 * 设置页面模块
 * 管理扫描路径、排除规则、自动扫描、系统信息
 */

const Settings = {
  currentConfig: null,
  hasChanges: false,

  async init() {
    await this.loadConfig();
    // bindEvents 使用事件委托绑到 document，只需绑定一次
    if (!this._eventsBound) {
      this.bindEvents();
      this._eventsBound = true;
    }
    this.renderUI();
  },

  // ──────────────────────────────────────────────────────────────
  // 1. 加载配置数据
  // ──────────────────────────────────────────────────────────────
  async loadConfig() {
    try {
      const resp = await fetch('/api/config');
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      this.currentConfig = await resp.json();
    } catch (err) {
      App.showToast('加载配置失败：' + err.message, 'error');
      // 使用默认配置
      this.currentConfig = {
        scan_roots: [],
        exclude_dirs: ['$RECYCLE.BIN', 'System Volume Information', '.Trash'],
        exclude_patterns: ['~$*', '*.tmp', 'Thumbs.db', 'desktop.ini'],
        auto_scan_interval_minutes: 30,
      };
    }
  },

  // ──────────────────────────────────────────────────────────────
  // 2. 绑定事件
  // ──────────────────────────────────────────────────────────────
  bindEvents() {
    // 扫描路径管理
    document.addEventListener('click', (e) => {
      if (e.target.closest('#btn-add-scan-root')) this.showAddScanRootModal();
      if (e.target.closest('[data-remove-root]')) {
        const index = parseInt(e.target.closest('[data-remove-root]').dataset.removeRoot, 10);
        this.removeScanRoot(index);
      }
      if (e.target.closest('[data-remove-exclude-dir]')) {
        const index = parseInt(e.target.closest('[data-remove-exclude-dir]').dataset.removeExcludeDir, 10);
        this.removeExcludeDir(index);
      }
      if (e.target.closest('[data-remove-exclude-pattern]')) {
        const index = parseInt(e.target.closest('[data-remove-exclude-pattern]').dataset.removeExcludePattern, 10);
        this.removeExcludePattern(index);
      }
      if (e.target.closest('#btn-add-exclude-dir')) this.showAddExcludeDirModal();
      if (e.target.closest('#btn-add-exclude-pattern')) this.showAddExcludePatternModal();
    });

    // 自动扫描设置
    const autoScanToggle = document.getElementById('auto-scan-toggle');
    if (autoScanToggle) {
      autoScanToggle.addEventListener('change', (e) => {
        const intervalInput = document.getElementById('auto-scan-interval');
        intervalInput.disabled = !e.target.checked;
        this.hasChanges = true;
      });
    }

    const intervalInput = document.getElementById('auto-scan-interval');
    if (intervalInput) {
      intervalInput.addEventListener('change', () => {
        this.hasChanges = true;
      });
    }

    // 保存按钮
    document.addEventListener('click', (e) => {
      if (e.target.closest('#btn-save-settings')) this.saveSettings();
      if (e.target.closest('#btn-reset-settings')) this.resetUI();
    });
  },

  // ──────────────────────────────────────────────────────────────
  // 3. 渲染 UI
  // ──────────────────────────────────────────────────────────────
  renderUI() {
    const container = document.getElementById('view-settings');
    if (!container) return;

    const hasAutoScan = this.currentConfig.auto_scan_interval_minutes && this.currentConfig.auto_scan_interval_minutes > 0;

    container.innerHTML = `
      <div class="max-w-2xl mx-auto space-y-6 pb-8">

        <!-- 页面标题 -->
        <div class="mb-6">
          <h2 class="text-2xl font-bold text-stone-800 mb-1">设置</h2>
          <p class="text-sm text-stone-500">配置文件管理、排除规则和系统参数</p>
        </div>

        <!-- ═══════════════════════════════════════════════════════════
             扫描路径管理
             ═══════════════════════════════════════════════════════════ -->
        <div class="bg-white rounded-xl border border-stone-200 p-5" style="box-shadow:0 1px 2px rgba(45,41,38,0.06)">
          <div class="flex items-center justify-between mb-4">
            <h3 class="text-sm font-semibold text-stone-700">扫描路径</h3>
            <button id="btn-add-scan-root" class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-xs font-medium transition-colors duration-150 cursor-pointer">
              <i data-lucide="plus" class="w-3.5 h-3.5"></i>
              添加路径
            </button>
          </div>

          <div class="space-y-2">
            ${this.renderScanRootsList()}
          </div>

          ${!this.currentConfig.scan_roots || this.currentConfig.scan_roots.length === 0 ? `
            <div class="flex flex-col items-center justify-center py-8 text-stone-400">
              <i data-lucide="folder" class="w-8 h-8 mb-2 opacity-40"></i>
              <p class="text-sm">暂无扫描路径，请添加</p>
            </div>
          ` : ''}
        </div>

        <!-- ═══════════════════════════════════════════════════════════
             排除规则
             ═══════════════════════════════════════════════════════════ -->
        <div class="space-y-4">
          <!-- 排除目录 -->
          <div class="bg-white rounded-xl border border-stone-200 p-5" style="box-shadow:0 1px 2px rgba(45,41,38,0.06)">
            <div class="flex items-center justify-between mb-4">
              <h3 class="text-sm font-semibold text-stone-700">排除目录</h3>
              <button id="btn-add-exclude-dir" class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-xs font-medium transition-colors duration-150 cursor-pointer">
                <i data-lucide="plus" class="w-3.5 h-3.5"></i>
                添加
              </button>
            </div>
            <div class="space-y-2">
              ${this.renderExcludeDirsList()}
            </div>
          </div>

          <!-- 排除文件模式 -->
          <div class="bg-white rounded-xl border border-stone-200 p-5" style="box-shadow:0 1px 2px rgba(45,41,38,0.06)">
            <div class="flex items-center justify-between mb-4">
              <h3 class="text-sm font-semibold text-stone-700">排除文件模式</h3>
              <button id="btn-add-exclude-pattern" class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-xs font-medium transition-colors duration-150 cursor-pointer">
                <i data-lucide="plus" class="w-3.5 h-3.5"></i>
                添加
              </button>
            </div>
            <div class="space-y-2">
              ${this.renderExcludePatternsList()}
            </div>
          </div>
        </div>

        <!-- ═══════════════════════════════════════════════════════════
             自动扫描设置
             ═══════════════════════════════════════════════════════════ -->
        <div class="bg-white rounded-xl border border-stone-200 p-5" style="box-shadow:0 1px 2px rgba(45,41,38,0.06)">
          <h3 class="text-sm font-semibold text-stone-700 mb-4">自动扫描</h3>

          <div class="space-y-4">
            <!-- 开关 -->
            <div class="flex items-center justify-between">
              <label for="auto-scan-toggle" class="text-sm text-stone-700 font-medium cursor-pointer">启用自动扫描</label>
              <div class="relative inline-block w-11 h-6 bg-stone-200 rounded-full transition-colors duration-200 cursor-pointer" id="auto-scan-toggle-container" style="${hasAutoScan ? 'background-color: #3B82F6' : ''}">
                <input
                  id="auto-scan-toggle"
                  type="checkbox"
                  ${hasAutoScan ? 'checked' : ''}
                  class="absolute opacity-0 w-full h-full cursor-pointer"
                >
                <div class="absolute inset-y-0 left-0 w-5 h-5 m-0.5 bg-white rounded-full transition-transform duration-200 shadow-sm" id="auto-scan-toggle-dot" style="transform: ${hasAutoScan ? 'translateX(20px)' : 'translateX(0)'}"></div>
              </div>
            </div>

            <!-- 间隔输入 -->
            <div>
              <label for="auto-scan-interval" class="block text-sm font-medium text-stone-700 mb-1.5">扫描间隔（分钟）</label>
              <input
                id="auto-scan-interval"
                type="number"
                min="1"
                max="1440"
                value="${this.currentConfig.auto_scan_interval_minutes || 30}"
                ${hasAutoScan ? '' : 'disabled'}
                class="w-full px-3 py-2 rounded-lg bg-white border border-stone-200 text-sm text-stone-800 placeholder-stone-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-colors duration-150 disabled:opacity-50 disabled:cursor-not-allowed"
              >
              <p class="text-xs text-stone-400 mt-1.5">建议 15-60 分钟，默认 30 分钟</p>
            </div>
          </div>
        </div>

        <!-- ═══════════════════════════════════════════════════════════
             系统信息
             ═══════════════════════════════════════════════════════════ -->
        <div class="bg-white rounded-xl border border-stone-200 p-5" style="box-shadow:0 1px 2px rgba(45,41,38,0.06)">
          <h3 class="text-sm font-semibold text-stone-700 mb-4">系统信息</h3>

          <div id="system-info-container" class="space-y-3">
            <div class="flex items-center justify-between py-2 border-b border-stone-100">
              <span class="text-sm text-stone-600">应用版本</span>
              <span class="text-sm font-medium text-stone-800 font-mono">1.0.0</span>
            </div>
            <div class="flex items-center justify-between py-2 border-b border-stone-100">
              <span class="text-sm text-stone-600">索引文件总数</span>
              <span class="text-sm font-medium text-stone-800 font-mono" id="info-total-files">--</span>
            </div>
            <div class="flex items-center justify-between py-2 border-b border-stone-100">
              <span class="text-sm text-stone-600">数据库文件大小</span>
              <span class="text-sm font-medium text-stone-800 font-mono" id="info-db-size">--</span>
            </div>
            <div class="flex items-center justify-between py-2">
              <span class="text-sm text-stone-600">配置文件路径</span>
              <span class="text-xs font-mono text-stone-500 truncate max-w-xs" title="config.json">config.json</span>
            </div>
          </div>
        </div>

        <!-- ═══════════════════════════════════════════════════════════
             操作按钮
             ═══════════════════════════════════════════════════════════ -->
        <div class="flex items-center justify-end gap-3 pt-4">
          <button id="btn-reset-settings" class="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-stone-100 hover:bg-stone-200 active:bg-stone-300 text-stone-700 text-sm font-medium border border-stone-200 transition-colors duration-150 focus:outline-none focus:ring-2 focus:ring-stone-400 focus:ring-offset-1 cursor-pointer">
            取消
          </button>
          <button id="btn-save-settings" class="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 active:bg-blue-800 text-white text-sm font-medium transition-colors duration-150 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-1 cursor-pointer">
            <i data-lucide="save" class="w-4 h-4"></i>
            保存设置
          </button>
        </div>

      </div>
    `;

    // 重新初始化 Lucide 图标
    lucide.createIcons();

    // 加载系统信息
    this.loadSystemInfo();

    // 绑定切换开关的动画
    this.bindToggleAnimation();
  },

  // ──────────────────────────────────────────────────────────────
  // 4. 渲染列表
  // ──────────────────────────────────────────────────────────────

  renderScanRootsList() {
    if (!this.currentConfig.scan_roots || this.currentConfig.scan_roots.length === 0) {
      return '';
    }

    return this.currentConfig.scan_roots
      .map((root, idx) => {
        // 兼容字符串和对象格式
        const path = typeof root === 'string' ? root : root.path;
        const label = typeof root === 'string' ? '本地磁盘' : (root.disk_label || '本地磁盘');
        return `
          <div class="flex items-center justify-between px-3 py-2.5 rounded-lg bg-stone-50 border border-stone-100 group hover:border-stone-200 transition-colors duration-150">
            <div class="flex items-center gap-2.5 flex-1 min-w-0">
              <i data-lucide="folder" class="w-4 h-4 text-stone-500 flex-shrink-0"></i>
              <div class="min-w-0 flex-1">
                <p class="text-sm font-medium text-stone-800 truncate">${this.escapeHtml(path)}</p>
                <p class="text-xs text-stone-400 truncate">${this.escapeHtml(label)}</p>
              </div>
            </div>
            <button data-remove-root="${idx}" class="inline-flex items-center gap-1 px-2 py-1.5 rounded-md text-stone-500 hover:text-red-600 hover:bg-red-50 text-xs transition-colors duration-150 cursor-pointer opacity-0 group-hover:opacity-100">
              <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
              <span>删除</span>
            </button>
          </div>
        `;
      })
      .join('');
  },

  renderExcludeDirsList() {
    if (!this.currentConfig.exclude_dirs || this.currentConfig.exclude_dirs.length === 0) {
      return '<p class="text-sm text-stone-400 py-4">暂无排除目录</p>';
    }

    return this.currentConfig.exclude_dirs
      .map((dir, idx) => `
        <div class="flex items-center justify-between px-3 py-2.5 rounded-lg bg-stone-50 border border-stone-100 group hover:border-stone-200 transition-colors duration-150">
          <div class="flex items-center gap-2.5 flex-1 min-w-0">
            <i data-lucide="folder-x" class="w-4 h-4 text-stone-500 flex-shrink-0"></i>
            <p class="text-sm font-mono text-stone-700 truncate">${this.escapeHtml(dir)}</p>
          </div>
          <button data-remove-exclude-dir="${idx}" class="inline-flex items-center gap-1 px-2 py-1.5 rounded-md text-stone-500 hover:text-red-600 hover:bg-red-50 text-xs transition-colors duration-150 cursor-pointer opacity-0 group-hover:opacity-100">
            <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
            <span>删除</span>
          </button>
        </div>
      `)
      .join('');
  },

  renderExcludePatternsList() {
    if (!this.currentConfig.exclude_patterns || this.currentConfig.exclude_patterns.length === 0) {
      return '<p class="text-sm text-stone-400 py-4">暂无排除模式</p>';
    }

    return this.currentConfig.exclude_patterns
      .map((pattern, idx) => `
        <div class="flex items-center justify-between px-3 py-2.5 rounded-lg bg-stone-50 border border-stone-100 group hover:border-stone-200 transition-colors duration-150">
          <div class="flex items-center gap-2.5 flex-1 min-w-0">
            <i data-lucide="file-x" class="w-4 h-4 text-stone-500 flex-shrink-0"></i>
            <p class="text-sm font-mono text-stone-700 truncate">${this.escapeHtml(pattern)}</p>
          </div>
          <button data-remove-exclude-pattern="${idx}" class="inline-flex items-center gap-1 px-2 py-1.5 rounded-md text-stone-500 hover:text-red-600 hover:bg-red-50 text-xs transition-colors duration-150 cursor-pointer opacity-0 group-hover:opacity-100">
            <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
            <span>删除</span>
          </button>
        </div>
      `)
      .join('');
  },

  // ──────────────────────────────────────────────────────────────
  // 5. 模态框：添加项目
  // ──────────────────────────────────────────────────────────────

  async showAddScanRootModal() {
    const path = prompt('输入扫描根目录路径（例如：E:\\）');
    if (path && path.trim()) {
      const diskLabel = prompt('输入磁盘标签（可选，如：工作数据盘）') || '';
      if (!this.currentConfig.scan_roots) this.currentConfig.scan_roots = [];

      // 检查路径是否已存在（兼容字符串和对象格式）
      const pathExists = this.currentConfig.scan_roots.some(root => {
        const existingPath = typeof root === 'string' ? root : root.path;
        return existingPath.toLowerCase() === path.trim().toLowerCase();
      });

      if (!pathExists) {
        this.currentConfig.scan_roots.push({
          path: path.trim(),
          disk_label: diskLabel.trim(),
          disk_serial: '',
        });
        this.renderUI();
        await this._saveScanRoots();
      } else {
        App.showToast('路径已存在', 'warning');
      }
    }
  },

  showAddExcludeDirModal() {
    const value = prompt('输入要排除的目录名称（例如：node_modules）');
    if (value && value.trim()) {
      if (!this.currentConfig.exclude_dirs) this.currentConfig.exclude_dirs = [];
      if (!this.currentConfig.exclude_dirs.includes(value.trim())) {
        this.currentConfig.exclude_dirs.push(value.trim());
        this.hasChanges = true;
        this.renderUI();
        App.showToast('已添加排除目录', 'success');
      } else {
        App.showToast('目录已存在', 'warning');
      }
    }
  },

  showAddExcludePatternModal() {
    const value = prompt('输入文件模式（例如：*.tmp, ~$*）');
    if (value && value.trim()) {
      if (!this.currentConfig.exclude_patterns) this.currentConfig.exclude_patterns = [];
      if (!this.currentConfig.exclude_patterns.includes(value.trim())) {
        this.currentConfig.exclude_patterns.push(value.trim());
        this.hasChanges = true;
        this.renderUI();
        App.showToast('已添加排除模式', 'success');
      } else {
        App.showToast('模式已存在', 'warning');
      }
    }
  },

  // ──────────────────────────────────────────────────────────────
  // 6. 删除项目
  // ──────────────────────────────────────────────────────────────

  async removeScanRoot(index) {
    if (confirm('确定删除此扫描路径吗？')) {
      this.currentConfig.scan_roots.splice(index, 1);
      this.renderUI();
      await this._saveScanRoots();
    }
  },

  removeExcludeDir(index) {
    if (confirm('确定删除此排除目录吗？')) {
      this.currentConfig.exclude_dirs.splice(index, 1);
      this.hasChanges = true;
      this.renderUI();
      App.showToast('已删除排除目录', 'success');
    }
  },

  removeExcludePattern(index) {
    if (confirm('确定删除此排除模式吗？')) {
      this.currentConfig.exclude_patterns.splice(index, 1);
      this.hasChanges = true;
      this.renderUI();
      App.showToast('已删除排除模式', 'success');
    }
  },

  // ──────────────────────────────────────────────────────────────
  // 7. 切换开关动画
  // ──────────────────────────────────────────────────────────────

  bindToggleAnimation() {
    const toggle = document.getElementById('auto-scan-toggle');
    const container = document.getElementById('auto-scan-toggle-container');
    const dot = document.getElementById('auto-scan-toggle-dot');

    if (!toggle || !container || !dot) return;

    const updateToggleStyle = () => {
      const isChecked = toggle.checked;
      container.style.backgroundColor = isChecked ? '#3B82F6' : '#D3D3D3';
      dot.style.transform = isChecked ? 'translateX(20px)' : 'translateX(0)';
    };

    toggle.addEventListener('change', updateToggleStyle);
    // 初始化颜色
    updateToggleStyle();
  },

  // ──────────────────────────────────────────────────────────────
  // 8. 保存设置
  // ──────────────────────────────────────────────────────────────

  // 扫描路径变更后立即保存并通知仪表盘同步
  async _saveScanRoots() {
    try {
      const resp = await fetch('/api/config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(this.currentConfig),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      App.showToast('扫描路径已保存', 'success');
      // 通知仪表盘同步输入框
      document.dispatchEvent(new CustomEvent('app:configChanged', {
        detail: { scan_roots: this.currentConfig.scan_roots }
      }));
    } catch (err) {
      App.showToast('保存失败：' + err.message, 'error');
    }
  },

  async saveSettings() {
    // 更新自动扫描设置
    const toggle = document.getElementById('auto-scan-toggle');
    const interval = document.getElementById('auto-scan-interval');

    if (toggle) {
      if (toggle.checked && interval) {
        const minutes = parseInt(interval.value, 10);
        this.currentConfig.auto_scan_interval_minutes = minutes;
      } else {
        this.currentConfig.auto_scan_interval_minutes = 0;
      }
    }

    // 发送到服务器
    const btn = document.getElementById('btn-save-settings');
    const originalText = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<i data-lucide="loader" class="w-4 h-4 animate-spin"></i>保存中...';

    try {
      const resp = await fetch('/api/config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(this.currentConfig),
      });

      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

      this.hasChanges = false;
      App.showToast('设置已保存', 'success');
    } catch (err) {
      App.showToast('保存设置失败：' + err.message, 'error');
    } finally {
      btn.disabled = false;
      btn.innerHTML = originalText;
      lucide.createIcons();
    }
  },

  resetUI() {
    this.hasChanges = false;
    this.renderUI();
  },

  // ──────────────────────────────────────────────────────────────
  // 9. 系统信息
  // ──────────────────────────────────────────────────────────────

  async loadSystemInfo() {
    try {
      const statsResp = await fetch('/api/stats/overview');
      if (statsResp.ok) {
        const stats = await statsResp.json();
        document.getElementById('info-total-files').textContent = this.formatNumber(stats.total_files);
        document.getElementById('info-db-size').textContent = this.formatBytes(stats.db_size_bytes);
      }
    } catch (err) {
      console.error('❌ 加载系统信息失败:', err);
    }
  },

  // ──────────────────────────────────────────────────────────────
  // 工具函数
  // ──────────────────────────────────────────────────────────────

  formatNumber(num) {
    if (num === undefined || num === null) return '--';
    return num.toLocaleString('zh-CN');
  },

  formatBytes(bytes) {
    if (bytes === undefined || bytes === null) return '--';
    const units = ['B', 'KB', 'MB', 'GB'];
    let size = bytes;
    let unitIdx = 0;

    while (size >= 1024 && unitIdx < units.length - 1) {
      size /= 1024;
      unitIdx++;
    }

    return `${size.toFixed(2)} ${units[unitIdx]}`;
  },

  escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  },
};

// 导出到全局
window.Settings = Settings;
