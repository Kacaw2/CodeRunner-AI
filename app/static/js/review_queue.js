document.addEventListener('DOMContentLoaded', () => {
  const draftList = document.getElementById('draftList');
  const emptyState = document.getElementById('emptyState');
  const pendingCount = document.getElementById('pendingCount');
  const statusFilter = document.getElementById('statusFilter');
  const refreshBtn = document.getElementById('refreshBtn');

  let currentDraftId = null;
  let previewModal = null;
  let revisionModal = null;

  if (document.getElementById('previewModal')) {
    previewModal = new bootstrap.Modal(document.getElementById('previewModal'));
  }
  if (document.getElementById('revisionModal')) {
    revisionModal = new bootstrap.Modal(document.getElementById('revisionModal'));
  }

  // Load drafts
  async function loadDrafts() {
    const status = statusFilter.value;
    draftList.innerHTML = '<div class="loading-placeholder"><div class="spinner-border spinner-border-sm text-primary"></div><span>Loading drafts...</span></div>';
    emptyState.classList.add('d-none');

    try {
      const resp = await fetch(`/api/v1/ai/generate/drafts?status=${status}&limit=50`);
      if (!resp.ok) throw new Error('Failed to load drafts');
      const data = await resp.json();

      if (!data.drafts || data.drafts.length === 0) {
        draftList.innerHTML = '';
        emptyState.classList.remove('d-none');
        pendingCount.textContent = '0 pending';
        return;
      }

      pendingCount.textContent = `${data.total} ${status === 'all' ? 'total' : status.replace('_', ' ')}`;
      renderDrafts(data.drafts);
    } catch (err) {
      draftList.innerHTML = `<div class="text-danger text-center p-3">Failed to load drafts: ${err.message}</div>`;
    }
  }

  function renderDrafts(drafts) {
    draftList.innerHTML = '';
    emptyState.classList.add('d-none');

    drafts.forEach(draft => {
      const qd = draft.question_data?.question || draft.question_data || {};
      const title = qd.title || 'Untitled Question';
      const desc = qd.description || '';
      const lang = qd.programming_language || 'python';
      const difficulty = qd.difficulty || 'medium';
      const testCount = (qd.test_cases || []).length;
      const verified = qd.verified;

      const statusLabel = draft.status.replace(/_/g, ' ');
      const statusClass = `status-${draft.status}`;
      const validClass = draft.validation_status === 'passed' ? 'validation-passed'
        : draft.validation_status === 'failed' ? 'validation-failed' : 'validation-unverified';

      const timeAgo = formatTimeAgo(draft.created_at);

      const card = document.createElement('div');
      card.className = 'draft-card';
      card.innerHTML = `
        <div class="draft-card-header">
          <h5 class="draft-card-title">${escapeHtml(title)}</h5>
          <span class="badge ${statusClass}">${statusLabel}</span>
        </div>
        <div class="draft-card-meta">
          <span><i class="bi bi-code-slash"></i> ${escapeHtml(lang)}</span>
          <span><i class="bi bi-speedometer2"></i> ${escapeHtml(difficulty)}</span>
          <span><i class="bi bi-check2-square"></i> ${testCount} tests</span>
          <span class="badge ${validClass}">${verified ? 'Verified' : draft.validation_status || 'unverified'}</span>
          ${draft.revision_count > 0 ? `<span><i class="bi bi-arrow-repeat"></i> Rev #${draft.revision_count}</span>` : ''}
          <span><i class="bi bi-clock"></i> ${timeAgo}</span>
        </div>
        <div class="draft-card-desc">${escapeHtml(desc.substring(0, 200))}</div>
        <div class="draft-card-actions">
          <button class="btn btn-sm btn-outline-primary preview-btn" data-id="${draft.id}">
            <i class="bi bi-eye"></i> Preview
          </button>
          ${draft.status === 'pending_review' ? `
            <button class="btn btn-sm btn-success approve-btn" data-id="${draft.id}">
              <i class="bi bi-check-lg"></i> Approve
            </button>
            <button class="btn btn-sm btn-warning revise-btn" data-id="${draft.id}">
              <i class="bi bi-pencil"></i> Revise
            </button>
            <button class="btn btn-sm btn-outline-danger reject-btn" data-id="${draft.id}">
              <i class="bi bi-x-lg"></i> Reject
            </button>
          ` : ''}
        </div>
      `;

      // Review notes
      if (draft.review_notes && draft.status === 'revision_requested') {
        const notesDiv = document.createElement('div');
        notesDiv.className = 'revision-history mt-2';
        notesDiv.innerHTML = `<strong>Teacher note:</strong> ${escapeHtml(draft.review_notes)}`;
        card.appendChild(notesDiv);
      }

      draftList.appendChild(card);
    });

    // Bind events
    draftList.querySelectorAll('.preview-btn').forEach(btn => {
      btn.addEventListener('click', () => openPreview(btn.dataset.id));
    });
    draftList.querySelectorAll('.approve-btn').forEach(btn => {
      btn.addEventListener('click', () => reviewAction(btn.dataset.id, 'approve'));
    });
    draftList.querySelectorAll('.revise-btn').forEach(btn => {
      btn.addEventListener('click', () => openRevision(btn.dataset.id));
    });
    draftList.querySelectorAll('.reject-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        if (confirm('Reject this draft? This cannot be undone.')) {
          reviewAction(btn.dataset.id, 'reject');
        }
      });
    });
  }

  async function openPreview(draftId) {
    currentDraftId = draftId;
    try {
      const resp = await fetch(`/api/v1/ai/generate/drafts/${draftId}`);
      if (!resp.ok) throw new Error('Failed to load draft');
      const data = await resp.json();
      const draft = data.draft;
      const qd = draft.question_data?.question || draft.question_data || {};

      document.getElementById('previewTitle').textContent = qd.title || 'Question Preview';

      let html = '';
      html += `<h6>Description</h6><div>${escapeHtml(qd.description || '')}</div>`;

      if (qd.starter_code) {
        html += `<h6>Starter Code</h6><pre>${escapeHtml(qd.starter_code)}</pre>`;
      }
      html += `<h6>Reference Solution</h6><pre>${escapeHtml(qd.solution || '')}</pre>`;

      if (qd.solution_explanation) {
        html += `<h6>Solution Explanation</h6><div>${escapeHtml(qd.solution_explanation)}</div>`;
      }

      html += `<h6>Test Cases (${(qd.test_cases || []).length})</h6>`;
      (qd.test_cases || []).forEach((tc, i) => {
        const hidden = tc.is_hidden ? ' hidden-case' : '';
        html += `<div class="test-case-item${hidden}">
          <strong>Case ${i + 1}</strong>${tc.is_hidden ? ' <span class="badge bg-warning text-dark">Hidden</span>' : ''}
          <br>Input: <code>${escapeHtml(tc.input || '')}</code>
          <br>Expected: <code>${escapeHtml(tc.expected_output || '')}</code>
        </div>`;
      });

      if (draft.review_notes) {
        html += `<h6>Review Notes</h6><div class="revision-history">${escapeHtml(draft.review_notes)}</div>`;
      }

      document.getElementById('previewBody').innerHTML = html;

      const footer = document.getElementById('previewFooter');
      const approveBtn = document.getElementById('modalApproveBtn');
      const reviseBtn = document.getElementById('modalReviseBtn');
      const rejectBtn = document.getElementById('modalRejectBtn');
      const isPending = draft.status === 'pending_review';
      approveBtn.style.display = isPending ? '' : 'none';
      reviseBtn.style.display = isPending ? '' : 'none';
      rejectBtn.style.display = isPending ? '' : 'none';

      previewModal.show();
    } catch (err) {
      alert('Failed to load preview: ' + err.message);
    }
  }

  function openRevision(draftId) {
    currentDraftId = draftId;
    document.getElementById('revisionNotes').value = '';
    revisionModal.show();
  }

  async function reviewAction(draftId, action, notes) {
    try {
      const body = { action };
      if (notes) body.notes = notes;

      const resp = await fetch(`/api/v1/ai/generate/drafts/${draftId}/review`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!resp.ok) {
        const err = await resp.json();
        throw new Error(err.message || 'Review action failed');
      }

      const data = await resp.json();
      if (previewModal) previewModal.hide();
      if (revisionModal) revisionModal.hide();

      if (action === 'approve') {
        showToast(`Question published! (ID: ${data.question_id})`, 'success');
      } else if (action === 'request_revision') {
        showToast('Revision requested. AI is revising...', 'warning');
      } else if (action === 'reject') {
        showToast('Draft rejected.', 'secondary');
      }

      loadDrafts();
    } catch (err) {
      alert('Action failed: ' + err.message);
    }
  }

  // Modal button handlers
  document.getElementById('modalApproveBtn')?.addEventListener('click', () => {
    if (currentDraftId && confirm('Approve and publish this question?')) {
      reviewAction(currentDraftId, 'approve');
    }
  });
  document.getElementById('modalReviseBtn')?.addEventListener('click', () => {
    if (currentDraftId) {
      previewModal.hide();
      openRevision(currentDraftId);
    }
  });
  document.getElementById('modalRejectBtn')?.addEventListener('click', () => {
    if (currentDraftId && confirm('Reject this draft?')) {
      reviewAction(currentDraftId, 'reject');
    }
  });
  document.getElementById('submitRevisionBtn')?.addEventListener('click', () => {
    const notes = document.getElementById('revisionNotes').value.trim();
    if (!notes) {
      alert('Please provide feedback for the AI.');
      return;
    }
    if (currentDraftId) {
      reviewAction(currentDraftId, 'request_revision', notes);
    }
  });

  // Filter & refresh
  statusFilter.addEventListener('change', loadDrafts);
  refreshBtn.addEventListener('click', loadDrafts);

  // Helpers
  function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  function formatTimeAgo(isoStr) {
    if (!isoStr) return '';
    const diff = Date.now() - new Date(isoStr).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins}m ago`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.floor(hours / 24);
    return `${days}d ago`;
  }

  function showToast(message, type) {
    const toast = document.createElement('div');
    toast.className = `alert alert-${type} position-fixed bottom-0 end-0 m-3`;
    toast.style.zIndex = '9999';
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 3000);
  }

  // Initial load
  loadDrafts();
});
