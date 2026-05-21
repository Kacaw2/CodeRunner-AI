/**
 * Agent Trace Viewer - Timeline visualization for agent runs.
 */
(function () {
  'use strict';

  const listEl = document.getElementById('traceList');
  const detailEl = document.getElementById('traceDetail');
  const filterEl = document.getElementById('agentFilter');
  const refreshBtn = document.getElementById('refreshBtn');
  const paginationEl = document.getElementById('tracePagination');

  let currentPage = 0;
  const pageSize = 20;
  let totalTraces = 0;

  // ── Load trace list ───────────────────────────────────────
  function loadTraces(offset) {
    offset = offset || 0;
    const agentType = filterEl.value;
    let url = `/api/v1/ai/traces?limit=${pageSize}&offset=${offset}`;
    if (agentType) url += `&agent_type=${agentType}`;

    fetch(url)
      .then(r => r.json())
      .then(data => {
        totalTraces = data.total || 0;
        renderTraceList(data.traces || []);
        renderPagination(offset);
      })
      .catch(err => {
        listEl.innerHTML = '<p class="text-danger small p-3">Failed to load traces.</p>';
      });
  }

  function renderTraceList(traces) {
    if (!traces.length) {
      listEl.innerHTML = '<p class="text-muted small p-3">No traces found.</p>';
      return;
    }

    listEl.innerHTML = traces.map(t => `
      <div class="trace-item" data-id="${t.id}">
        <div class="trace-item-header">
          <span class="trace-agent-badge ${t.agent_type}">${t.agent_type}</span>
          <span class="trace-status-badge ${t.status}">${t.status}</span>
        </div>
        <div class="trace-item-meta">
          <span><i class="bi bi-clock"></i> ${formatDuration(t.total_latency_ms)}</span>
          <span><i class="bi bi-tools"></i> ${t.tool_call_count || 0} tools</span>
          <span>${formatTime(t.created_at)}</span>
        </div>
      </div>
    `).join('');

    // Click handlers
    listEl.querySelectorAll('.trace-item').forEach(item => {
      item.addEventListener('click', () => {
        listEl.querySelectorAll('.trace-item').forEach(i => i.classList.remove('active'));
        item.classList.add('active');
        loadTraceDetail(item.dataset.id);
      });
    });
  }

  function renderPagination(offset) {
    const totalPages = Math.ceil(totalTraces / pageSize);
    const currentPageNum = Math.floor(offset / pageSize) + 1;

    if (totalPages <= 1) {
      paginationEl.innerHTML = '';
      return;
    }

    paginationEl.innerHTML = `
      <button id="prevPage" ${currentPageNum <= 1 ? 'disabled' : ''}>← Prev</button>
      <span class="page-info">${currentPageNum} / ${totalPages}</span>
      <button id="nextPage" ${currentPageNum >= totalPages ? 'disabled' : ''}>Next →</button>
    `;

    document.getElementById('prevPage')?.addEventListener('click', () => {
      loadTraces(Math.max(0, offset - pageSize));
    });
    document.getElementById('nextPage')?.addEventListener('click', () => {
      loadTraces(offset + pageSize);
    });
  }

  // ── Load trace detail ─────────────────────────────────────
  function loadTraceDetail(runId) {
    fetch(`/api/v1/ai/traces/${runId}`)
      .then(r => r.json())
      .then(data => renderTraceDetail(data))
      .catch(err => {
        detailEl.innerHTML = '<p class="text-danger p-3">Failed to load trace detail.</p>';
      });
  }

  function renderTraceDetail(data) {
    const run = data.run;
    const steps = data.steps || run.tool_calls_json || [];

    let timelineHtml = '';
    let cumulativeMs = 0;

    steps.forEach((step, i) => {
      const isLlm = step.step_type === 'llm_call';
      const isTool = step.step_type === 'tool_call';
      const iconClass = isLlm ? 'llm' : (step.tool_success === false ? 'tool failed' : 'tool');
      const icon = isLlm ? '<i class="bi bi-cpu"></i>' : '<i class="bi bi-wrench"></i>';
      const title = isLlm ? `LLM Call #${steps.filter((s, j) => j <= i && s.step_type === 'llm_call').length}`
        : `Tool: ${step.tool_name || 'unknown'}`;

      let detail = '';
      if (isTool && step.tool_input) {
        const inputStr = typeof step.tool_input === 'string' ? step.tool_input : JSON.stringify(step.tool_input, null, 2);
        detail = `<pre>${escapeHtml(inputStr.substring(0, 300))}</pre>`;
      }
      if (step.tool_output_preview) {
        detail += `<div style="margin-top:4px;color:#059669;">Output: ${escapeHtml(step.tool_output_preview.substring(0, 200))}</div>`;
      }
      if (step.error) {
        detail += `<div class="error-text">Error: ${escapeHtml(step.error.substring(0, 200))}</div>`;
      }
      if (step.tool_success === false && !step.error) {
        detail += `<div class="error-text">Tool call failed</div>`;
      }

      timelineHtml += `
        <div class="timeline-step">
          <div class="timeline-icon ${iconClass}">${icon}</div>
          <div class="timeline-body">
            <div class="timeline-body-header">
              <span class="timeline-step-title">${title}</span>
              <span class="timeline-step-time">${formatDuration(step.latency_ms)} @ ${formatDuration(cumulativeMs)}</span>
            </div>
            <div class="timeline-step-detail">${detail}</div>
          </div>
        </div>
      `;
      cumulativeMs += (step.latency_ms || 0);
    });

    detailEl.innerHTML = `
      <div class="trace-detail-header">
        <div class="trace-detail-title">
          <span class="trace-agent-badge ${run.agent_type}" style="font-size:0.8rem;padding:3px 10px;">${run.agent_type}</span>
          Agent Run <code>${run.id.substring(0, 8)}...</code>
          <span class="trace-status-badge ${run.status}" style="margin-left:8px;">${run.status}</span>
        </div>
        <div class="trace-detail-stats">
          <div class="trace-stat">
            <div class="trace-stat-label">Total Duration</div>
            <div class="trace-stat-value">${formatDuration(run.total_latency_ms)}</div>
          </div>
          <div class="trace-stat">
            <div class="trace-stat-label">LLM Time</div>
            <div class="trace-stat-value">${formatDuration(run.llm_latency_ms)}</div>
          </div>
          <div class="trace-stat">
            <div class="trace-stat-label">Tool Time</div>
            <div class="trace-stat-value">${formatDuration(run.tool_latency_ms)}</div>
          </div>
          <div class="trace-stat">
            <div class="trace-stat-label">Tool Calls</div>
            <div class="trace-stat-value">${run.tool_call_count || 0}</div>
          </div>
          <div class="trace-stat">
            <div class="trace-stat-label">Tokens (in/out)</div>
            <div class="trace-stat-value">${run.tokens_input || '-'} / ${run.tokens_output || '-'}</div>
          </div>
        </div>
      </div>

      <div class="trace-timeline">
        <h5><i class="bi bi-clock-history"></i> Execution Timeline</h5>
        ${timelineHtml || '<p class="text-muted small">No steps recorded.</p>'}
      </div>

      ${run.error_message ? `
        <div style="margin-top:20px;padding:12px 16px;background:#fef2f2;border-radius:10px;border:1px solid #fecaca;">
          <strong style="color:#991b1b;">Error:</strong>
          <span style="color:#7f1d1d;">${escapeHtml(run.error_message)}</span>
        </div>
      ` : ''}

      <div class="trace-io">
        <div class="trace-io-box">
          <h6>Input</h6>
          <pre>${escapeHtml((run.input_message || 'N/A').substring(0, 500))}</pre>
        </div>
        <div class="trace-io-box">
          <h6>Output</h6>
          <pre>${escapeHtml((run.output_response || 'N/A').substring(0, 500))}</pre>
        </div>
      </div>
    `;
  }

  // ── Helpers ───────────────────────────────────────────────

  function formatDuration(ms) {
    if (ms == null) return '-';
    if (ms < 1000) return ms + 'ms';
    return (ms / 1000).toFixed(1) + 's';
  }

  function formatTime(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    const now = new Date();
    const diffMs = now - d;
    if (diffMs < 60000) return 'just now';
    if (diffMs < 3600000) return Math.floor(diffMs / 60000) + 'm ago';
    if (diffMs < 86400000) return Math.floor(diffMs / 3600000) + 'h ago';
    return d.toLocaleDateString();
  }

  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text || '';
    return div.innerHTML;
  }

  // ── Event listeners ───────────────────────────────────────
  filterEl.addEventListener('change', () => loadTraces(0));
  refreshBtn.addEventListener('click', () => loadTraces(0));

  // Initial load
  loadTraces(0);
})();
