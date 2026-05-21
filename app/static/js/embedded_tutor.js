/**
 * Embedded AI Tutor for Question Runner
 * Provides in-context tutoring without leaving the code editor.
 */
(function () {
  'use strict';

  const CONFIG = window.TUTOR_CONFIG || {};
  const questionId = CONFIG.questionId;
  const language = CONFIG.language || 'python';

  const panel = document.getElementById('aiTutorPanel');
  const tab = document.getElementById('aiTutorTab');
  const closeBtn = document.getElementById('aiTutorClose');
  const messagesDiv = document.getElementById('aiTutorMessages');
  const inputEl = document.getElementById('aiTutorInput');
  const sendBtn = document.getElementById('aiTutorSend');
  const statusEl = document.getElementById('aiTutorStatus');
  const quickBtns = document.querySelectorAll('.quick-action-btn');

  let conversationId = null;
  let isStreaming = false;

  // ── Panel toggle ──────────────────────────────────────────
  tab.addEventListener('click', () => panel.classList.remove('collapsed'));
  closeBtn.addEventListener('click', () => panel.classList.add('collapsed'));

  // Also open from the existing "Ask AI" button
  const askAiBtn = document.getElementById('askAiBtn');
  if (askAiBtn) {
    askAiBtn.addEventListener('click', function (e) {
      e.preventDefault();
      panel.classList.remove('collapsed');
    });
  }

  // ── Quick actions ─────────────────────────────────────────
  quickBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      const action = btn.dataset.action;
      const code = getEditorCode();
      const errorStatus = getLastErrorStatus();

      let message = '';
      if (action === 'hint') message = 'I need a hint for this problem.';
      if (action === 'explain_error') message = errorStatus
        ? `My code gives ${errorStatus}. Can you help me understand why?`
        : 'My code has an error. Can you help me understand it?';
      if (action === 'review') message = 'Please review my current code and suggest improvements.';

      if (message) sendMessage(message, code, errorStatus);
    });
  });

  // ── Send message ──────────────────────────────────────────
  sendBtn.addEventListener('click', () => {
    const msg = inputEl.value.trim();
    if (msg && !isStreaming) {
      sendMessage(msg, getEditorCode(), getLastErrorStatus());
      inputEl.value = '';
    }
  });

  inputEl.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendBtn.click();
    }
  });

  function sendMessage(message, code, errorStatus) {
    if (isStreaming) return;

    // Remove welcome message
    const welcome = messagesDiv.querySelector('.ai-tutor-welcome');
    if (welcome) welcome.remove();

    // Add user bubble
    appendMessage('user', message);

    // Build request
    const payload = {
      message: message,
      agent_type: 'tutor',
      question_id: questionId,
      conversation_id: conversationId,
    };
    if (code) payload.code = code;
    if (errorStatus) payload.error_status = errorStatus;

    streamResponse(payload);
  }

  function streamResponse(payload) {
    isStreaming = true;
    sendBtn.disabled = true;
    statusEl.textContent = 'Thinking...';
    statusEl.classList.add('streaming');

    // Add typing indicator
    const typingEl = document.createElement('div');
    typingEl.className = 'typing-indicator';
    typingEl.innerHTML = '<span></span><span></span><span></span>';
    messagesDiv.appendChild(typingEl);
    scrollToBottom();

    let assistantBubble = null;
    let fullContent = '';

    fetch('/api/v1/ai/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }).then(response => {
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      function processStream() {
        reader.read().then(({ done, value }) => {
          if (done) {
            finishStream();
            return;
          }

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() || '';

          for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            const data = line.slice(6).trim();
            if (data === '[DONE]') {
              finishStream();
              return;
            }

            try {
              const event = JSON.parse(data);
              handleEvent(event);
            } catch (e) {
              // skip unparseable
            }
          }

          processStream();
        }).catch(err => {
          appendMessage('error', 'Connection lost. Please try again.');
          finishStream();
        });
      }

      function handleEvent(event) {
        if (event.type === 'start') {
          conversationId = event.conversation_id;
        } else if (event.type === 'token') {
          // Remove typing indicator on first token
          if (typingEl.parentNode) typingEl.remove();

          if (!assistantBubble) {
            assistantBubble = document.createElement('div');
            assistantBubble.className = 'tutor-msg assistant';
            messagesDiv.appendChild(assistantBubble);
          }

          fullContent += event.content;
          assistantBubble.innerHTML = renderMarkdown(fullContent);
          scrollToBottom();
        } else if (event.type === 'tool_call') {
          if (typingEl.parentNode) typingEl.remove();
          appendMessage('tool-event', `🔧 Using: ${event.tool}`);
        } else if (event.type === 'tool_result') {
          appendMessage('tool-event', `✓ ${event.summary}`);
        } else if (event.type === 'error') {
          if (typingEl.parentNode) typingEl.remove();
          appendMessage('error', event.message || 'An error occurred.');
        } else if (event.type === 'done') {
          // handled by finishStream
        }
      }

      processStream();
    }).catch(err => {
      if (typingEl.parentNode) typingEl.remove();
      appendMessage('error', 'Failed to connect to AI service. Please try again.');
      finishStream();
    });

    function finishStream() {
      if (typingEl.parentNode) typingEl.remove();
      isStreaming = false;
      sendBtn.disabled = false;
      statusEl.textContent = 'Ready';
      statusEl.classList.remove('streaming');
      scrollToBottom();
    }
  }

  // ── Helpers ───────────────────────────────────────────────

  function appendMessage(type, content) {
    const el = document.createElement('div');
    el.className = `tutor-msg ${type}`;
    if (type === 'assistant') {
      el.innerHTML = renderMarkdown(content);
    } else {
      el.textContent = content;
    }
    messagesDiv.appendChild(el);
    scrollToBottom();
  }

  function scrollToBottom() {
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
  }

  function getEditorCode() {
    // Try CodeMirror instance first
    const cmEl = document.querySelector('.CodeMirror');
    if (cmEl && cmEl.CodeMirror) {
      return cmEl.CodeMirror.getValue();
    }
    // Fallback to textarea
    const textarea = document.getElementById('codeEditor');
    return textarea ? textarea.value : '';
  }

  function getLastErrorStatus() {
    // Check if there's a visible error/status in the results section
    const resultEl = document.querySelector('#testResultsSection .status-badge, #submissionResultTabContent .badge');
    if (resultEl) {
      const text = resultEl.textContent.trim().toUpperCase();
      if (['WA', 'RE', 'CE', 'TLE', 'MLE'].includes(text)) return text;
    }
    return '';
  }

  function renderMarkdown(text) {
    // Simple markdown rendering for code blocks and inline code
    let html = escapeHtml(text);

    // Fenced code blocks
    html = html.replace(/```(\w*)\n([\s\S]*?)```/g, function (_, lang, code) {
      return '<pre><code>' + code.trim() + '</code></pre>';
    });

    // Inline code
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');

    // Bold
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');

    // Line breaks
    html = html.replace(/\n/g, '<br>');

    return html;
  }

  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }
})();
