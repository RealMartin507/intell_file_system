/**
 * AI 文件助手模块
 *
 * 占位界面阶段（第一/二阶段）：
 * - UI 外壳已完成，包含聊天界面、示例问题、消息展示区
 * - 实现了示例问题点击、输入框交互、Toast 通知
 * - 预留了后端 API 接口注释，第三阶段可直接接入
 *
 * 预留的后端接口（第三阶段实现）：
 * - POST /api/ai/chat - 发送消息到 AI 后端
 * - 返回格式：{ reply: string, sources: [{file_id, filename, path, relevance}] }
 */

const AI = {
  // ═════════════════════════════════════════════════════════════════
  // 1. 全局状态
  // ═════════════════════════════════════════════════════════════════

  state: {
    isLoading: false,
    currentConversationId: null,
    messages: [],  // 当前对话的消息列表
  },

  elements: {},

  // ═════════════════════════════════════════════════════════════════
  // 2. 初始化
  // ═════════════════════════════════════════════════════════════════

  init() {
    this.cacheElements();
    this.attachEventListeners();
    this.setupAutoResize();
  },

  cacheElements() {
    this.elements = {
      // 容器
      welcomeState: document.getElementById('ai-welcome-state'),
      messagesContainer: document.getElementById('ai-messages-container'),

      // 输入区
      inputText: document.getElementById('ai-input-text'),
      sendBtn: document.getElementById('ai-send-btn'),

      // 示例按钮
      exampleBtns: document.querySelectorAll('.ai-example-btn'),
    };
  },

  attachEventListeners() {
    // 示例问题按钮点击
    this.elements.exampleBtns.forEach(btn => {
      btn.addEventListener('click', () => this.onExampleClick(btn));
    });

    // 发送按钮点击
    this.elements.sendBtn.addEventListener('click', () => this.sendMessage());

    // 文本框 Ctrl+Enter 发送
    this.elements.inputText.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        e.preventDefault();
        this.sendMessage();
      }
    });

    // 文本框 Enter 换行
    this.elements.inputText.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.ctrlKey && !e.metaKey) {
        // 允许自然换行，不做处理
      }
    });
  },

  /**
   * 自动调整文本框高度
   */
  setupAutoResize() {
    const textarea = this.elements.inputText;

    const autoResize = () => {
      textarea.style.height = 'auto';
      const newHeight = Math.min(textarea.scrollHeight, 120);
      textarea.style.height = `${newHeight}px`;
    };

    textarea.addEventListener('input', autoResize);
  },

  // ═════════════════════════════════════════════════════════════════
  // 3. 事件处理
  // ═════════════════════════════════════════════════════════════════

  /**
   * 示例问题点击处理
   */
  onExampleClick(btn) {
    const prompt = btn.getAttribute('data-prompt');
    this.elements.inputText.value = prompt;
    this.elements.inputText.focus();

    // 调整高度
    this.elements.inputText.style.height = 'auto';
    const newHeight = Math.min(this.elements.inputText.scrollHeight, 120);
    this.elements.inputText.style.height = `${newHeight}px`;
  },

  /**
   * 发送消息
   */
  sendMessage() {
    const text = this.elements.inputText.value.trim();

    // 验证输入
    if (!text) {
      App.showToast('请输入问题', 'warning');
      return;
    }

    // 显示 Toast：功能即将推出
    App.showToast('AI 问答功能将在后续版本推出，敬请期待', 'info');

    // 清空输入框
    this.elements.inputText.value = '';
    this.elements.inputText.style.height = 'auto';

    // 【第三阶段】这里接入真正的后端逻辑
    // this.sendMessageToBackend(text);

    // 演示用：如果需要测试消息渲染，可以调用 this.renderUserMessage(text)
    // 然后延迟后调用 this.renderAIResponse(...)
  },

  // ═════════════════════════════════════════════════════════════════
  // 4. 消息渲染接口（第三阶段接入 API）
  // ═════════════════════════════════════════════════════════════════

  /**
   * 【预留接口】发送消息到后端
   *
   * @param {string} text - 用户问题
   *
   * 第三阶段实现，调用：
   * POST /api/ai/chat
   * {
   *   "conversation_id": "uuid",
   *   "message": "用户问题文本",
   *   "context": {
   *     "recent_files": [...],  // 可选：最近访问的文件列表
   *     "selected_roots": [...]  // 可选：当前扫描根目录
   *   }
   * }
   *
   * 返回：
   * {
   *   "reply": "AI 的回复文本...",
   *   "sources": [
   *     {
   *       "file_id": "uuid",
   *       "filename": "roads_2024.shp",
   *       "path": "E:\\GIS\\Projects\\roads_2024.shp",
   *       "file_type": "gis_vector",
   *       "relevance": 0.95,
   *       "snippet": "文件内容摘要..."
   *     }
   *   ],
   *   "follow_up_suggestions": [...]  // 可选：后续建议问题
   * }
   */
  async sendMessageToBackend(text) {
    // 显示用户消息
    this.renderUserMessage(text);

    // 设置加载状态
    this.state.isLoading = true;
    this.elements.sendBtn.disabled = true;

    try {
      // 【第三阶段实现】：
      // const response = await fetch('/api/ai/chat', {
      //   method: 'POST',
      //   headers: { 'Content-Type': 'application/json' },
      //   body: JSON.stringify({
      //     conversation_id: this.state.currentConversationId,
      //     message: text
      //   })
      // });
      //
      // if (!response.ok) throw new Error('API 请求失败');
      // const data = await response.json();
      //
      // this.renderAIResponse(data.reply, data.sources);

      // 目前仅占位，不调用后端
    } catch (error) {
      console.error('AI 消息发送失败:', error);
      App.showToast('发送失败，请重试', 'error');
    } finally {
      this.state.isLoading = false;
      this.elements.sendBtn.disabled = false;
    }
  },

  /**
   * 渲染用户消息
   *
   * @param {string} text - 消息文本
   */
  renderUserMessage(text) {
    // 如果是首条消息，显示消息容器，隐藏欢迎界面
    if (this.state.messages.length === 0) {
      this.showMessagesView();
    }

    const messageEl = document.createElement('div');
    messageEl.className = 'flex justify-end mb-4 animate-fadeInUp';
    messageEl.innerHTML = `
      <div class="max-w-md bg-blue-600 text-white rounded-2xl rounded-tr-md px-4 py-3">
        <p class="text-sm leading-relaxed break-words">${this.escapeHtml(text)}</p>
      </div>
    `;

    this.elements.messagesContainer.appendChild(messageEl);
    this.scrollToBottom();

    // 添加到消息记录
    this.state.messages.push({
      type: 'user',
      text: text,
      timestamp: new Date(),
    });
  },

  /**
   * 渲染 AI 回复
   *
   * @param {string} reply - AI 回复文本
   * @param {Array} sources - 引用来源列表，格式：
   *   [
   *     {
   *       file_id: "uuid",
   *       filename: "roads_2024.shp",
   *       path: "E:\\GIS\\Projects\\roads_2024.shp",
   *       file_type: "gis_vector",
   *       relevance: 0.95
   *     },
   *     ...
   *   ]
   */
  renderAIResponse(reply, sources = []) {
    const messageEl = document.createElement('div');
    messageEl.className = 'flex justify-start mb-4 animate-fadeInUp';

    // 构建源文件卡片 HTML
    let sourcesHtml = '';
    if (sources && sources.length > 0) {
      sourcesHtml = `
        <div class="mt-3 pt-3 border-t border-stone-200 space-y-2">
          <p class="text-xs font-medium text-stone-500 uppercase tracking-wider">引用来源</p>
          <div class="space-y-1.5">
      `;

      sources.forEach((source, idx) => {
        // 使用 data-* 属性存储数据，避免 HTML 转义问题
        sourcesHtml += `
          <div class="ai-source-btn flex items-start gap-2 p-2 rounded-lg bg-stone-50 hover:bg-stone-100 transition-colors cursor-pointer"
               data-file-id="${source.file_id}"
               data-filename="${this.escapeHtml(source.filename)}">
            <i data-lucide="file-text" class="w-3.5 h-3.5 text-stone-400 flex-shrink-0 mt-0.5"></i>
            <div class="min-w-0 flex-1">
              <p class="text-xs font-medium text-stone-700 truncate hover:underline">${this.escapeHtml(source.filename)}</p>
              <p class="text-xs text-stone-400 truncate mt-0.5">${this.escapeHtml(source.path)}</p>
            </div>
            ${source.relevance ? `<span class="text-xs text-stone-500 flex-shrink-0 font-mono">${(source.relevance * 100).toFixed(0)}%</span>` : ''}
          </div>
        `;
      });

      sourcesHtml += `
          </div>
        </div>
      `;
    }

    messageEl.innerHTML = `
      <div class="max-w-md bg-white border border-stone-200 rounded-2xl rounded-tl-md px-4 py-3 shadow-warm-sm">
        <p class="text-sm leading-relaxed text-stone-800 break-words">${this.escapeHtml(reply)}</p>
        ${sourcesHtml}
      </div>
    `;

    this.elements.messagesContainer.appendChild(messageEl);
    this.scrollToBottom();

    // 重新初始化 Lucide 图标
    lucide.createIcons();

    // 为源卡片添加点击事件监听器
    const sourceButtons = messageEl.querySelectorAll('.ai-source-btn');
    sourceButtons.forEach(btn => {
      btn.addEventListener('click', () => {
        const filename = btn.getAttribute('data-filename');
        const fileId = btn.getAttribute('data-file-id');
        this.goToFileInSearch(filename, fileId);
      });
    });

    // 添加到消息记录
    this.state.messages.push({
      type: 'ai',
      text: reply,
      sources: sources,
      timestamp: new Date(),
    });
  },

  /**
   * 清空对话
   */
  clearConversation() {
    this.state.messages = [];
    this.state.currentConversationId = null;
    this.elements.messagesContainer.innerHTML = '';
    this.elements.inputText.value = '';
    this.elements.inputText.style.height = 'auto';

    // 显示欢迎界面
    this.showWelcomeView();
  },

  // ═════════════════════════════════════════════════════════════════
  // 5. UI 状态切换
  // ═════════════════════════════════════════════════════════════════

  /**
   * 显示欢迎界面
   */
  showWelcomeView() {
    this.elements.welcomeState.classList.remove('hidden');
    this.elements.messagesContainer.classList.add('hidden');
  },

  /**
   * 显示消息视图
   */
  showMessagesView() {
    this.elements.welcomeState.classList.add('hidden');
    this.elements.messagesContainer.classList.remove('hidden');
  },

  /**
   * 滚动到底部
   */
  scrollToBottom() {
    const container = this.elements.messagesContainer;
    setTimeout(() => {
      container.scrollTop = container.scrollHeight;
    }, 0);
  },

  // ═════════════════════════════════════════════════════════════════
  // 6. 工具函数
  // ═════════════════════════════════════════════════════════════════

  /**
   * 转义 HTML 字符
   */
  escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  },

  /**
   * 从 AI 引用来源跳转到搜索视图定位文件
   *
   * @param {string} filename - 文件名
   * @param {string} fileId - 文件 ID
   */
  goToFileInSearch(filename, fileId) {
    // 切换到搜索视图
    App.switchView('search');

    // 在搜索框中输入文件名
    const searchInput = document.getElementById('search-input');
    if (searchInput) {
      searchInput.value = filename;
      // 触发搜索
      searchInput.dispatchEvent(new Event('input', { bubbles: true }));
    }

    // 【可选】如果要直接定位文件详情，可以调用：
    // Preview.show(fileId);

    App.showToast(`已跳转到搜索视图，正在查找 "${filename}"`, 'success');
  },
};

// 页面加载完成后初始化
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    // 确保 App 已初始化
    if (typeof App !== 'undefined') {
      AI.init();
    }
  });
} else {
  // DOMContentLoaded 已触发，直接初始化
  if (typeof App !== 'undefined') {
    AI.init();
  }
}

// 【测试演示代码】可在控制台运行以验证功能：
/*
AI.renderUserMessage("GIS 文件去年保存在哪里？");
setTimeout(() => {
  AI.renderAIResponse(
    "根据您的知识库索引，去年保存的 GIS 相关文件主要分布在以下位置...",
    [
      {
        filename: "roads_2024.shp",
        path: "E:\\GIS\\Projects\\Cities\\roads_2024.shp",
        file_id: "abc-123",
        file_type: "gis_vector",
        relevance: 0.95
      },
      {
        filename: "landuse.tif",
        path: "E:\\GIS\\Raster\\landuse.tif",
        file_id: "def-456",
        file_type: "gis_raster",
        relevance: 0.87
      }
    ]
  );
}, 1000);
*/
