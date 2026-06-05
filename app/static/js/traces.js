/**
 * Agent Trace Viewer - complete trace tree (run / spans / events / artifacts /
 * links) with tabbed detail. Reads the new agent_trace_* API shape.
 */
(function () {
  'use strict';

  const listEl = document.getElementById('traceList');
  const detailEl = document.getElementById('traceDetail');
  const filterEl = document.getElementById('agentFilter');
  const statusEl = document.getElementById('statusFilter');
  const searchEl = document.getElementById('searchInput');
  const refreshBtn = document.getElementById('refreshBtn');
  const paginationEl = document.getElementById('tracePagination');

  const pageSize = 20;
  let totalTraces = 0;
  let activeTab = 'timeline';
  let currentDetail = null;

  // ── Load trace list ───────────────────────────────────────
  function loadTraces(offset) {
    offset = offset || 0;
    const params = new URLSearchParams({ limit: pageSize, offset: offset });
    if (filterEl && filterEl.value) params.set('agent_type', filterEl.value);
    if (statusEl && statusEl.value) params.set('status', statusEl.value);
    if (searchEl && searchEl.value.trim()) params.set('q', searchEl.value.trim());

    fetch(`/api/v1/ai/traces?${params.toString()}`)
      .then(r => r.json())
      .then(data => {
        totalTraces = data.total || 0;
        renderTraceList(data.traces || []);
        renderPagination(offset);
      })
      .catch(() => {
        listEl.innerHTML = '<p class="text-danger small p-3">Failed to load traces.</p>';
      });
  }

  function renderTraceList(traces) {
    if (!traces.length) {
      listEl.innerHTML = '<p class="text-muted small p-3">No traces found.</p>';
      return;
    }

    listEl.innerHTML = traces.map(t => `
      <div class="trace-item" data-id="${escapeHtml(t.trace_id || t.id)}">
        <div class="trace-item-header">
          <span class="trace-agent-badge ${t.agent_type || ''}">${t.agent_type || 'unknown'}</span>
          <span class="trace-status-badge ${t.status}">${t.status}</span>
        </div>
        <div class="trace-item-meta">
          <span><i class="bi bi-clock"></i> ${formatDuration(t.total_latency_ms)}</span>
          <span><i class="bi bi-tools"></i> ${t.tool_call_count || 0} tools</span>
          <span><i class="bi bi-cash-coin"></i> ${formatCost(t.cost_cny)}</span>
        </div>
        <div class="trace-item-meta">
          <span class="trace-source">${t.source || 'agent'}</span>
          <span>${formatTime(t.created_at)}</span>
        </div>
      </div>
    `).join('');

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
      <button id="prevPage" ${currentPageNum <= 1 ? 'disabled' : ''}>&larr; Prev</button>
      <span class="page-info">${currentPageNum} / ${totalPages}</span>
      <button id="nextPage" ${currentPageNum >= totalPages ? 'disabled' : ''}>Next &rarr;</button>
    `;

    const prev = document.getElementById('prevPage');
    const next = document.getElementById('nextPage');
    if (prev) prev.addEventListener('click', () => loadTraces(Math.max(0, offset - pageSize)));
    if (next) next.addEventListener('click', () => loadTraces(offset + pageSize));
  }

  // ── Load trace detail ─────────────────────────────────────
  function loadTraceDetail(traceId) {
    fetch(`/api/v1/ai/traces/${encodeURIComponent(traceId)}`)
      .then(r => r.json())
      .then(data => {
        currentDetail = data;
        activeTab = 'timeline';
        renderTraceDetail();
      })
      .catch(() => {
        detailEl.innerHTML = '<p class="text-danger p-3">Failed to load trace detail.</p>';
      });
  }

  function renderTraceDetail() {
    const data = currentDetail;
    if (!data || !data.run) return;
    const run = data.run;
    const spans = data.spans || [];
    const isEval = run.eval_run_id != null || run.eval_case_id != null;

    const tabs = [
      ['timeline', 'Timeline'],
      ['messages', 'Messages'],
      ['tools', 'Tools / MCP'],
      ['artifacts', `Artifacts (${(data.artifacts || []).length})`],
      ['cost', 'Cost'],
      ['eval', 'Eval'],
    ];

    detailEl.innerHTML = `
      <div class="trace-detail-header">
        <div class="trace-detail-title">
          <span class="trace-agent-badge ${run.agent_type || ''}" style="font-size:0.8rem;padding:3px 10px;">${run.agent_type || 'unknown'}</span>
          Trace <code>${escapeHtml((run.trace_id || '').substring(0, 8))}…</code>
          <span class="trace-status-badge ${run.status}" style="margin-left:8px;">${run.status}</span>
          ${run.legacy ? '<span class="trace-status-badge" style="margin-left:6px;background:#e5e7eb;color:#374151;">legacy</span>' : ''}
          ${isEval ? '<span class="trace-status-badge" style="margin-left:6px;background:#ede9fe;color:#5b21b6;">eval</span>' : ''}
        </div>
        <div class="trace-detail-stats">
          ${stat('Total', formatDuration(run.total_latency_ms))}
          ${stat('LLM', formatDuration(run.llm_latency_ms))}
          ${stat('Tool', formatDuration(run.tool_latency_ms))}
          ${stat('Cost', formatCost(run.cost_cny))}
          ${stat('Tokens (in/out)', `${run.tokens_input || 0} / ${run.tokens_output || 0}`)}
        </div>
      </div>

      <div class="trace-tabs" id="traceTabs">
        ${tabs.map(([key, label]) =>
          `<button class="trace-tab ${key === activeTab ? 'active' : ''}" data-tab="${key}">${label}</button>`
        ).join('')}
      </div>

      <div class="trace-tab-body" id="traceTabBody">${renderTab(activeTab, data)}</div>
    `;

    detailEl.querySelectorAll('.trace-tab').forEach(btn => {
      btn.addEventListener('click', () => {
        activeTab = btn.dataset.tab;
        detailEl.querySelectorAll('.trace-tab').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        document.getElementById('traceTabBody').innerHTML = renderTab(activeTab, currentDetail);
      });
    });
  }

  function renderTab(tab, data) {
    const run = data.run;
    const spans = data.spans || [];

    if (tab === 'timeline') return renderTimeline(spans, run);
    if (tab === 'messages') return renderMessages(run);
    if (tab === 'tools') return renderSpanTable(spans.filter(isMcpOrToolSpan), 'No tool/MCP spans.');
    if (tab === 'artifacts') return renderArtifacts(data.artifacts || []);
    if (tab === 'cost') return renderCost(run);
    if (tab === 'eval') return renderEval(run, data.links || []);
    return '';
  }

  // Every agent tool call crosses the MCP client boundary, so tool and mcp
  // spans are the same surface — one tab covers both.
  function isMcpOrToolSpan(s) {
    return s.span_type === 'mcp' || s.span_type === 'tool';
  }

  function renderTimeline(spans, run) {
    if (!spans.length) {
      return `${run.error_message ? errorBox(run.error_message) : ''}<p class="text-muted small">No spans recorded.</p>`;
    }
    let cumulativeMs = 0;
    const rows = spans.map((s) => {
      const isLlm = s.span_type === 'llm';
      const iconClass = isLlm ? 'llm' : (s.status === 'failed' ? 'tool failed' : 'tool');
      const icon = isLlm ? '<i class="bi bi-cpu"></i>' : '<i class="bi bi-wrench"></i>';
      const title = isLlm ? 'LLM Call' : `${s.span_type}: ${s.name || 'unknown'}`;
      let detail = '';
      if (s.input_preview) detail += `<pre>${escapeHtml(String(s.input_preview).substring(0, 300))}</pre>`;
      if (s.output_preview) detail += `<div style="margin-top:4px;color:#059669;">Output: ${escapeHtml(String(s.output_preview).substring(0, 200))}</div>`;
      if (s.error_message) detail += `<div class="error-text">Error: ${escapeHtml(String(s.error_message).substring(0, 200))}</div>`;
      const html = `
        <div class="timeline-step">
          <div class="timeline-icon ${iconClass}">${icon}</div>
          <div class="timeline-body">
            <div class="timeline-body-header">
              <span class="timeline-step-title">${escapeHtml(title)}</span>
              <span class="timeline-step-time">${formatDuration(s.latency_ms)} @ ${formatDuration(cumulativeMs)}</span>
            </div>
            <div class="timeline-step-detail">${detail}</div>
          </div>
        </div>`;
      cumulativeMs += (s.latency_ms || 0);
      return html;
    }).join('');
    return `${run.error_message ? errorBox(run.error_message) : ''}<div class="trace-timeline">${rows}</div>`;
  }

  function renderMessages(run) {
    return `
      <div class="trace-io">
        <div class="trace-io-box">
          <h6>Input</h6>
          <pre>${escapeHtml((run.input_preview || 'N/A').substring(0, 1000))}</pre>
        </div>
        <div class="trace-io-box">
          <h6>Output</h6>
          <pre>${escapeHtml((run.output_preview || 'N/A').substring(0, 1000))}</pre>
        </div>
      </div>`;
  }

  function renderSpanTable(spans, empty) {
    if (!spans.length) return `<p class="text-muted small">${empty}</p>`;
    return `<table class="trace-table">
      <thead><tr><th>Name</th><th>Status</th><th>Latency</th><th>Detail</th></tr></thead>
      <tbody>${spans.map(s => `
        <tr>
          <td><code>${escapeHtml(s.name || '')}</code></td>
          <td><span class="trace-status-badge ${s.status}">${s.status}</span></td>
          <td>${formatDuration(s.latency_ms)}</td>
          <td><pre>${escapeHtml(String(s.output_preview || s.input_preview || s.error_message || '').substring(0, 200))}</pre></td>
        </tr>`).join('')}</tbody>
    </table>`;
  }

  function renderArtifacts(artifacts) {
    if (!artifacts.length) return '<p class="text-muted small">No artifacts.</p>';
    return artifacts.map(a => `
      <div class="trace-artifact">
        <div class="trace-artifact-head">
          <strong>${escapeHtml(a.name || a.artifact_type)}</strong>
          <span class="text-muted small">${escapeHtml(a.mime_type || a.artifact_type || '')}</span>
        </div>
        ${a.preview_text ? `<pre>${escapeHtml(String(a.preview_text).substring(0, 500))}</pre>` : ''}
        ${a.storage_uri ? `<div class="small text-muted">${escapeHtml(a.storage_uri)}</div>` : ''}
      </div>`).join('');
  }

  function renderCost(run) {
    return `<div class="trace-detail-stats">
      ${stat('Cost (CNY)', formatCost(run.cost_cny))}
      ${stat('Model', run.model_name || '-')}
      ${stat('Tokens in', run.tokens_input || 0)}
      ${stat('Tokens out', run.tokens_output || 0)}
      ${stat('MCP latency', formatDuration(run.mcp_latency_ms))}
      ${stat('Sandbox latency', formatDuration(run.sandbox_latency_ms))}
    </div>`;
  }

  function renderEval(run, links) {
    if (run.eval_run_id == null && run.eval_case_id == null) {
      return '<p class="text-muted small">This trace is not linked to an eval run.</p>';
    }
    const reportLink = run.eval_run_id != null
      ? `<a href="/ai/evals?run=${encodeURIComponent(run.eval_run_id)}">View eval report &rarr;</a>`
      : '';
    // Grader results are loaded lazily from the eval case bound to this trace.
    if (run.trace_id) loadEvalCase(run.trace_id);
    return `<div class="trace-detail-stats">
      ${stat('Eval Run', run.eval_run_id != null ? run.eval_run_id : '-')}
      ${stat('Eval Case', run.eval_case_id || '-')}
    </div>
    <div style="margin-top:8px;">${reportLink}</div>
    <div id="evalGraderBox" class="small text-muted" style="margin-top:10px;">Loading graders…</div>
    ${links.length ? `<div class="small text-muted" style="margin-top:8px;">Links: ${links.map(l => escapeHtml(`${l.link_type}:${l.target_id}`)).join(', ')}</div>` : ''}`;
  }

  function loadEvalCase(traceId) {
    fetch(`/api/v1/ai/evals/cases/by-trace/${encodeURIComponent(traceId)}`)
      .then(r => r.json())
      .then(data => {
        const box = document.getElementById('evalGraderBox');
        if (!box) return;
        const c = data.case;
        if (!c) { box.innerHTML = 'No eval case bound to this trace.'; return; }
        const verdict = c.passed
          ? '<span class="trace-status-badge completed">passed</span>'
          : `<span class="trace-status-badge failed">${escapeHtml(c.failure_type || 'failed')}</span>`;
        const dataset = escapeHtml(`${c.case_type || ''} · ${c.suite || ''}`);
        const graders = (c.graders || []).map(g => `
          <tr>
            <td><code>${escapeHtml(g.grader_type)}</code></td>
            <td>${g.passed == null ? 'skipped' : (g.passed ? 'pass' : 'fail')}</td>
            <td>${g.score == null ? '-' : Number(g.score).toFixed(2)}</td>
            <td><pre>${escapeHtml(String(g.reason || '').substring(0, 160))}</pre></td>
          </tr>`).join('');
        box.innerHTML = `
          <div style="margin-bottom:6px;">Dataset: <strong>${dataset}</strong> &nbsp; ${verdict}</div>
          ${graders ? `<table class="trace-table">
            <thead><tr><th>Grader</th><th>Result</th><th>Score</th><th>Reason</th></tr></thead>
            <tbody>${graders}</tbody></table>` : '<div>No graders recorded.</div>'}`;
      })
      .catch(() => {
        const box = document.getElementById('evalGraderBox');
        if (box) box.innerHTML = 'Failed to load grader results.';
      });
  }

  // ── Helpers ───────────────────────────────────────────────
  function stat(label, value) {
    return `<div class="trace-stat">
      <div class="trace-stat-label">${label}</div>
      <div class="trace-stat-value">${value}</div>
    </div>`;
  }

  function errorBox(msg) {
    return `<div style="margin-bottom:14px;padding:12px 16px;background:#fef2f2;border-radius:10px;border:1px solid #fecaca;">
      <strong style="color:#991b1b;">Error:</strong>
      <span style="color:#7f1d1d;">${escapeHtml(msg)}</span>
    </div>`;
  }

  function formatDuration(ms) {
    if (ms == null) return '-';
    if (ms < 1000) return ms + 'ms';
    return (ms / 1000).toFixed(1) + 's';
  }

  function formatCost(cost) {
    if (cost == null) return '-';
    const n = typeof cost === 'number' ? cost : parseFloat(cost);
    if (isNaN(n)) return '-';
    return '¥' + n.toFixed(4);
  }

  function formatTime(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    const diffMs = new Date() - d;
    if (diffMs < 60000) return 'just now';
    if (diffMs < 3600000) return Math.floor(diffMs / 60000) + 'm ago';
    if (diffMs < 86400000) return Math.floor(diffMs / 3600000) + 'h ago';
    return d.toLocaleDateString();
  }

  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text == null ? '' : text;
    return div.innerHTML;
  }

  // ── Event listeners ───────────────────────────────────────
  if (filterEl) filterEl.addEventListener('change', () => loadTraces(0));
  if (statusEl) statusEl.addEventListener('change', () => loadTraces(0));
  if (searchEl) {
    let t = null;
    searchEl.addEventListener('input', () => {
      clearTimeout(t);
      t = setTimeout(() => loadTraces(0), 300);
    });
  }
  if (refreshBtn) refreshBtn.addEventListener('click', () => loadTraces(0));

  loadTraces(0);
})();
