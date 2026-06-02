/**
 * Agent Eval runner + report viewer. Lists past eval runs, kicks off new runs
 * by dataset selector, and renders a full ReportGenerator report (quality /
 * cost / latency / failure types / regressions) with per-case trace links.
 */
(function () {
  'use strict';

  const historyEl = document.getElementById('evalHistory');
  const reportEl = document.getElementById('evalReport');
  const selectorEl = document.getElementById('selectorFilter');
  const runBtn = document.getElementById('runEvalBtn');
  const refreshBtn = document.getElementById('refreshHistoryBtn');

  // ── Eval history ──────────────────────────────────────────
  function loadHistory() {
    fetch('/api/v1/ai/evals/history?limit=30')
      .then(r => r.json())
      .then(data => renderHistory(data.runs || []))
      .catch(() => {
        historyEl.innerHTML = '<p class="text-danger small p-3">Failed to load eval history.</p>';
      });
  }

  function renderHistory(runs) {
    if (!runs.length) {
      historyEl.innerHTML = '<p class="text-muted small p-3">No eval runs yet.</p>';
      return;
    }
    historyEl.innerHTML = runs.map(r => `
      <div class="trace-item" data-id="${r.id}">
        <div class="trace-item-header">
          <span class="trace-agent-badge">${escapeHtml(r.suite_name || '')}</span>
          <span class="trace-status-badge ${passClass(r.pass_rate)}">${formatPct(r.pass_rate)}</span>
        </div>
        <div class="trace-item-meta">
          <span><i class="bi bi-check2-square"></i> ${r.passed_cases || 0}/${r.total_cases || 0}</span>
          <span><i class="bi bi-cpu"></i> ${escapeHtml(r.model_name || '-')}</span>
        </div>
        <div class="trace-item-meta">
          <span class="trace-source">run #${r.id}</span>
          <span>${formatTime(r.run_at)}</span>
        </div>
      </div>
    `).join('');

    historyEl.querySelectorAll('.trace-item').forEach(item => {
      item.addEventListener('click', () => {
        historyEl.querySelectorAll('.trace-item').forEach(i => i.classList.remove('active'));
        item.classList.add('active');
        loadReport(item.dataset.id);
      });
    });
  }

  // ── Run a new eval ────────────────────────────────────────
  function runEval() {
    const selector = selectorEl ? selectorEl.value : 'all';
    runBtn.disabled = true;
    runBtn.innerHTML = '<i class="bi bi-hourglass-split"></i> Running…';
    fetch('/api/v1/ai/evals/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ selector: selector })
    })
      .then(r => r.json())
      .then(data => {
        const report = data.report || {};
        loadHistory();
        if (report.eval_run_id != null) loadReport(report.eval_run_id);
      })
      .catch(() => {
        reportEl.innerHTML = '<p class="text-danger p-3">Eval run failed.</p>';
      })
      .finally(() => {
        runBtn.disabled = false;
        runBtn.innerHTML = '<i class="bi bi-play-fill"></i> Run eval';
      });
  }

  // ── Report detail ─────────────────────────────────────────
  function loadReport(runId) {
    fetch(`/api/v1/ai/evals/runs/${encodeURIComponent(runId)}`)
      .then(r => r.json())
      .then(renderReport)
      .catch(() => {
        reportEl.innerHTML = '<p class="text-danger p-3">Failed to load report.</p>';
      });
  }

  function renderReport(data) {
    const s = data.summary || {};
    const cases = data.cases || [];
    const cost = s.cost_cny || {};
    const lat = s.latency_ms || {};
    const failed = cases.filter(c => !c.passed);

    reportEl.innerHTML = `
      <div class="trace-detail-header">
        <div class="trace-detail-title">
          Eval Run <code>#${data.eval_run_id}</code>
          <span class="trace-status-badge ${passClass(s.pass_rate)}" style="margin-left:8px;">${formatPct(s.pass_rate)}</span>
          <span class="text-muted small" style="margin-left:8px;">${escapeHtml(s.suite_name || '')}</span>
        </div>
        <div class="trace-detail-stats">
          ${stat('Cases', `${s.passed_cases || 0}/${s.total_cases || 0}`)}
          ${stat('Cost total', `¥${(cost.total || 0).toFixed(4)}`)}
          ${stat('Cost p95', `¥${(cost.p95 || 0).toFixed(4)}`)}
          ${stat('Latency p50', `${lat.p50 || 0}ms`)}
          ${stat('Latency p95', `${lat.p95 || 0}ms`)}
        </div>
      </div>
      <div class="trace-tab-body">
        ${renderGraderRates(s.grader_pass_rates || {})}
        ${renderFailureTypes(s.failure_types || {})}
        ${renderRegressions(s.regressions || [])}
        ${renderFailedCases(failed)}
      </div>`;

    reportEl.querySelectorAll('[data-trace]').forEach(a => {
      a.addEventListener('click', e => {
        e.preventDefault();
        window.location.href = `/ai/traces?focus=${encodeURIComponent(a.dataset.trace)}`;
      });
    });
    reportEl.querySelectorAll('[data-promote]').forEach(btn => {
      btn.addEventListener('click', () => promoteRegression(btn.dataset.promote, btn));
    });
  }

  function renderGraderRates(rates) {
    const keys = Object.keys(rates);
    if (!keys.length) return '';
    return `<h6 class="mt-2">Grader pass rates</h6><div class="trace-detail-stats">
      ${keys.sort().map(k => stat(k, formatPct(rates[k]))).join('')}
    </div>`;
  }

  function renderFailureTypes(types) {
    const keys = Object.keys(types);
    if (!keys.length) return '<h6 class="mt-3">Failure types</h6><p class="text-muted small">None.</p>';
    return `<h6 class="mt-3">Failure types</h6><div class="trace-detail-stats">
      ${keys.sort().map(k => stat(k, types[k])).join('')}
    </div>`;
  }

  function renderRegressions(regressions) {
    if (!regressions.length) return '';
    return `<h6 class="mt-3 text-danger">Regressions (${regressions.length})</h6>
      <ul class="small">${regressions.map(r =>
        `<li><code>${escapeHtml(r.case_id)}</code> — ${escapeHtml(r.failure_type || 'failed')}</li>`
      ).join('')}</ul>`;
  }

  function renderFailedCases(failed) {
    if (!failed.length) return '<h6 class="mt-3">Failed cases</h6><p class="text-muted small">All cases passed.</p>';
    return `<h6 class="mt-3">Failed cases (${failed.length})</h6>
      <table class="trace-table">
        <thead><tr><th>Case</th><th>Type</th><th>Trace</th><th></th></tr></thead>
        <tbody>${failed.map(c => `
          <tr>
            <td><code>${escapeHtml(c.case_id)}</code></td>
            <td>${escapeHtml(c.failure_type || 'failed')}</td>
            <td>${c.trace_id
              ? `<a href="#" data-trace="${escapeHtml(c.trace_id)}"><code>${escapeHtml(c.trace_id.substring(0, 8))}…</code></a>`
              : '-'}</td>
            <td>${c.trace_id
              ? `<button class="btn btn-sm btn-outline-danger" data-promote="${escapeHtml(c.trace_id)}">→ Regression</button>`
              : ''}</td>
          </tr>`).join('')}</tbody>
      </table>`;
  }

  function promoteRegression(traceId, btn) {
    btn.disabled = true;
    fetch('/api/v1/ai/evals/promote-regression', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ trace_id: traceId, reason: 'promoted from eval report' })
    })
      .then(r => r.json())
      .then(data => {
        btn.textContent = data.case ? 'Added ✓' : 'Failed';
      })
      .catch(() => { btn.textContent = 'Failed'; btn.disabled = false; });
  }

  // ── Helpers ───────────────────────────────────────────────
  function stat(label, value) {
    return `<div class="trace-stat">
      <div class="trace-stat-label">${escapeHtml(String(label))}</div>
      <div class="trace-stat-value">${escapeHtml(String(value))}</div>
    </div>`;
  }

  function passClass(rate) {
    const n = Number(rate) || 0;
    if (n >= 0.9) return 'completed';
    if (n >= 0.6) return 'limit_exceeded';
    return 'failed';
  }

  function formatPct(rate) {
    const n = Number(rate);
    if (isNaN(n)) return '-';
    return (n * 100).toFixed(0) + '%';
  }

  function formatTime(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    if (isNaN(d.getTime())) return '';
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

  // ── Wiring ────────────────────────────────────────────────
  if (runBtn) runBtn.addEventListener('click', runEval);
  if (refreshBtn) refreshBtn.addEventListener('click', loadHistory);

  loadHistory();
})();
