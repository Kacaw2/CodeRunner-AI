(function () {
  const CTX = window.__AI_CONTEXT || {};
  const API_CHAT_STREAM = "/api/v1/ai/chat/stream";
  const API_CONVERSATIONS = "/api/v1/ai/conversations";

  function authHeaders() {
    const h = { "Content-Type": "application/json" };
    const t = localStorage.getItem("token");
    if (t) h.Authorization = "Bearer " + t;
    return h;
  }

  // DOM
  const chatMessages = document.getElementById("chatMessages");
  const chatInput = document.getElementById("chatInput");
  const sendBtn = document.getElementById("sendBtn");
  const newChatBtn = document.getElementById("newChatBtn");
  const conversationList = document.getElementById("conversationList");
  const chatTitle = document.getElementById("chatTitle");
  const toggleSidebar = document.getElementById("toggleSidebar");
  const chatSidebar = document.getElementById("chatSidebar");
  const agentSelect = document.getElementById("agentType");
  const convFilter = document.getElementById("convFilter");

  const welcomePanels = {
    tutor: document.getElementById("welcomeTutor"),
    reviewer: document.getElementById("welcomeReviewer"),
    analytics: document.getElementById("welcomeAnalytics"),
  };

  const agentLabels = {
    tutor: "AI Tutor",
    reviewer: "Code Review",
    generator: "AI Generator",
    analytics: "Learning Analytics",
  };

  const placeholders = {
    tutor: "Ask me about your code...",
    reviewer: "Paste code or ask for a review...",
    analytics: "Ask about your learning progress...",
  };

  let conversationId = CTX.conversationId || null;
  let currentAgent = CTX.agentType || "tutor";
  let isSending = false;

  // Init agent selector
  if (agentSelect) {
    agentSelect.value = currentAgent;
    agentSelect.addEventListener("change", () => {
      currentAgent = agentSelect.value;
      updateAgentUI();
      if (!conversationId) showWelcome();
    });
  }

  function updateAgentUI() {
    chatTitle.textContent = agentLabels[currentAgent] || "AI Assistant";
    chatInput.placeholder = placeholders[currentAgent] || "Type a message...";
  }

  function showWelcome() {
    // Clear messages area and show appropriate welcome
    const msgs = chatMessages.querySelectorAll(".msg");
    msgs.forEach((m) => m.remove());
    Object.entries(welcomePanels).forEach(([key, el]) => {
      if (el) el.style.display = key === currentAgent ? "" : "none";
    });
  }

  function hideAllWelcomes() {
    Object.values(welcomePanels).forEach((el) => {
      if (el) el.style.display = "none";
    });
  }

  // Sidebar toggle
  if (toggleSidebar) {
    toggleSidebar.addEventListener("click", () => {
      chatSidebar.classList.toggle("open");
    });
  }

  // Auto-resize textarea
  chatInput.addEventListener("input", () => {
    chatInput.style.height = "auto";
    chatInput.style.height = Math.min(chatInput.scrollHeight, 120) + "px";
  });

  // Send on Enter
  chatInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  sendBtn.addEventListener("click", sendMessage);

  // Quick prompts
  document.querySelectorAll(".quick-prompt").forEach((btn) => {
    btn.addEventListener("click", () => {
      chatInput.value = btn.dataset.prompt;
      sendMessage();
    });
  });

  // New chat
  newChatBtn.addEventListener("click", () => {
    conversationId = null;
    showWelcome();
    document.querySelectorAll(".conv-item.active").forEach((el) => el.classList.remove("active"));
  });

  // Conversation filter
  if (convFilter) {
    convFilter.addEventListener("change", () => loadConversations());
  }

  // ── Load conversations ──
  async function loadConversations() {
    try {
      let url = API_CONVERSATIONS + "?limit=50";
      const filterVal = convFilter ? convFilter.value : "";
      if (filterVal) url += "&agent_type=" + filterVal;

      const res = await fetch(url, { headers: authHeaders() });
      const data = await res.json();
      conversationList.innerHTML = "";
      if (!data.items || data.items.length === 0) {
        conversationList.innerHTML = '<p class="text-muted small px-3">No conversations yet</p>';
        return;
      }
      data.items.forEach((c) => {
        const div = document.createElement("div");
        div.className = "conv-item-wrapper";

        const btn = document.createElement("button");
        btn.className = "conv-item" + (c.id === conversationId ? " active" : "");

        const typeIcon = {
          tutor: "bi-lightbulb",
          reviewer: "bi-code-slash",
          generator: "bi-magic",
          analytics: "bi-graph-up",
        }[c.agent_type] || "bi-chat";

        btn.innerHTML =
          '<div class="conv-title"><i class="bi ' + typeIcon + ' me-1"></i>' +
          escapeHtml(c.title || "Untitled") + "</div>" +
          '<div class="conv-meta">' + (c.agent_type || "") + " · " + formatDate(c.updated_at) + "</div>";
        btn.addEventListener("click", () => loadConversation(c.id, c.agent_type));

        const delBtn = document.createElement("button");
        delBtn.className = "conv-delete-btn";
        delBtn.title = "Delete";
        delBtn.innerHTML = '<i class="bi bi-trash3"></i>';
        delBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          deleteConversation(c.id, div);
        });

        div.appendChild(btn);
        div.appendChild(delBtn);
        conversationList.appendChild(div);
      });
    } catch (_) {
      conversationList.innerHTML = '<p class="text-muted small px-3">Failed to load</p>';
    }
  }

  async function loadConversation(id, agentType) {
    try {
      const res = await fetch(API_CONVERSATIONS + "/" + id, { headers: authHeaders() });
      const data = await res.json();
      conversationId = id;
      hideAllWelcomes();

      // Switch agent type to match conversation
      if (agentType && agentSelect) {
        currentAgent = agentType;
        agentSelect.value = agentType;
        updateAgentUI();
      }

      chatTitle.textContent = data.title || agentLabels[currentAgent] || "AI Assistant";

      // Clear existing messages (keep welcome panels hidden)
      const msgs = chatMessages.querySelectorAll(".msg");
      msgs.forEach((m) => m.remove());

      data.messages.forEach((m) => {
        appendMessage(m.role, m.content);
      });
      scrollToBottom();

      // Highlight active conversation
      document.querySelectorAll(".conv-item").forEach((el) => el.classList.remove("active"));
      document.querySelectorAll(".conv-item-wrapper").forEach((wrapper) => {
        const btn = wrapper.querySelector(".conv-item");
        if (btn && btn.querySelector(".conv-title")?.textContent.includes(data.title)) {
          btn.classList.add("active");
        }
      });
    } catch (_) { /* ignore */ }
  }

  async function deleteConversation(id, wrapperEl) {
    if (!confirm("Delete this conversation?")) return;
    try {
      await fetch(API_CONVERSATIONS + "/" + id, {
        method: "DELETE",
        headers: authHeaders(),
      });
      if (wrapperEl) wrapperEl.remove();
      if (conversationId === id) {
        conversationId = null;
        showWelcome();
      }
    } catch (_) { /* ignore */ }
  }

  // ── Send message ──
  async function sendMessage() {
    const text = chatInput.value.trim();
    if (!text || isSending) return;

    isSending = true;
    sendBtn.disabled = true;
    chatInput.value = "";
    chatInput.style.height = "auto";

    hideAllWelcomes();

    appendMessage("user", text);
    const assistantEl = appendMessage("assistant", "");
    const bodyEl = assistantEl.querySelector(".msg-body");
    bodyEl.innerHTML = '<div class="typing-indicator"><span></span><span></span><span></span></div>';
    scrollToBottom();

    const payload = {
      message: text,
      agent_type: currentAgent,
      conversation_id: conversationId,
      question_id: CTX.questionId,
      submission_id: CTX.submissionId,
    };

    try {
      const response = await fetch(API_CHAT_STREAM, {
        method: "POST",
        headers: authHeaders(),
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        throw new Error(err.message || "Request failed");
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let fullText = "";

      bodyEl.innerHTML = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop();

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const raw = line.slice(6).trim();
          if (raw === "[DONE]") continue;

          let event;
          try {
            event = JSON.parse(raw);
          } catch (_) {
            continue;
          }

          if (event.type === "start") {
            conversationId = event.conversation_id;
          } else if (event.type === "token") {
            fullText += event.content;
            bodyEl.innerHTML = renderMarkdown(fullText);
            scrollToBottom();
          } else if (event.type === "tool_call") {
            const indicator = document.createElement("div");
            indicator.className = "tool-indicator";
            indicator.innerHTML = '<i class="bi bi-gear-fill"></i> Calling ' + escapeHtml(event.tool) + "...";
            bodyEl.appendChild(indicator);
            scrollToBottom();
          } else if (event.type === "tool_result") {
            const indicators = bodyEl.querySelectorAll(".tool-indicator");
            if (indicators.length > 0) {
              const last = indicators[indicators.length - 1];
              last.innerHTML = '<i class="bi bi-check-circle"></i> ' + escapeHtml(event.summary || event.tool);
              last.querySelector("i").style.animation = "none";
            }
          } else if (event.type === "done") {
            // done
          } else if (event.type === "error") {
            bodyEl.textContent = "Error: " + (event.message || "Unknown error");
          }
        }
      }

      if (!fullText && bodyEl.textContent === "") {
        bodyEl.textContent = "(No response)";
      }

      // Re-render final markdown to clean up any tool indicators mixed in
      if (fullText) {
        bodyEl.innerHTML = renderMarkdown(fullText);
      }

      loadConversations();
    } catch (err) {
      bodyEl.textContent = "Error: " + err.message;
    } finally {
      isSending = false;
      sendBtn.disabled = false;
      chatInput.focus();
    }
  }

  // ── Markdown helper ──
  function renderMarkdown(text) {
    if (typeof marked !== "undefined" && typeof DOMPurify !== "undefined") {
      return DOMPurify.sanitize(marked.parse(text || ""));
    }
    return escapeHtml(text);
  }

  // ── Helpers ──
  function appendMessage(role, content) {
    const div = document.createElement("div");
    div.className = "msg msg-" + role;
    const avatarIcon = role === "user" ? "bi-person-fill" : "bi-robot";
    const rendered = role === "assistant" ? renderMarkdown(content) : escapeHtml(content);
    div.innerHTML =
      '<div class="msg-avatar"><i class="bi ' + avatarIcon + '"></i></div>' +
      '<div class="msg-body">' + rendered + "</div>";
    chatMessages.appendChild(div);
    return div;
  }

  function scrollToBottom() {
    chatMessages.scrollTop = chatMessages.scrollHeight;
  }

  function escapeHtml(s) {
    const d = document.createElement("div");
    d.textContent = s || "";
    return d.innerHTML;
  }

  function formatDate(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    const now = new Date();
    if (d.toDateString() === now.toDateString()) {
      return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    }
    return d.toLocaleDateString([], { month: "short", day: "numeric" });
  }

  // ── Init ──
  updateAgentUI();
  loadConversations();
  if (conversationId) {
    loadConversation(conversationId);
  }
  chatInput.focus();
})();
