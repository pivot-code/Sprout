/**
 * Sprout Frontend v1.0 — Learning Growth Agent
 * REST + WebSocket communication
 */

const API_BASE = window.location.origin;
const WS_URL = `ws://${window.location.host}/ws/chat`;

// ─── Global State ─────────────────────────────────────────────────
const state = {
  ws: null,
  sessions: {},
  activeSession: null,
  currentView: 'chat',
  currentMemoryTab: 'identity',
  isStreaming: false,
  pendingFiles: [],
  providers: [],
  activeProviderId: '',
  _saveTimers: {},
  _unreadNotifCount: 0,
};

// ─── DOM Helpers ─────────────────────────────────────────────────
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

// ─── Init ─────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
  initNavigation();
  initChat();
  await initConversationTabs();
  initFileUpload();
  initStopButton();
  initCopyButtons();
  initThemeToggle();
  initPermissionSelect();
  initMemoryEditor();
  initSettings();
  initProviderManagement();
  initTaskManagement();
  loadSystemStatus();
  loadProviders();
  connectWebSocket();
  startNotificationPolling();

  window.addEventListener('beforeunload', () => {
    // 只保存“已加载”的会话（避免用空 messages 覆盖磁盘）
    Object.keys(state.sessions).forEach(sid => {
      const sess = state.sessions[sid];
      if (sess && sess._loaded !== false) {
        saveSessionToBackend(sid);
      }
    });
    navigator.sendBeacon(API_BASE + '/api/shutdown');
  });
});

// ─── Navigation ──────────────────────────────────────────────────
function initNavigation() {
  $$('.nav-item').forEach(btn => {
    btn.addEventListener('click', () => {
      const view = btn.dataset.view;
      switchView(view);
    });
  });
}

function switchView(viewName) {
  state.currentView = viewName;
  $$('.nav-item').forEach(b => b.classList.toggle('active', b.dataset.view === viewName));
  $$('.view').forEach(v => v.classList.toggle('active', v.id === `view-${viewName}`));
  if (viewName === 'skills') loadSkills();
  if (viewName === 'tasks') { loadTasks(); loadUserTasks(); }
  if (viewName === 'memory') loadMemory(state.currentMemoryTab);
  if (viewName === 'settings') { loadSettings(); loadProviderList(); }
}

// ─── WebSocket ───────────────────────────────────────────────────
function connectWebSocket() {
  if (state.ws && state.ws.readyState === WebSocket.OPEN) return;
  state.ws = new WebSocket(WS_URL);
  state.ws.onopen = () => updateConnectionStatus(true);
  state.ws.onclose = () => { updateConnectionStatus(false); setTimeout(connectWebSocket, 3000); };
  state.ws.onerror = () => updateConnectionStatus(false);
  state.ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      handleStreamEvent(data);
    } catch (e) { console.error('WS parse error:', e); }
  };
}

function updateConnectionStatus(connected) {
  const dot = $('#connection-status .status-dot');
  const text = $('#connection-status .status-text');
  if (connected) {
    dot.className = 'status-dot connected';
    text.textContent = 'Connected';
  } else {
    dot.className = 'status-dot disconnected';
    text.textContent = 'Disconnected';
  }
}

// ─── Conversation Management ─────────────────────────────────────
async function initConversationTabs() {
  $('#new-chat-btn').addEventListener('click', createNewConversation);

  try {
    const resp = await fetch(`${API_BASE}/api/sessions/persisted`);
    const data = await resp.json();
    const saved = data.sessions || [];

    if (saved.length > 0) {
      saved.forEach(s => {
        state.sessions[s.id] = {
          name: s.name || '',
          messages: [],
          _loaded: false,
          _isNotifications: s.id === 'notifications',
        };
      });
      const firstNonNotif = saved.find(s => s.id !== 'notifications');
      state.activeSession = (firstNonNotif || saved[0]).id;
      renderConversationTabs();
      await switchToConversation(state.activeSession);
    } else {
      await createNewConversation();
    }
  } catch (e) {
    console.error('恢复会话失败：', e);
    await createNewConversation();
  }
}

async function createNewConversation() {
  try {
    const resp = await fetch(`${API_BASE}/api/sessions`, { method: 'POST' });
    const data = await resp.json();
    const sid = data.session_id;
    state.sessions[sid] = { name: '', messages: [], _loaded: true };
    state.activeSession = sid;
    renderConversationTabs();
    switchToConversation(sid);
  } catch (e) {
    const sid = 'local-' + Date.now();
    state.sessions[sid] = { name: '', messages: [], _loaded: true };
    state.activeSession = sid;
    renderConversationTabs();
    switchToConversation(sid);
  }
}

function renderConversationTabs() {
  const container = $('#conversation-list');

  const entries = Object.entries(state.sessions);
  entries.sort(([sidA], [sidB]) => {
    if (sidA === 'notifications') return -1;
    if (sidB === 'notifications') return 1;
    return 0;
  });

  container.innerHTML = entries.map(([sid, s]) => {
    const displayName = s.name || 'New Chat';
    const isNotif = sid === 'notifications';
    const hasUnread = isNotif && state._unreadNotifCount > 0;
    const notifClass = isNotif ? ' conv-notif' : '';
    const unreadClass = hasUnread ? ' conv-unread' : '';
    const closeBtn = isNotif ? '' : `<button class="conv-close" data-sid="${sid}" title="Close">×</button>`;
    const badge = hasUnread ? `<span class="conv-badge">${state._unreadNotifCount}</span>` : '';

    return `
    <div class="conv-tab${notifClass}${unreadClass} ${sid === state.activeSession ? 'active' : ''}" data-sid="${sid}">
      <span class="conv-name" data-sid="${sid}">${escapeHtml(displayName)}${badge}</span>
      ${closeBtn}
    </div>
  `;
  }).join('');

  container.querySelectorAll('.conv-tab').forEach(tab => {
    tab.addEventListener('click', (e) => {
      if (e.target.classList.contains('conv-close')) return;
      if (e.target.classList.contains('conv-name-edit')) return;
      switchToConversation(tab.dataset.sid);
    });
  });
  container.querySelectorAll('.conv-close').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      closeConversation(btn.dataset.sid);
    });
  });
  container.querySelectorAll('.conv-tab').forEach(tab => {
    tab.addEventListener('contextmenu', (e) => {
      e.preventDefault();
      e.stopPropagation();
      showConvContextMenu(e.clientX, e.clientY, tab.dataset.sid);
    });
  });
}

async function switchToConversation(sid) {
  state.activeSession = sid;

  // 如果切到通知会话，标记所有通知为已读
  if (sid === 'notifications' && state._unreadNotifCount > 0) {
    try {
      const resp = await fetch(`${API_BASE}/api/notifications?unread=true`);
      const data = await resp.json();
      const ids = (data.notifications || []).map(n => n.id);
      if (ids.length > 0) {
        await fetch(`${API_BASE}/api/notifications/read`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ids }),
        });
      }
      state._unreadNotifCount = 0;
      renderConversationTabs();
    } catch (e) {
      console.error('标记通知已读失败：', e);
    }
  }

  const sess = state.sessions[sid];
  if (sess && !sess._loaded) {
    try {
      const resp = await fetch(`${API_BASE}/api/sessions/${sid}/messages`);
      const data = await resp.json();
      sess.messages = data.messages || [];
      sess.name = data.name || sess.name;
      sess._loaded = true;
    } catch (e) {
      console.error('加载会话消息失败：', e);
      sess._loaded = true;
    }
  }

  renderConversationTabs();
  renderChatMessages();
  if ($('#chat-input')) $('#chat-input').focus();
}

async function closeConversation(sid) {
  if (sid === 'notifications') {
    alert('通知会话不能关闭。');
    return;
  }
  const ids = Object.keys(state.sessions);
  if (ids.length <= 1) return;

  const sess = state.sessions[sid];
  const name = sess?.name || 'New Chat';
  const msgCount = sess?.messages?.length || 0;
  const confirmed = confirm(`确定关闭对话「${name}」吗？\n（${msgCount} 条消息将被删除，不可恢复）`);
  if (!confirmed) return;

  if (state.isStreaming && state.activeSession === sid) {
    await stopGeneration();
  }

  try { await fetch(`${API_BASE}/api/sessions/${sid}`, { method: 'DELETE' }); } catch (e) {}

  delete state.sessions[sid];
  delete state._saveTimers[sid];
  if (state.activeSession === sid) {
    const remaining = Object.keys(state.sessions);
    state.activeSession = remaining[remaining.length - 1] || null;
    switchToConversation(state.activeSession);
  } else {
    renderConversationTabs();
  }
}

// ─── Session Persistence ───────────────────────────────────────
function scheduleSaveSession(sid) {
  const sess = state.sessions[sid];
  // 没加载过的会话，不要保存（避免用空 messages 覆盖磁盘）
  if (!sess || sess._loaded === false) return;

  if (state._saveTimers[sid]) {
    clearTimeout(state._saveTimers[sid]);
  }
  state._saveTimers[sid] = setTimeout(() => {
    saveSessionToBackend(sid);
    delete state._saveTimers[sid];
  }, 1000);
}

async function saveSessionToBackend(sid) {
  const sess = state.sessions[sid];
  if (!sess) return;
  // 没加载过的会话，不要保存（避免用空 messages 覆盖磁盘）
  if (sess._loaded === false) return;
  try {
    await fetch(`${API_BASE}/api/sessions/${sid}/messages`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        messages: sess.messages,
        name: sess.name || '',
      }),
    });
  } catch (e) {
    console.error('保存会话失败：', e);
  }
}

// ─── Session Naming ────────────────────────────────────────────
function autoNameFromMessage(text) {
  const cleaned = String(text).replace(/\s+/g, ' ').trim();
  const maxLen = 15;
  if (cleaned.length <= maxLen) return cleaned;
  return cleaned.slice(0, maxLen) + '…';
}

function startRenameSession(sid) {
  const nameEl = document.querySelector(`.conv-name[data-sid="${sid}"]`);
  if (!nameEl) return;
  const current = state.sessions[sid]?.name || '';

  const input = document.createElement('input');
  input.type = 'text';
  input.className = 'conv-name-edit';
  input.value = current;
  input.maxLength = 40;

  nameEl.replaceWith(input);
  input.focus();
  input.select();

  const commit = () => {
    const newName = input.value.trim();
    if (newName && state.sessions[sid]) {
      state.sessions[sid].name = newName;
      scheduleSaveSession(sid);
    }
    renderConversationTabs();
  };

  input.addEventListener('blur', commit);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      input.blur();
    } else if (e.key === 'Escape') {
      input.value = state.sessions[sid]?.name || '';
      input.blur();
    }
  });
}

function showConvContextMenu(x, y, sid) {
  const existing = document.getElementById('conv-context-menu');
  if (existing) existing.remove();

  const menu = document.createElement('div');
  menu.id = 'conv-context-menu';
  menu.className = 'conv-context-menu';
  menu.style.left = x + 'px';
  menu.style.top = y + 'px';
  menu.innerHTML = `
    <div class="ctx-item" data-action="rename">✏️ 重命名</div>
    <div class="ctx-item" data-action="close">🗑️ 关闭</div>
  `;
  document.body.appendChild(menu);

  menu.querySelectorAll('.ctx-item').forEach(item => {
    item.addEventListener('click', () => {
      const action = item.dataset.action;
      menu.remove();
      if (action === 'rename') startRenameSession(sid);
      else if (action === 'close') closeConversation(sid);
    });
  });

  setTimeout(() => {
    const closeMenu = (ev) => {
      if (!menu.contains(ev.target)) {
        menu.remove();
        document.removeEventListener('click', closeMenu);
      }
    };
    document.addEventListener('click', closeMenu);
  }, 0);
}

// ─── Chat Functions ──────────────────────────────────────────────
function initChat() {
  const input = $('#chat-input');
  const sendBtn = $('#btn-send');
  const clearBtn = $('#btn-clear');

  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  input.addEventListener('input', () => {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 120) + 'px';
  });

  sendBtn.addEventListener('click', sendMessage);
  clearBtn.addEventListener('click', clearChat);

  $('#chat-messages').addEventListener('click', (e) => {
    if (e.target.classList.contains('quick-btn')) {
      const msg = e.target.dataset.msg;
      if (msg) { $('#chat-input').value = msg; sendMessage(); }
    }
  });
}

async function sendMessage() {
  const input = $('#chat-input');
  const msg = input.value.trim();
  if (!msg || state.isStreaming) return;

  const sid = state.activeSession;
  if (!sid) return;

  let finalMsg = msg;
  if (state.pendingFiles.length > 0) {
    const fileInfo = state.pendingFiles.map(f => f._serverPath || f.name).join(', ');
    finalMsg = `[Attached files: ${fileInfo}]\n${msg}`;
    state.pendingFiles = [];
    $('#attachments-preview').style.display = 'none';
    $('#attachments-preview').innerHTML = '';
  }

  input.value = '';
  input.style.height = 'auto';

  const welcome = $('#chat-messages .welcome-message');
  if (welcome) welcome.style.display = 'none';

  const sess = state.sessions[sid];
  if (sess && !sess.name && sess.messages.length === 0) {
    sess.name = autoNameFromMessage(msg);
    renderConversationTabs();
  }

  addMessageToSession(sid, 'user', finalMsg);
  appendMessageElement('user', finalMsg);

  const thinkingId = appendThinking();

  state.isStreaming = true;
  $('#btn-send').disabled = true;
  $('#btn-stop').style.display = 'flex';
  $('#btn-attach').disabled = true;

  try {
    if (state.ws && state.ws.readyState === WebSocket.OPEN) {
      state.ws.send(JSON.stringify({
        message: finalMsg,
        session_id: sid,
      }));
      state._currentThinkingId = thinkingId;
    } else {
      const resp = await fetch(`${API_BASE}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: finalMsg, session_id: sid }),
      });
      const data = await resp.json();
      removeThinking(thinkingId);
      if (data.response) {
        addMessageToSession(sid, 'assistant', data.response);
        appendMessageElement('assistant', data.response);
      } else if (data.error) {
        appendMessageElement('system', 'Error: ' + data.error);
      }
      endStreaming();
    }
  } catch (e) {
    removeThinking(thinkingId);
    appendMessageElement('system', 'Connection failed: ' + e.message);
    endStreaming();
  }
}

function endStreaming() {
  state.isStreaming = false;
  $('#btn-send').disabled = false;
  $('#btn-stop').style.display = 'none';
  $('#btn-attach').disabled = false;
}

// ─── Stop Generation ────────────────────────────────────────────
function initStopButton() {
  $('#btn-stop').addEventListener('click', stopGeneration);
}

async function stopGeneration() {
  const sid = state.activeSession;
  if (!sid) return;
  try {
    await fetch(`${API_BASE}/api/stop/${sid}`, { method: 'POST' });
  } catch (e) {}
  if (state.ws) { state.ws.close(); state.ws = null; }
  setTimeout(connectWebSocket, 500);
  endStreaming();
  removeThinking(state._currentThinkingId);
}

// ─── File Upload ────────────────────────────────────────────────
function initFileUpload() {
  $('#btn-attach').addEventListener('click', () => $('#file-input').click());
  $('#btn-workdir-select').addEventListener('click', selectWorkDir);
  $('#file-input').addEventListener('change', handleFileSelect);
}

async function handleFileSelect(e) {
  const files = Array.from(e.target.files);
  if (files.length === 0) return;

  const preview = $('#attachments-preview');
  preview.style.display = 'flex';

  for (const file of files) {
    state.pendingFiles.push(file);

    const formData = new FormData();
    formData.append('file', file);
    formData.append('session_id', state.activeSession || 'default');

    try {
      const resp = await fetch(`${API_BASE}/api/upload`, { method: 'POST', body: formData });
      const data = await resp.json();
      file._serverPath = data.path;
      const chip = document.createElement('span');
      chip.className = 'attach-chip';
      chip.innerHTML = `${getFileIcon(file.name)} ${escapeHtml(file.name)} <button class="chip-remove" data-name="${escapeHtml(file.name)}">×</button>`;
      preview.appendChild(chip);
    } catch (e) {
      const chip = document.createElement('span');
      chip.className = 'attach-chip error';
      chip.textContent = `Failed: ${file.name}`;
      preview.appendChild(chip);
    }
  }

  preview.querySelectorAll('.chip-remove').forEach(btn => {
    btn.addEventListener('click', () => {
      state.pendingFiles = state.pendingFiles.filter(f => f.name !== btn.dataset.name);
      btn.parentElement.remove();
      if (state.pendingFiles.length === 0) {
        preview.style.display = 'none';
        preview.innerHTML = '';
      }
    });
  });

  $('#file-input').value = '';
}

function getFileIcon(filename) {
  const ext = filename.split('.').pop().toLowerCase();
  const map = { pdf: '📄', docx: '📝', doc: '📝', xlsx: '📊', xls: '📊', pptx: '📽️', ppt: '📽️', py: '🐍', js: '📜', txt: '📃', md: '📋', csv: '📊', json: '📋', zip: '📦', png: '🖼️', jpg: '🖼️', jpeg: '🖼️', gif: '🖼️' };
  return map[ext] || '📎';
}

async function selectWorkDir() {
  const path = prompt('Enter work directory path:');
  if (!path) return;
  try {
    const resp = await fetch(`${API_BASE}/api/workdir?session_id=${encodeURIComponent(state.activeSession || 'default')}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
    });
    const data = await resp.json();
    appendMessageElement('system', data.message || 'Work directory updated');
  } catch (e) {
    appendMessageElement('system', 'Failed to set work directory: ' + e.message);
  }
}

// ─── Stream Event Handling ──────────────────────────────────────
function handleStreamEvent(event) {
  const thinkingId = state._currentThinkingId;

  switch (event.type) {
    case 'start':
      break;
    case 'thinking':
      if (thinkingId && state._currentThinkingBlock) {
        updateThinkingBlock(state._currentThinkingBlock, event.content);
      } else if (thinkingId) {
        removeThinking(thinkingId);
        state._currentThinkingId = null;
        state._currentThinkingBlock = appendThinkingBlock(event.content);
      }
      break;
    case 'tool_call':
      collapseThinkingBlock();
      if (thinkingId) { removeThinking(thinkingId); state._currentThinkingId = null; }
      appendToolCall(event.name, event.args);
      break;
    case 'tool_result':
      appendToolResult(event.name, event.content);
      break;
    case 'final':
      collapseThinkingBlock();
      if (thinkingId) { removeThinking(thinkingId); state._currentThinkingId = null; }
      addMessageToSession(state.activeSession, 'assistant', event.content);
      appendMessageElement('assistant', event.content);
      endStreaming();
      break;
    case 'done':
      collapseThinkingBlock();
      if (thinkingId) { removeThinking(thinkingId); state._currentThinkingId = null; }
      endStreaming();
      break;
    case 'stopped':
      collapseThinkingBlock();
      appendMessageElement('system', event.content || '[Generation stopped]');
      endStreaming();
      break;
    case 'error':
      collapseThinkingBlock();
      if (thinkingId) { removeThinking(thinkingId); state._currentThinkingId = null; }
      appendMessageElement('system', 'Error: ' + event.content);
      endStreaming();
      break;
  }
}

// ─── Session Memory ─────────────────────────────────────────────
function addMessageToSession(sid, role, content) {
  if (!state.sessions[sid]) return;
  state.sessions[sid].messages.push({ role, content, time: Date.now() });
  scheduleSaveSession(sid);
}

function renderChatMessages() {
  const container = $('#chat-messages');
  const sid = state.activeSession;
  container.innerHTML = '';

  if (!sid || !state.sessions[sid] || state.sessions[sid].messages.length === 0) {
    container.innerHTML = `
      <div class="welcome-message">
        <div class="welcome-icon">🌱</div>
        <h3>欢迎使用 Sprout</h3>
        <p>我是你的学习成长助手，可以帮你：</p>
        <div class="capability-cards">
          <div class="cap-card">📑 <span>找论文</span></div>
          <div class="cap-card">📝 <span>读文献</span></div>
          <div class="cap-card">✏️ <span>出题练习</span></div>
          <div class="cap-card">🧠 <span>知识卡片</span></div>
          <div class="cap-card">🔍 <span>知识检索</span></div>
          <div class="cap-card">🗺️ <span>知识地图</span></div>
        </div>
        <div class="quick-actions">
          <button class="quick-btn" data-msg="你有哪些技能？">⚡ 查看技能</button>
          <button class="quick-btn" data-msg="帮我找最新的 AI 论文">📑 找论文</button>
          <button class="quick-btn" data-msg="帮我生成今天的学习报告">📝 学习报告</button>
          <button class="quick-btn" data-msg="搜索最新的AI新闻">🌐 联网搜索</button>
        </div>
      </div>`;
    return;
  }

  state.sessions[sid].messages.forEach(m => {
    appendMessageElement(m.role, m.content, false);
  });
  container.scrollTop = container.scrollHeight;
}

function appendMessageElement(role, content, scroll = true) {
  const container = $('#chat-messages');
  const div = document.createElement('div');
  div.className = `message ${role}`;

  if (role === 'user') {
    div.innerHTML = `
      <div class="msg-content">${escapeHtml(content)}</div>
      <button class="btn-copy-msg" title="Copy">📋</button>
    `;
  } else if (role === 'assistant') {
    div.innerHTML = `
      <div class="msg-avatar">🌱</div>
      <div class="msg-content">${formatContent(content)}</div>
      <button class="btn-copy-msg" title="Copy">📋</button>
    `;
  } else {
    div.innerHTML = `<div class="msg-content">${escapeHtml(content)}</div>`;
  }

  const copyBtn = div.querySelector('.btn-copy-msg');
  if (copyBtn) {
    copyBtn.addEventListener('click', () => {
      copyToClipboard(content);
      copyBtn.textContent = '✅';
      setTimeout(() => { copyBtn.textContent = '📋'; }, 1500);
    });
  }

  container.appendChild(div);
  if (scroll) container.scrollTop = container.scrollHeight;
  return div;
}

function appendThinking() {
  const container = $('#chat-messages');
  const div = document.createElement('div');
  div.className = 'message assistant';
  const id = 'thinking-' + Date.now();
  div.id = id;
  div.innerHTML = `
    <div class="msg-avatar">🌱</div>
    <div class="msg-content">
      <div class="thinking-dots"><span></span><span></span><span></span></div>
    </div>
  `;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
  return id;
}

function removeThinking(id) {
  if (id) { const el = document.getElementById(id); if (el) el.remove(); }
}

function appendThinkingBlock(content) {
  const container = $('#chat-messages');
  const div = document.createElement('div');
  div.className = 'message assistant';
  const id = 'think-' + Date.now();
  div.id = id;
  const preview = summarizeThinking(content);
  div.innerHTML = `
    <div class="msg-avatar">🌱</div>
    <div class="msg-content">
      <div class="thinking-block">
        <div class="thinking-header" onclick="toggleThinkingBlock('${id}')">
          <span class="think-icon">🧠</span>
          <span class="think-label">Thinking</span>
          <span class="think-preview">${escapeHtml(preview)}</span>
          <span class="think-toggle">▸</span>
        </div>
        <div class="thinking-body" style="display:none;">
          <div class="thinking-text">${escapeHtml(content)}</div>
        </div>
      </div>
    </div>
  `;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
  return id;
}

function updateThinkingBlock(id, content) {
  const el = document.getElementById(id);
  if (!el) return;
  const textEl = el.querySelector('.thinking-text');
  const previewEl = el.querySelector('.think-preview');
  if (textEl) textEl.textContent = content;
  if (previewEl) previewEl.textContent = summarizeThinking(content);
  const container = $('#chat-messages');
  container.scrollTop = container.scrollHeight;
}

function collapseThinkingBlock() {
  if (state._currentThinkingBlock) {
    const el = document.getElementById(state._currentThinkingBlock);
    if (el) {
      const body = el.querySelector('.thinking-body');
      const toggle = el.querySelector('.think-toggle');
      if (body && body.style.display !== 'none') {
        body.style.display = 'none';
        if (toggle) toggle.textContent = '▸';
      }
      el.querySelector('.thinking-header').classList.add('collapsed');
    }
    state._currentThinkingBlock = null;
  }
}

function toggleThinkingBlock(id) {
  const el = document.getElementById(id);
  if (!el) return;
  const body = el.querySelector('.thinking-body');
  const toggle = el.querySelector('.think-toggle');
  const header = el.querySelector('.thinking-header');
  if (body.style.display === 'none') {
    body.style.display = 'block';
    if (toggle) toggle.textContent = '▾';
    header.classList.remove('collapsed');
  } else {
    body.style.display = 'none';
    if (toggle) toggle.textContent = '▸';
    header.classList.add('collapsed');
  }
}

function summarizeThinking(text) {
  if (!text) return '...';
  const firstLine = text.split('\n')[0].trim();
  if (firstLine.length <= 80) return firstLine;
  return firstLine.substring(0, 80) + '...';
}

function appendToolCall(name, args) {
  const container = $('#chat-messages');
  const div = document.createElement('div');
  div.className = 'message assistant';
  const argsStr = typeof args === 'object' ? JSON.stringify(args, null, 2) : String(args);
  div.innerHTML = `
    <div class="msg-avatar">🌱</div>
    <div class="msg-content">
      <div class="tool-call-block">
        <div class="tool-call-header">🔧 ${escapeHtml(name)}</div>
        <div class="tool-call-body">${escapeHtml(argsStr)}</div>
      </div>
    </div>
  `;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
}

function appendToolResult(name, content) {
  const container = $('#chat-messages');
  const div = document.createElement('div');
  div.className = 'message assistant';
  div.innerHTML = `
    <div class="msg-avatar">🌱</div>
    <div class="msg-content">
      <div class="tool-result-block">
        <div class="tool-result-header">✅ ${escapeHtml(name)}</div>
        <div class="tool-result-body">${escapeHtml(content)}</div>
      </div>
    </div>
  `;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
}

async function clearChat() {
  const sid = state.activeSession;
  if (sid && state.sessions[sid]) {
    state.sessions[sid].messages = [];
    scheduleSaveSession(sid);
  }
  renderChatMessages();
  try { await fetch(`${API_BASE}/api/clear?session_id=${encodeURIComponent(sid || 'default')}`, { method: 'POST' }); } catch (e) {}
}

function initCopyButtons() {}

async function copyToClipboard(text) {
  try {
    await navigator.clipboard.writeText(text);
  } catch (e) {
    const ta = document.createElement('textarea');
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
  }
}

// ─── Notifications ──────────────────────────────────────────────
let _notifTimer = null;

function startNotificationPolling() {
  if (_notifTimer) clearInterval(_notifTimer);
  _notifTimer = setInterval(checkNotifications, 30000);
  setTimeout(checkNotifications, 3000);
}

async function checkNotifications() {
  try {
    const resp = await fetch(`${API_BASE}/api/notifications?unread=true`);
    const data = await resp.json();
    const notifs = data.notifications || [];

    const oldCount = state._unreadNotifCount;
    state._unreadNotifCount = notifs.length;

    if (oldCount !== state._unreadNotifCount) {
      renderConversationTabs();
    }

    if (notifs.length === 0) return;

    if (state.sessions['notifications']) {
      state.sessions['notifications']._loaded = false;
      if (state.activeSession === 'notifications') {
        await switchToConversation('notifications');
      }
    } else {
      try {
        const resp2 = await fetch(`${API_BASE}/api/sessions/persisted`);
        const data2 = await resp2.json();
        const saved = data2.sessions || [];
        const notifSession = saved.find(s => s.id === 'notifications');
        if (notifSession) {
          state.sessions['notifications'] = {
            name: notifSession.name || '🔔 通知',
            messages: [],
            _loaded: false,
            _isNotifications: true,
          };
          renderConversationTabs();
        }
      } catch (e) {}
    }
  } catch (e) {
    console.error('检查通知失败：', e);
  }
}

// ─── System Status ──────────────────────────────────────────────
async function loadSystemStatus() {
  try {
    const resp = await fetch(`${API_BASE}/api/status`);
    const data = await resp.json();
    const provider = data.activeProvider;
    if (provider) {
      state._currentProviderModels = provider.models || {};
      updateTierSelect();
    } else {
      $('#tier-select').innerHTML = '<option value="">No Model</option>';
    }
  } catch (e) {
    $('#tier-select').innerHTML = '<option value="">Offline</option>';
  }
}

function updateTierSelect() {
  const models = state._currentProviderModels || {};
  const currentTier = models.default || 'sonnet';
  const tiers = [];
  if (models.opus) tiers.push(['opus', `Opus: ${models.opus}`]);
  if (models.sonnet) tiers.push(['sonnet', `Sonnet: ${models.sonnet}`]);
  if (models.haiku) tiers.push(['haiku', `Haiku: ${models.haiku}`]);
  $('#tier-select').innerHTML = tiers.map(([k,v]) =>
    `<option value="${k}" ${k === currentTier ? 'selected' : ''}>${escapeHtml(v)}</option>`
  ).join('');
}

// ─── Provider Management ────────────────────────────────────────
async function loadProviders() {
  try {
    const resp = await fetch(`${API_BASE}/api/providers`);
    const data = await resp.json();
    state.providers = data.providers || [];
    state.activeProviderId = data.activeId || '';
    updateProviderSelect();
  } catch (e) { console.error('Load providers error:', e); }
}

function updateProviderSelect() {
  const select = $('#provider-select');
  select.innerHTML = '<option value="">Select Provider</option>';
  state.providers.forEach(p => {
    const opt = document.createElement('option');
    opt.value = p.id;
    opt.textContent = p.name;
    if (p.id === state.activeProviderId) opt.selected = true;
    select.appendChild(opt);
  });
}

function initProviderManagement() {
  $('#provider-select').addEventListener('change', async (e) => {
    const providerId = e.target.value;
    if (!providerId) return;
    try {
      const resp = await fetch(`${API_BASE}/api/providers/switch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider_id: providerId }),
      });
      const data = await resp.json();
      if (data.status === 'ok') {
        state.activeProviderId = providerId;
        updateProviderSelect();
        loadSystemStatus();
        appendMessageElement('system', `Switched to ${data.activeProvider?.name || providerId}. Provider change takes effect on new conversations.`);
      }
    } catch (e) {
      appendMessageElement('system', 'Provider switch failed: ' + e.message);
    }
  });

  $('#tier-select').addEventListener('change', async (e) => {
    const tier = e.target.value;
    if (!tier || !state.activeProviderId) return;
    const provider = state.providers.find(p => p.id === state.activeProviderId);
    if (!provider) return;
    provider.models.default = tier;
    await fetch(`${API_BASE}/api/providers/${state.activeProviderId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ models: provider.models }),
    });
    await fetch(`${API_BASE}/api/providers/switch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider_id: state.activeProviderId }),
    });
    updateTierSelect();
  });

  $('#btn-add-provider')?.addEventListener('click', () => {
    $('#provider-modal-title').textContent = 'Add Provider';
    $('#provider-edit-id').value = '';
    $('#provider-name').value = '';
    $('#provider-apikey').value = '';
    $('#provider-baseurl').value = '';
    $('#provider-format').value = 'openai';
    $('#provider-runtime').value = 'deepseek';
    $('#provider-opus-model').value = '';
    $('#provider-sonnet-model').value = '';
    $('#provider-haiku-model').value = '';
    $('#provider-default-tier').value = 'sonnet';
    $('#provider-modal').style.display = 'flex';
  });

  $('#btn-close-provider-modal')?.addEventListener('click', () => {
    $('#provider-modal').style.display = 'none';
  });

  $('#btn-cancel-provider')?.addEventListener('click', () => {
    $('#provider-modal').style.display = 'none';
  });

  $('#btn-save-provider')?.addEventListener('click', saveProvider);

  $('#provider-modal')?.addEventListener('click', (e) => {
    if (e.target === $('#provider-modal')) {
      $('#provider-modal').style.display = 'none';
    }
  });

  $('#btn-close-skill-modal')?.addEventListener('click', () => {
    $('#skill-modal').style.display = 'none';
  });
  $('#skill-modal')?.addEventListener('click', (e) => {
    if (e.target === $('#skill-modal')) {
      $('#skill-modal').style.display = 'none';
    }
  });
}

async function saveProvider() {
  const editId = $('#provider-edit-id').value;
  const provider = {
    name: $('#provider-name').value.trim(),
    apiKey: $('#provider-apikey').value.trim(),
    baseUrl: $('#provider-baseurl').value.trim(),
    apiFormat: $('#provider-format').value,
    runtimeKind: $('#provider-runtime').value,
    models: {
      opus: $('#provider-opus-model').value.trim(),
      sonnet: $('#provider-sonnet-model').value.trim(),
      haiku: $('#provider-haiku-model').value.trim(),
      default: $('#provider-default-tier').value,
    },
  };

  if (!provider.name || !provider.apiKey || !provider.baseUrl || !provider.models.sonnet) {
    alert('Please fill in all required fields: Name, API Key, Base URL, Sonnet Model');
    return;
  }

  try {
    let resp;
    if (editId) {
      resp = await fetch(`${API_BASE}/api/providers/${editId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(provider),
      });
    } else {
      resp = await fetch(`${API_BASE}/api/providers`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(provider),
      });
    }
    const data = await resp.json();
    if (data.status === 'ok') {
      $('#provider-modal').style.display = 'none';
      await loadProviders();
      loadProviderList();
      updateProviderSelect();
      if (editId === state.activeProviderId) {
        await fetch(`${API_BASE}/api/providers/switch`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ provider_id: editId }),
        });
        loadSystemStatus();
      }
    }
  } catch (e) {
    alert('Failed to save provider: ' + e.message);
  }
}

async function editProvider(providerId) {
  const p = state.providers.find(p => p.id === providerId);
  if (!p) return;
  $('#provider-modal-title').textContent = 'Edit Provider';
  $('#provider-edit-id').value = p.id;
  $('#provider-name').value = p.name || '';
  $('#provider-apikey').value = p.apiKey || '';
  $('#provider-baseurl').value = p.baseUrl || '';
  $('#provider-format').value = p.apiFormat || 'openai';
  $('#provider-runtime').value = p.runtimeKind || 'deepseek';
  $('#provider-opus-model').value = (p.models && p.models.opus) || '';
  $('#provider-sonnet-model').value = (p.models && p.models.sonnet) || (p.models && p.models.main) || '';
  $('#provider-haiku-model').value = (p.models && p.models.haiku) || '';
  $('#provider-default-tier').value = (p.models && p.models.default) || 'sonnet';
  $('#provider-modal').style.display = 'flex';
}

async function deleteProvider(providerId) {
  if (!confirm('Delete this provider?')) return;
  try {
    await fetch(`${API_BASE}/api/providers/${providerId}`, { method: 'DELETE' });
    await loadProviders();
    loadProviderList();
  } catch (e) {
    alert('Failed to delete: ' + e.message);
  }
}

function loadProviderList() {
  const container = $('#provider-list');
  if (!container) return;
  container.innerHTML = state.providers.map(p => `
    <div class="provider-item ${p.id === state.activeProviderId ? 'active' : ''}">
      <div class="provider-info">
        <strong>${escapeHtml(p.name)}</strong>
        <span class="provider-model">${escapeHtml((p.models && (p.models.sonnet || p.models.main)) || '')}</span>
        <span class="provider-url">${escapeHtml(p.baseUrl || '')}</span>
      </div>
      <div class="provider-actions">
        <button class="btn-sm btn-secondary" onclick="editProvider('${p.id}')">Edit</button>
        <button class="btn-sm btn-danger" onclick="deleteProvider('${p.id}')">Delete</button>
      </div>
    </div>
  `).join('');
}

// ─── Skills Panel ────────────────────────────────────────────────
async function loadSkills() {
  try {
    const resp = await fetch(`${API_BASE}/api/skills`);
    const skills = await resp.json();
    $('#skills-list').innerHTML = skills.map(s => `
      <div class="skill-card">
        <h3>⚡ ${escapeHtml(s.name)}</h3>
        <div class="skill-actions">
          <button class="btn-secondary" onclick="useSkill('${escapeHtml(s.name)}')">Use Skill</button>
          <button class="btn-secondary" onclick="viewSkillDetail('${escapeHtml(s.name)}')">Details</button>
        </div>
      </div>
    `).join('');
  } catch (e) { $('#skills-list').innerHTML = '<p>Load failed</p>'; }
}

function useSkill(name) {
  switchView('chat');
  $('#chat-input').value = `Use ${name} skill`;
  sendMessage();
}

async function viewSkillDetail(name) {
  try {
    const resp = await fetch(`${API_BASE}/api/skills/${name}`);
    const data = await resp.json();
    $('#skill-modal-title').textContent = `技能详情：${name}`;
    $('#skill-modal-content').textContent = data.content || '(无内容)';
    $('#skill-modal').style.display = 'flex';
  } catch (e) {
    alert('加载失败：' + e.message);
  }
}

// ─── Theme Toggle ──────────────────────────────────────────────
function initThemeToggle() {
  const btn = $('#btn-theme-toggle');
  if (!btn) return;
  btn.addEventListener('click', () => {
    const html = document.documentElement;
    const current = html.getAttribute('data-theme');
    const next = current === 'dark' ? 'light' : 'dark';
    html.setAttribute('data-theme', next);
    btn.textContent = next === 'dark' ? '🌙' : '☀️';
  });
}

// ─── Permission Select ─────────────────────────────────────────
function initPermissionSelect() {
  const sel = $('#permission-select');
  if (!sel) return;
  sel.addEventListener('change', async () => {
    const mode = sel.value;
    const sid = state.activeSession || 'default';
    try {
      await fetch(`${API_BASE}/api/permission/${sid}?mode=${mode}`, { method: 'POST' });
      appendMessageElement('system', '权限已切换为: ' + mode);
    } catch (e) {
      appendMessageElement('system', '权限切换失败: ' + e.message);
    }
  });
}

// ─── Memory Editor ──────────────────────────────────────────────
function initMemoryEditor() {
  $$('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      $$('.tab-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      state.currentMemoryTab = btn.dataset.tab;
      loadMemory(btn.dataset.tab);
    });
  });
  $('#btn-save-memory').addEventListener('click', saveMemory);
}

async function loadMemory(tab) {
  try {
    const resp = await fetch(`${API_BASE}/api/memory?session_id=${encodeURIComponent(state.activeSession || 'default')}`);
    const data = await resp.json();
    $('#memory-editor').value = data[tab] || '';
  } catch (e) { $('#memory-editor').value = 'Load failed'; }
}

async function saveMemory() {
  const content = $('#memory-editor').value;
  const tab = state.currentMemoryTab;
  try {
    const resp = await fetch(`${API_BASE}/api/memory/update?name=${tab}&content=${encodeURIComponent(content)}&session_id=${encodeURIComponent(state.activeSession || 'default')}`, { method: 'POST' });
    const data = await resp.json();
    if (data.status === 'ok') alert('Saved successfully');
  } catch (e) { alert('Save failed: ' + e.message); }
}

// ─── Tasks Panel ────────────────────────────────────────────────
async function loadTasks() {
  try {
    const resp = await fetch(`${API_BASE}/api/tasks`);
    const tasks = await resp.json();
    const container = $('#tasks-list');
    if (tasks.length === 0) {
      container.innerHTML = '<p style="color:var(--text-muted);text-align:center;padding:40px;">No running tasks</p>';
      return;
    }
    container.innerHTML = tasks.map(t => {
      const intervalStr = t.interval >= 60 ? `${Math.round(t.interval/60)}min` : `${t.interval}s`;
      const statusClass = t.running ? 'running' : 'stopped';
      const statusText = t.running ? 'Running' : 'Stopped';
      return `
        <div class="task-item">
          <div>
            <div class="task-name">${escapeHtml(t.name)}</div>
            <div class="task-interval">Interval: ${intervalStr} ${t.description ? '- ' + escapeHtml(t.description) : ''}</div>
          </div>
          <div class="task-status ${statusClass}">${statusText}</div>
        </div>`;
    }).join('');
  } catch (e) { $('#tasks-list').innerHTML = '<p>Load failed</p>'; }
}

// ─── User Tasks ─────────────────────────────────────────────────
function initTaskManagement() {
  $('#btn-add-task').addEventListener('click', () => openTaskModal(null));
  $('#btn-close-task-modal').addEventListener('click', () => {
    $('#task-modal').style.display = 'none';
  });
  $('#btn-cancel-task').addEventListener('click', () => {
    $('#task-modal').style.display = 'none';
  });
  $('#btn-save-task').addEventListener('click', saveUserTask);
  $('#task-modal').addEventListener('click', (e) => {
    if (e.target === $('#task-modal')) $('#task-modal').style.display = 'none';
  });

  $('#task-action').addEventListener('change', updateTaskParamVisibility);
  $('#task-schedule-type').addEventListener('change', updateTaskScheduleVisibility);
}

function updateTaskParamVisibility() {
  const action = $('#task-action').value;
  $('#task-params-arxiv').style.display = action === 'fetch_arxiv' ? 'flex' : 'none';
  $('#task-params-study').style.display = action === 'generate_study_report' ? 'flex' : 'none';
}

function updateTaskScheduleVisibility() {
  const type = $('#task-schedule-type').value;
  $('#task-time-group').style.display = (type === 'daily' || type === 'weekly') ? 'flex' : 'none';
  $('#task-weekday-group').style.display = type === 'weekly' ? 'flex' : 'none';
  $('#task-interval-group').style.display = type === 'interval' ? 'flex' : 'none';
}

async function loadUserTasks() {
  try {
    const resp = await fetch(`${API_BASE}/api/user_tasks`);
    const data = await resp.json();
    const tasks = data.tasks || [];
    const container = $('#user-tasks-list');
    if (tasks.length === 0) {
      container.innerHTML = '<p style="color:var(--text-muted);text-align:center;padding:20px;">还没有自定义任务。点右上角"+ 新建任务"添加。</p>';
      return;
    }
    container.innerHTML = tasks.map(t => {
      const sched = t.schedule || {};
      let schedStr = '';
      if (sched.type === 'daily') schedStr = `每天 ${sched.time || '?'}`;
      else if (sched.type === 'weekly') {
        const wd = ['周一','周二','周三','周四','周五','周六','周日'][parseInt(sched.weekday) || 0];
        schedStr = `每${wd} ${sched.time || '?'}`;
      } else if (sched.type === 'interval') schedStr = `每 ${sched.minutes || '?'} 分钟`;
      const statusClass = t.enabled ? 'running' : 'stopped';
      const statusText = t.enabled ? '已启用' : '已停用';
      return `
        <div class="task-item">
          <div>
            <div class="task-name">${escapeHtml(t.name || '未命名')}</div>
            <div class="task-interval">${schedStr} · ${escapeHtml(t.action || '')}</div>
            <div class="task-interval" style="font-size:11px;">上次运行：${t.last_run ? escapeHtml(t.last_run) : '从未'}</div>
          </div>
          <div style="display:flex;gap:8px;align-items:center;">
            <div class="task-status ${statusClass}">${statusText}</div>
            <button class="btn-sm btn-secondary" onclick="editUserTask('${t.id}')">编辑</button>
            <button class="btn-sm btn-danger" onclick="deleteUserTask('${t.id}')">删除</button>
          </div>
        </div>`;
    }).join('');
  } catch (e) {
    $('#user-tasks-list').innerHTML = '<p>加载失败</p>';
  }
}

async function openTaskModal(task) {
  if (task) {
    $('#task-modal-title').textContent = '编辑任务';
    $('#task-edit-id').value = task.id;
    $('#task-name').value = task.name || '';
    $('#task-action').value = task.action || 'generate_study_report';
    $('#task-enabled').checked = !!task.enabled;
    const params = task.params || {};
    $('#task-arxiv-query').value = params.query || '';
    $('#task-arxiv-max').value = params.max_results || 5;
    $('#task-arxiv-categories').value = params.categories || '';
    $('#task-arxiv-lookback').value = params.lookback_days || 0;
    $('#task-arxiv-detail').value = params.detail_level || 'brief';
    $('#task-arxiv-save').checked = params.save !== false;
    $('#task-arxiv-download-pdf').checked = params.download_pdf === true;
    $('#task-report-hours').value = params.hours || 24;
    const sched = task.schedule || {};
    $('#task-schedule-type').value = sched.type || 'daily';
    $('#task-time').value = sched.time || '20:00';
    $('#task-weekday').value = sched.weekday || 0;
    $('#task-interval').value = sched.minutes || 60;
  } else {
    $('#task-modal-title').textContent = '新建任务';
    $('#task-edit-id').value = '';
    $('#task-name').value = '';
    $('#task-action').value = 'generate_study_report';
    $('#task-enabled').checked = true;
    $('#task-arxiv-query').value = '';
    $('#task-arxiv-max').value = 5;
    $('#task-arxiv-categories').value = '';
    $('#task-arxiv-lookback').value = 0;
    $('#task-arxiv-detail').value = 'brief';
    $('#task-arxiv-save').checked = true;
    $('#task-arxiv-download-pdf').checked = false;
    $('#task-report-hours').value = 24;
    $('#task-schedule-type').value = 'daily';
    $('#task-time').value = '20:00';
    $('#task-weekday').value = 0;
    $('#task-interval').value = 60;
  }
  updateTaskParamVisibility();
  updateTaskScheduleVisibility();
  $('#task-modal').style.display = 'flex';
}

async function editUserTask(taskId) {
  try {
    const resp = await fetch(`${API_BASE}/api/user_tasks`);
    const data = await resp.json();
    const task = (data.tasks || []).find(t => t.id === taskId);
    if (task) openTaskModal(task);
  } catch (e) {}
}

async function saveUserTask() {
  const editId = $('#task-edit-id').value;
  const name = $('#task-name').value.trim();
  const action = $('#task-action').value;
  if (!name) {
    alert('请填写任务名称');
    return;
  }

  let params = {};
  if (action === 'fetch_arxiv') {
    params = {
      query: $('#task-arxiv-query').value.trim(),
      max_results: parseInt($('#task-arxiv-max').value) || 5,
      categories: $('#task-arxiv-categories').value.trim(),
      lookback_days: parseInt($('#task-arxiv-lookback').value) || 0,
      detail_level: $('#task-arxiv-detail').value || 'brief',
      save: $('#task-arxiv-save').checked,
      download_pdf: $('#task-arxiv-download-pdf').checked,
    };
  } else if (action === 'generate_study_report') {
    params = { hours: parseInt($('#task-report-hours').value) || 24 };
  }

  const stype = $('#task-schedule-type').value;
  let schedule = { type: stype };
  if (stype === 'daily') {
    schedule.time = $('#task-time').value || '20:00';
  } else if (stype === 'weekly') {
    schedule.time = $('#task-time').value || '20:00';
    schedule.weekday = parseInt($('#task-weekday').value) || 0;
  } else if (stype === 'interval') {
    schedule.minutes = parseInt($('#task-interval').value) || 60;
  }

  const payload = {
    name,
    action,
    params,
    schedule,
    enabled: $('#task-enabled').checked,
  };

  try {
    let resp;
    if (editId) {
      resp = await fetch(`${API_BASE}/api/user_tasks/${editId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
    } else {
      resp = await fetch(`${API_BASE}/api/user_tasks`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
    }
    if (!resp.ok) {
      const text = await resp.text();
      alert('保存失败：服务器返回 ' + resp.status + '\n' + text.slice(0, 200));
      return;
    }
    const data = await resp.json();
    if (data.status === 'ok') {
      $('#task-modal').style.display = 'none';
      loadUserTasks();
    }
  } catch (e) {
    alert('保存失败：' + e.message);
  }
}

async function deleteUserTask(taskId) {
  if (!confirm('确定删除这个任务吗？')) return;
  try {
    await fetch(`${API_BASE}/api/user_tasks/${taskId}`, { method: 'DELETE' });
    loadUserTasks();
  } catch (e) {
    alert('删除失败：' + e.message);
  }
}

// ─── Settings Panel ─────────────────────────────────────────────
function initSettings() {
  $('#btn-set-workdir').addEventListener('click', setWorkDir);
}

async function loadSettings() {
  try {
    const resp = await fetch(`${API_BASE}/api/status`);
    const data = await resp.json();
    $('#setting-model').textContent = data.model || '-';
    if (data.work_dir) $('#workdir-input').value = data.work_dir;
    const tc = $('#tools-list');
    tc.innerHTML = (data.tools || []).map(t =>
      `<div class="tool-badge"><strong>${escapeHtml(t)}</strong></div>`
    ).join('');
  } catch (e) {}
  try {
    const resp = await fetch(`${API_BASE}/api/about`);
    const about = await resp.json();
    if (about.author) {
      $('#about-author').textContent = about.author;
      $('#about-name').textContent = about.name || 'Sprout';
      $('#about-version').textContent = about.version || '-';
    }
  } catch (e) {}
}

async function setWorkDir() {
  const path = $('#workdir-input').value.trim();
  if (!path) return;
  try {
    const resp = await fetch(`${API_BASE}/api/workdir?session_id=${encodeURIComponent(state.activeSession || 'default')}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
    });
    const data = await resp.json();
    alert(data.message);
  } catch (e) { alert('Failed: ' + e.message); }
}

// ─── Utilities ──────────────────────────────────────────────────
function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function formatContent(text) {
  if (!text) return '';
  let html = escapeHtml(text);
  html = html.replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>');
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
  html = html.replace(/^- (.+)$/gm, '<li>$1</li>');
  return html;
}