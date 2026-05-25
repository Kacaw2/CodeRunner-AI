(function () {
  const CTX = window.__AI_CONTEXT || {};
  const API_CHAT_ASYNC = "/api/v1/ai/chat/async";
  const API_CHAT_TASK = "/api/v1/ai/chat/task";
  const API_CHAT_STREAM = "/api/v1/ai/chat/stream";  // legacy fallback
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
  const agentBadge = document.getElementById("agentBadge");
  const convFilter = document.getElementById("convFilter");
  const welcomeGeneral = document.getElementById("welcomeGeneral");

  const agentLabels = {
    tutor: "AI Tutor",
    reviewer: "Code Review",
    generator: "AI Generator",
    analytics: "Learning Analytics",
    auto: "AI Assistant",
  };

  const agentBadgeColors = {
    tutor: "bg-primary",
    reviewer: "bg-info",
    generator: "bg-success",
    analytics: "bg-warning text-dark",
    auto: "bg-secondary",
  };

  let conversationId = CTX.conversationId || null;
  let currentAgent = "auto";
  let isSending = false;

  function updateAgentBadge(agentType) {
    if (!agentBadge) return;
    const label = agentLabels[agentType] || agentType || "Auto";
    const colorClass = agentBadgeColors[agentType] || "bg-secondary";
    agentBadge.className = "badge " + colorClass;
    if (agentType === "auto") {
      agentBadge.innerHTML = '<i class="bi bi-arrow-repeat"></i> Auto';
    } else {
      agentBadge.textContent = label;
    }
  }

  function updateAgentUI() {
    chatTitle.textContent = agentLabels[currentAgent] || "AI Assistant";
    chatInput.placeholder = "Type a message...";
  }

  function showWelcome() {
    const msgs = chatMessages.querySelectorAll(".msg");
    msgs.forEach((m) => m.remove());
    if (welcomeGeneral) welcomeGeneral.style.display = "";
    currentAgent = "auto";
    updateAgentBadge("auto");
  }

  function hideAllWelcomes() {
    if (welcomeGeneral) welcomeGeneral.style.display = "none";
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
    updateAgentUI();
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

      // Show the conversation's agent type in the badge
      if (agentType) {
        currentAgent = agentType;
        updateAgentBadge(agentType);
        updateAgentUI();
      }

      chatTitle.textContent = data.title || agentLabels[currentAgent] || "AI Assistant";

      // Clear existing messages (keep welcome panels hidden)
      const msgs = chatMessages.querySelectorAll(".msg");
      msgs.forEach((m) => m.remove());

      data.messages.forEach((m) => {
        appendMessage(m.role, m.content);
      });
      scrollToBottom(true);

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

  // ── Send message (async task model) ──
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
    bodyEl.innerHTML = '<div class="thinking-label"><span class="thinking-dot"></span> Thinking...</div>';
    userScrolledUp = false;
    scrollToBottom(true);

    // SSE events container
    const sseContainer = document.createElement("div");
    sseContainer.className = "sse-events-container";
    sseContainer.style.display = "none";
    const sseToggle = document.createElement("button");
    sseToggle.className = "sse-events-toggle";
    sseToggle.innerHTML = '<span class="toggle-icon"><i class="bi bi-chevron-right"></i></span> <span>Process details</span> <span class="sse-count"></span>';
    sseToggle.addEventListener("click", function () {
      sseToggle.classList.toggle("expanded");
      sseListEl.classList.toggle("show");
    });
    const sseListEl = document.createElement("div");
    sseListEl.className = "sse-events-list";
    sseContainer.appendChild(sseToggle);
    sseContainer.appendChild(sseListEl);
    let sseEventCount = 0;

    function addSseEvent(type, text) {
      sseEventCount++;
      const item = document.createElement("div");
      item.className = "sse-event-item " + type;
      item.textContent = text;
      sseListEl.appendChild(item);
      sseContainer.style.display = "";
      sseToggle.querySelector(".sse-count").textContent = "(" + sseEventCount + ")";
      if (!sseContainer.parentNode) bodyEl.appendChild(sseContainer);
      scrollToBottom();
    }

    const payload = {
      message: text,
      agent_type: "auto",
      conversation_id: conversationId,
      question_id: CTX.questionId,
      submission_id: CTX.submissionId,
    };

    try {
      // Step 1: Create async task
      const createRes = await fetch(API_CHAT_ASYNC, {
        method: "POST",
        headers: authHeaders(),
        body: JSON.stringify(payload),
      });

      if (!createRes.ok) {
        const err = await createRes.json().catch(() => ({}));
        throw new Error(err.message || "Request failed");
      }

      const { task_id, conversation_id: newConvId } = await createRes.json();
      if (newConvId) conversationId = newConvId;

      // Step 2: Subscribe to SSE stream for this task
      await _subscribeToTaskStream(task_id, bodyEl, sseContainer, sseListEl, addSseEvent, sseEventCount);

      loadConversations();
    } catch (err) {
      bodyEl.textContent = "Error: " + err.message;
    } finally {
      isSending = false;
      sendBtn.disabled = false;
      chatInput.focus();
    }
  }

  // ── Task SSE subscription with reconnect ──
  async function _subscribeToTaskStream(taskId, bodyEl, sseContainer, sseListEl, addSseEvent, initialSseCount) {
    let sseEventCount = initialSseCount;
    let lastEventIndex = 0;
    let fullText = "";
    let retries = 0;
    const maxRetries = 3;

    async function connectStream() {
      const streamUrl = API_CHAT_TASK + "/" + taskId + "/stream?last_event=" + lastEventIndex;
      const response = await fetch(streamUrl, { headers: authHeaders() });

      if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        throw new Error(err.message || "Stream failed");
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      if (lastEventIndex === 0) {
        bodyEl.innerHTML = "";
      }

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop();

        for (const line of lines) {
          if (line.startsWith(":")) continue;  // heartbeat
          if (!line.startsWith("data: ")) continue;
          const raw = line.slice(6).trim();
          if (raw === "[DONE]") continue;

          let event;
          try {
            event = JSON.parse(raw);
          } catch (_) {
            continue;
          }

          lastEventIndex++;
          retries = 0;  // Reset retry count on successful event

          if (event.type === "start") {
            if (event.conversation_id) conversationId = event.conversation_id;
            if (event.agent_type) {
              currentAgent = event.agent_type;
              updateAgentBadge(event.agent_type);
              updateAgentUI();
            }
            addSseEvent("start", "Routed to " + (agentLabels[event.agent_type] || event.agent_type || "agent"));
          } else if (event.type === "token") {
            const thinkingEl = bodyEl.querySelector(".thinking-label");
            if (thinkingEl) thinkingEl.remove();
            fullText += event.content;
            bodyEl.innerHTML = renderMarkdown(fullText);
            if (sseContainer.parentNode !== bodyEl && sseEventCount > 0) {
              sseContainer.style.display = "";
              bodyEl.appendChild(sseContainer);
            }
            scrollToBottom();
          } else if (event.type === "replace") {
            fullText = event.content;
            bodyEl.innerHTML = renderMarkdown(fullText);
            if (sseContainer.parentNode !== bodyEl && sseEventCount > 0) {
              sseContainer.style.display = "";
              bodyEl.appendChild(sseContainer);
            }
            scrollToBottom();
          } else if (event.type === "handoff" || event.type === "handoff_start") {
            const target = event.target || "";
            const reason = event.reason || "";
            if (target) {
              currentAgent = target;
              updateAgentBadge(target);
              updateAgentUI();
            }
            addSseEvent("handoff", "Handing off to " + (agentLabels[target] || target) + (reason ? ": " + reason : ""));
            if (event.type === "handoff_start") {
              fullText += "\n\n---\n\n";
              bodyEl.innerHTML = renderMarkdown(fullText);
              if (sseContainer.parentNode !== bodyEl && sseEventCount > 0) {
                sseContainer.style.display = "";
                bodyEl.appendChild(sseContainer);
              }
            }
          } else if (event.type === "tool_call") {
            const thinkingEl = bodyEl.querySelector(".thinking-label");
            if (thinkingEl) thinkingEl.innerHTML = '<span class="thinking-dot"></span> Working...';
            addSseEvent("tool-call", "Calling: " + (event.tool || ""));
          } else if (event.type === "tool_result") {
            addSseEvent("tool-result", "Done: " + (event.summary || event.tool || ""));
          } else if (event.type === "done") {
            if (currentAgent === "generator" && fullText) {
              const genData = tryParseGeneratorJson(fullText);
              if (genData) {
                bodyEl.innerHTML = "";
                bodyEl.appendChild(renderGeneratorCard(genData, event.draft_id || null));
                if (sseEventCount > 0) bodyEl.appendChild(sseContainer);
                scrollToBottom();
              }
            }
            if (event.draft_id && currentAgent !== "generator") {
              const banner = document.createElement("div");
              banner.className = "draft-saved-banner";
              banner.innerHTML =
                '<i class="bi bi-check-circle-fill"></i> ' +
                'Draft saved ' +
                (event.draft_status === "passed" ? '<span class="badge bg-success">Verified</span>' : '<span class="badge bg-warning text-dark">Unverified</span>') +
                ' — <a href="/ai/review-queue">Go to Review Queue</a>';
              bodyEl.appendChild(banner);
              scrollToBottom();
            }
            return;  // Task complete
          } else if (event.type === "error") {
            const thinkingEl = bodyEl.querySelector(".thinking-label");
            if (thinkingEl) thinkingEl.remove();
            addSseEvent("error", event.message || "Unknown error");
            bodyEl.textContent = "Error: " + (event.message || "Unknown error");
            if (sseEventCount > 0) bodyEl.appendChild(sseContainer);
            return;  // Task failed
          }
        }
      }
    }

    // Connect with retry logic
    while (retries <= maxRetries) {
      try {
        await connectStream();
        break;  // Clean exit (done or error event received)
      } catch (err) {
        retries++;
        if (retries > maxRetries) {
          // Fall back to polling for final result
          try {
            const pollRes = await fetch(API_CHAT_TASK + "/" + taskId, { headers: authHeaders() });
            if (pollRes.ok) {
              const pollData = await pollRes.json();
              if (pollData.task && pollData.task.status === "completed" && pollData.task.response) {
                fullText = pollData.task.response;
              }
            }
          } catch (_) { /* ignore */ }

          if (!fullText) {
            bodyEl.textContent = "Connection lost. Please try again.";
            return;
          }
        } else {
          // Wait before retry with exponential backoff
          await new Promise((resolve) => setTimeout(resolve, 1000 * retries));
        }
      }
    }

    // Final render
    if (!fullText && bodyEl.textContent === "") {
      bodyEl.textContent = "(No response)";
    }

    if (fullText) {
      if (currentAgent === "generator") {
        const genData = tryParseGeneratorJson(fullText);
        if (genData) {
          bodyEl.innerHTML = "";
          bodyEl.appendChild(renderGeneratorCard(genData, null));
        } else {
          bodyEl.innerHTML = renderMarkdown(fullText);
        }
      } else {
        bodyEl.innerHTML = renderMarkdown(fullText);
      }
      if (sseEventCount > 0) {
        bodyEl.appendChild(sseContainer);
      }
    }
  }

  // ── Markdown helper ──
  function renderMarkdown(text) {
    if (typeof marked !== "undefined" && typeof DOMPurify !== "undefined") {
      return DOMPurify.sanitize(marked.parse(text || ""));
    }
    return escapeHtml(text);
  }

  // ── Generator problem card ──
  function tryParseGeneratorJson(text) {
    // Try to extract JSON from ```json fences or raw { ... }
    let jsonStr = text;
    const fenceMatch = text.match(/```json\s*\n?([\s\S]*?)```/);
    if (fenceMatch) jsonStr = fenceMatch[1];
    const braceMatch = jsonStr.match(/\{[\s\S]*\}/);
    if (!braceMatch) return null;
    try {
      const obj = JSON.parse(braceMatch[0]);
      // Check if it's a generator output (has question wrapper or direct problem fields)
      const data = obj.question || obj;
      if (data.title && data.test_cases) return data;
      return null;
    } catch (_) { return null; }
  }

  function renderGeneratorCard(data, draftId) {
    const diff = (data.difficulty || "").toLowerCase();
    const visibleCases = (data.test_cases || []).filter(tc => !tc.is_hidden).slice(0, 3);
    const lang = data.programming_language || "python";

    let casesHtml = "";
    visibleCases.forEach((tc, i) => {
      casesHtml +=
        '<div class="gen-tc-item">' +
        '<span class="gen-tc-label">Input:</span><span>' + escapeHtml(tc.input || "") + '</span>' +
        '<span class="gen-tc-label">Expected:</span><span>' + escapeHtml(tc.expected_output || "") + '</span>' +
        '</div>';
    });

    const descPreview = (data.description || "").substring(0, 400) + ((data.description || "").length > 400 ? "..." : "");

    const card = document.createElement("div");
    card.className = "gen-problem-card";
    card.innerHTML =
      '<div class="gen-problem-header">' +
        '<span class="gen-title">' + escapeHtml(data.title || "Untitled") + '</span>' +
        '<span class="gen-diff ' + diff + '">' + escapeHtml(diff || "-") + ' · ' + escapeHtml(lang.toUpperCase()) + '</span>' +
      '</div>' +
      '<div class="gen-problem-desc">' + escapeHtml(descPreview) + '</div>' +
      (casesHtml ? '<div class="gen-test-cases"><h6>Sample Test Cases</h6>' + casesHtml + '</div>' : '') +
      '<div class="gen-problem-actions">' +
        (draftId
          ? '<button class="gen-save-btn" disabled><i class="bi bi-check-circle"></i> Draft Saved</button>'
          : '<button class="gen-save-btn" data-action="save"><i class="bi bi-floppy"></i> Save as Draft</button>'
        ) +
        '<button data-action="toggle-json"><i class="bi bi-code-slash"></i> View JSON</button>' +
      '</div>';

    // Toggle raw JSON view
    card.querySelector('[data-action="toggle-json"]').addEventListener("click", function () {
      let jsonPanel = card.querySelector(".gen-json-raw");
      if (jsonPanel) {
        jsonPanel.remove();
        this.innerHTML = '<i class="bi bi-code-slash"></i> View JSON';
      } else {
        jsonPanel = document.createElement("pre");
        jsonPanel.className = "gen-json-raw";
        jsonPanel.style.cssText = "padding:12px 16px;font-size:0.78rem;background:#f8fafc;max-height:300px;overflow:auto;margin:0;border-top:1px solid #e2e8f0;";
        jsonPanel.textContent = JSON.stringify(data, null, 2);
        card.appendChild(jsonPanel);
        this.innerHTML = '<i class="bi bi-code-slash"></i> Hide JSON';
      }
    });

    // Save draft action
    const saveBtn = card.querySelector('[data-action="save"]');
    if (saveBtn) {
      saveBtn.addEventListener("click", async function () {
        saveBtn.disabled = true;
        saveBtn.innerHTML = '<i class="bi bi-hourglass-split"></i> Saving...';
        try {
          const res = await fetch("/api/v1/ai/generate/to-draft", {
            method: "POST",
            headers: authHeaders(),
            body: JSON.stringify({ question_data: data, conversation_id: conversationId }),
          });
          if (res.ok) {
            saveBtn.innerHTML = '<i class="bi bi-check-circle"></i> Draft Saved';
            saveBtn.className = "gen-save-btn";
          } else {
            saveBtn.innerHTML = '<i class="bi bi-x-circle"></i> Failed';
            saveBtn.disabled = false;
          }
        } catch (_) {
          saveBtn.innerHTML = '<i class="bi bi-x-circle"></i> Failed';
          saveBtn.disabled = false;
        }
      });
    }

    return card;
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

  let userScrolledUp = false;

  // Track if user has manually scrolled up during streaming
  if (chatMessages) {
    chatMessages.addEventListener("scroll", function () {
      const threshold = 60;
      const atBottom = chatMessages.scrollHeight - chatMessages.scrollTop - chatMessages.clientHeight < threshold;
      userScrolledUp = !atBottom;
    });
  }

  function scrollToBottom(force) {
    if (force || !userScrolledUp) {
      chatMessages.scrollTop = chatMessages.scrollHeight;
    }
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
