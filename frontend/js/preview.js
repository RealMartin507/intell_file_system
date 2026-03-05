/**
 * preview.js — 文件预览模块
 * 依赖：window.App（由 app.js 提供）
 */

// ──────────────────────────────────────────────
// 文件类型视觉配置（与 search.js 同步）
// ──────────────────────────────────────────────
const PREVIEW_FILE_TYPE_CONFIG = {
  gis_vector:  { label: 'GIS 矢量',  icon: 'map',         bgClass: 'bg-emerald-50',  textClass: 'text-emerald-600'  },
  gis_raster:  { label: 'GIS 栅格',  icon: 'grid-3x3',    bgClass: 'bg-violet-50',   textClass: 'text-violet-700'   },
  mapgis:      { label: 'MapGIS',    icon: 'layers',      bgClass: 'bg-cyan-50',     textClass: 'text-cyan-700'     },
  fme:         { label: 'FME',       icon: 'workflow',    bgClass: 'bg-orange-50',   textClass: 'text-orange-700'   },
  survey:      { label: '测量数据',  icon: 'compass',     bgClass: 'bg-yellow-50',   textClass: 'text-yellow-700'   },
  cad:         { label: 'CAD',       icon: 'pen-tool',    bgClass: 'bg-blue-50',     textClass: 'text-blue-700'     },
  image:       { label: '图片',      icon: 'image',       bgClass: 'bg-pink-50',     textClass: 'text-pink-700'     },
  document:    { label: '文档',      icon: 'file-text',   bgClass: 'bg-indigo-50',   textClass: 'text-indigo-700'   },
  spreadsheet: { label: '表格',      icon: 'table-2',     bgClass: 'bg-green-50',    textClass: 'text-green-700'    },
  video:       { label: '视频',      icon: 'film',        bgClass: 'bg-rose-50',     textClass: 'text-rose-700'     },
  audio:       { label: '音频',      icon: 'music',       bgClass: 'bg-purple-50',   textClass: 'text-purple-700'   },
  archive:     { label: '压缩包',    icon: 'archive',     bgClass: 'bg-amber-50',    textClass: 'text-amber-800'    },
  other:       { label: '其他',      icon: 'file',        bgClass: 'bg-stone-100',   textClass: 'text-stone-600'    },
};

// ──────────────────────────────────────────────
// 模块状态
// ──────────────────────────────────────────────
let _currentFileId = null;
let _currentFile = null;

// 在脚本加载时立即输出日志
console.log('🚀 [Preview] 脚本开始加载...');

// ──────────────────────────────────────────────
// 初始化
// ──────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  console.log('🚀 [Preview] DOMContentLoaded 事件触发');

  // 检查前置条件
  const container = document.getElementById('preview-modal-container');
  if (!container) {
    console.error('❌ [Preview] 模态框容器不存在！');
    return;
  }

  console.log('✅ [Preview] 模态框容器已找到');
  console.log('  - 初始 classes:', container.className);

  // 初始化事件处理
  _initModalHandlers();

  // 暴露 Preview API
  window.Preview = {
    show: _show,
    hide: _hide,
    openFullImage: _openFullImage,
  };

  console.log('✅ [Preview] 模块初始化完成');
  console.log('  - Preview.show("file-id") 已可用');
});

// ──────────────────────────────────────────────
// 模态框事件处理
// ──────────────────────────────────────────────
function _initModalHandlers() {
  const container = document.getElementById('preview-modal-container');
  const overlay = document.getElementById('preview-modal-overlay');
  const closeBtn = document.getElementById('preview-close-btn');

  if (!container) {
    console.warn('⚠️ 预览模态框容器未找到');
    return;
  }

  // 关闭按钮
  if (closeBtn) {
    closeBtn.addEventListener('click', () => Preview.hide());
  }

  // 点击遮罩关闭
  if (overlay) {
    overlay.addEventListener('click', () => Preview.hide());
  }

  // 按 Esc 关闭
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && !container.classList.contains('hidden')) {
      Preview.hide();
    }
  });

  // 操作按钮
  document.getElementById('preview-btn-open')?.addEventListener('click', () => {
    if (_currentFileId) _openFile(_currentFileId);
  });

  document.getElementById('preview-btn-open-dir')?.addEventListener('click', () => {
    if (_currentFileId) _openDir(_currentFileId);
  });

  document.getElementById('preview-btn-copy-path')?.addEventListener('click', () => {
    if (_currentFileId) _copyPath(_currentFileId);
  });

  // 防止点击模态框内容时关闭
  const modal = document.getElementById('preview-modal');
  if (modal) {
    modal.addEventListener('click', e => e.stopPropagation());
  }
}

// ──────────────────────────────────────────────
// 打开预览
// ──────────────────────────────────────────────
async function _show(fileId) {
  if (!fileId) {
    console.warn('⚠️ 文件 ID 为空');
    return;
  }

  console.log(`🔍 打开预览: ${fileId}`);
  _currentFileId = fileId;

  const container = document.getElementById('preview-modal-container');
  if (!container) {
    console.error('❌ 模态框容器不存在');
    return;
  }

  // 显示模态框（加载中）
  container.style.display = 'flex'; // 确保显示
  container.classList.remove('hidden');

  // 触发动效
  const overlay = document.getElementById('preview-modal-overlay');
  const modal = document.getElementById('preview-modal');
  if (overlay) overlay.classList.add('overlay-enter');
  if (modal) modal.classList.add('modal-enter');

  try {
    // 获取文件完整信息
    const res = await fetch(`${App.API_BASE}/api/files/${fileId}`);
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || `获取文件信息失败 (${res.status})`);
    }

    const file = await res.json();
    _currentFile = file;

    console.log('📄 文件信息:', file);

    // 更新标题
    const titleEl = document.getElementById('preview-title');
    if (titleEl) {
      titleEl.textContent = file.file_name || '文件详情';
    }

    // 渲染内容
    await _renderPreview(file);

    // 刷新 Lucide 图标
    lucide.createIcons();

  } catch (err) {
    console.error('❌ 预览加载失败:', err);
    const contentEl = document.getElementById('preview-content');
    if (contentEl) {
      contentEl.innerHTML = `
        <div class="flex flex-col items-center justify-center py-8 text-stone-400">
          <i data-lucide="alert-circle" class="w-10 h-10 mb-2 opacity-50"></i>
          <p class="text-sm font-medium text-stone-600">无法加载文件信息</p>
          <p class="text-xs text-stone-400 mt-1">${err.message}</p>
        </div>
      `;
      lucide.createIcons();
    }
  }
}

// ──────────────────────────────────────────────
// 关闭预览
// ──────────────────────────────────────────────
function _hide() {
  const container = document.getElementById('preview-modal-container');
  const modal = document.getElementById('preview-modal');

  if (!container) return;

  // 触发离场动效
  if (modal) {
    modal.classList.remove('modal-enter');
    modal.classList.add('modal-leave');
  }

  // 等待动效完成后隐藏
  setTimeout(() => {
    container.classList.add('hidden');
    container.style.display = 'none'; // 强制隐藏
    // 移除动效类，为下次打开做准备
    if (modal) {
      modal.classList.remove('modal-leave');
    }
    _currentFileId = null;
    _currentFile = null;
    console.log('✅ 预览已关闭');
  }, 150); // 离场动效持续 150ms
}

// ──────────────────────────────────────────────
// 根据文件类型渲染预览内容
// ──────────────────────────────────────────────
async function _renderPreview(file) {
  const contentEl = document.getElementById('preview-content');
  if (!contentEl) return;

  const fileType = file.file_type || 'other';
  const cfg = PREVIEW_FILE_TYPE_CONFIG[fileType] || PREVIEW_FILE_TYPE_CONFIG.other;

  // 通用的文件信息卡片
  const infoCard = _buildFileInfoCard(file, cfg);

  // 根据类型渲染不同内容
  if (fileType === 'image') {
    contentEl.innerHTML = await _renderImagePreview(file, infoCard);
  } else if (fileType === 'document' && _isPdfFile(file)) {
    contentEl.innerHTML = _renderPdfPreview(file, infoCard);
  } else if (fileType === 'document' || fileType === 'spreadsheet' || fileType === 'video' || fileType === 'audio') {
    contentEl.innerHTML = infoCard;
  } else if (_isGisType(fileType)) {
    contentEl.innerHTML = await _renderGisPreview(file, cfg, infoCard);
  } else {
    contentEl.innerHTML = infoCard;
  }

  // 刷新图标
  lucide.createIcons({ nodes: [contentEl] });
}

// ──────────────────────────────────────────────
// 图片预览
// ──────────────────────────────────────────────
async function _renderImagePreview(file, infoCard) {
  let thumbnailHtml = '';

  try {
    // 获取缩略图
    const previewRes = await fetch(`${App.API_BASE}/api/files/${file.id}/preview`);
    if (previewRes.ok) {
      const blob = await previewRes.blob();
      const url = URL.createObjectURL(blob);
      thumbnailHtml = `
        <div class="mb-4">
          <p class="text-xs font-medium text-stone-500 mb-2 uppercase tracking-wider">缩略图预览</p>
          <div class="bg-stone-50 rounded-lg overflow-hidden border border-stone-200 flex items-center justify-center"
               style="max-height: 400px;">
            <img
              src="${url}"
              alt="${file.file_name}"
              class="max-w-full max-h-full object-contain cursor-pointer hover:opacity-90 transition-opacity"
              onclick="Preview.openFullImage('${file.id}')"
              title="点击查看原图"
            >
          </div>
          <p class="text-xs text-stone-400 mt-2 text-center">点击缩略图查看原图</p>
        </div>
      `;
    }
  } catch (err) {
    console.warn('⚠️ 缩略图加载失败:', err);
    thumbnailHtml = `
      <div class="mb-4 p-4 bg-stone-50 rounded-lg border border-stone-200 text-center">
        <p class="text-xs text-stone-500">缩略图加载失败</p>
      </div>
    `;
  }

  return `
    <div class="space-y-4">
      ${thumbnailHtml}
      <div class="border-t border-stone-100 pt-4">
        ${infoCard}
      </div>
    </div>
  `;
}

// ──────────────────────────────────────────────
// PDF 预览
// ──────────────────────────────────────────────
function _renderPdfPreview(file, infoCard) {
  return `
    <div class="space-y-4">
      <div class="p-4 bg-amber-50 rounded-lg border border-amber-200">
        <div class="flex items-start gap-3">
          <i data-lucide="file-text" class="w-5 h-5 text-amber-600 flex-shrink-0 mt-0.5"></i>
          <div class="flex-1">
            <p class="text-sm font-medium text-amber-900">PDF 文件</p>
            <p class="text-xs text-amber-700 mt-1">
              此文件为 PDF 格式。点击下方"打开文件"按钮用默认应用查看。
            </p>
          </div>
        </div>
      </div>
      <div class="border-t border-stone-100 pt-4">
        ${infoCard}
      </div>
    </div>
  `;
}

// ──────────────────────────────────────────────
// GIS 预览（含关联文件列表）
// ──────────────────────────────────────────────
async function _renderGisPreview(file, cfg, infoCard) {
  const typeLabel = cfg.label || file.file_type;

  let relatedHtml = '';
  if (file.shapefile_group && file.related_files && file.related_files.length > 0) {
    relatedHtml = `
      <div class="border-t border-stone-100 pt-4 mt-4">
        <p class="text-xs font-medium text-stone-500 mb-3 uppercase tracking-wider">关联文件</p>
        <div class="space-y-1.5">
          ${file.related_files.map(rf => `
            <div class="flex items-center gap-2 p-2.5 bg-stone-50 rounded-lg border border-stone-100 hover:bg-stone-100 transition-colors">
              <i data-lucide="file" class="w-4 h-4 text-stone-400 flex-shrink-0"></i>
              <div class="min-w-0 flex-1">
                <p class="text-xs font-medium text-stone-700 truncate">${rf.file_name}</p>
                <p class="text-xs text-stone-400 truncate">${_fmtSize(rf.file_size)} · ${_fmtDate(rf.modified_time)}</p>
              </div>
            </div>
          `).join('')}
        </div>
        <p class="text-xs text-stone-400 mt-2">共 ${file.related_files.length} 个相关文件</p>
      </div>
    `;
  }

  return `
    <div class="space-y-2">
      <div class="flex items-center gap-2.5 p-3 ${cfg.bgClass} rounded-lg border border-stone-100">
        <div class="w-10 h-10 rounded-lg ${cfg.bgClass} flex items-center justify-center">
          <i data-lucide="${cfg.icon}" class="w-5 h-5 ${cfg.textClass}"></i>
        </div>
        <div>
          <p class="text-xs text-stone-500 font-medium">文件类型</p>
          <p class="text-sm font-medium text-stone-800">${typeLabel}</p>
        </div>
      </div>
      ${infoCard}
      ${relatedHtml}
    </div>
  `;
}

// ──────────────────────────────────────────────
// 构建文件信息卡片
// ──────────────────────────────────────────────
function _buildFileInfoCard(file, cfg) {
  const rows = [
    { label: '文件名', value: file.file_name },
    { label: '文件类型', value: cfg.label },
    { label: '文件大小', value: _fmtSize(file.file_size) },
    { label: '修改时间', value: _fmtDate(file.modified_time) },
    { label: '创建时间', value: _fmtDate(file.created_time) },
    { label: '完整路径', value: file.file_path, mono: true },
  ];

  return `
    <div class="space-y-2.5">
      ${rows.map(row => `
        <div class="flex items-start gap-3">
          <p class="text-xs font-medium text-stone-400 min-w-fit">${row.label}</p>
          <p class="text-sm text-stone-700 flex-1 break-words ${row.mono ? 'font-mono text-xs' : ''}">${row.value || '--'}</p>
        </div>
      `).join('')}
    </div>
  `;
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
      App.showToast(err.detail || `打开文件失败（${res.status}）`, 'error');
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
      App.showToast(err.detail || `打开文件夹失败（${res.status}）`, 'error');
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
    if (!res.ok) {
      const errData = await res.text();
      console.error(`❌ 获取文件路径失败 (${res.status}):`, errData);
      throw new Error(`获取路径失败 (${res.status})`);
    }

    const data = await res.json();
    const path = data.file_path || data.path || '';

    if (!path) {
      App.showToast('无法获取文件路径', 'error');
      return;
    }

    await navigator.clipboard.writeText(path);
    App.showToast('已复制路径', 'success', 2000);
  } catch (err) {
    console.error('❌ 复制路径异常:', err);
    App.showToast(`复制失败: ${err.message}`, 'error');
  }
}

// ──────────────────────────────────────────────
// 放大查看原图
// ──────────────────────────────────────────────
function _openFullImage(fileId) {
  if (!fileId) return;
  // 在新标签页打开原图
  const imageUrl = `${App.API_BASE}/api/files/${fileId}/preview?full=1`;
  window.open(imageUrl, '_blank');
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

function _isPdfFile(file) {
  return file.file_name && /\.pdf$/i.test(file.file_name);
}

function _isGisType(fileType) {
  return ['gis_vector', 'gis_raster', 'mapgis', 'fme', 'survey', 'cad'].includes(fileType);
}