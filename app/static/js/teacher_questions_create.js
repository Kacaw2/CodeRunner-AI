import { getToken, authenticatedFetch } from '/static/js/auth.js';

const API_BASE = '/api/v1';
let allProblems = [];
let currentQuizId = null;
let showOnlyMyProblems = false;

const token = getToken();
if (!token) {
  window.location.href = '/auth/login?next=/teacher/questions/create';
}

function showMessage(elementId, message, isSuccess) {
  const el = document.getElementById(elementId);
  if (!el) return;
  el.textContent = message;
  el.className = isSuccess ? 'success-msg' : 'error-msg';
  setTimeout(() => {
    el.textContent = '';
    el.className = '';
  }, 5000);
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text ?? '';
  return div.innerHTML;
}

async function loadQuizzes() {
  try {
    const response = await authenticatedFetch(`${API_BASE}/quizzes`);
    const data = await response.json();
    if (!response.ok) return;

    const quizzes = Array.isArray(data) ? data : (data.items || []);
    const options = quizzes.map(q => `<option value="${q.id}">${escapeHtml(q.title)}</option>`).join('');
    document.getElementById('quizSelect').innerHTML = '<option value="">-- All Problems --</option>' + options;
    document.getElementById('qQuizSelect').innerHTML = '<option value="">-- No Quiz --</option>' + options;
  } catch (error) {
    console.error('Error loading quizzes:', error);
  }
}

async function createQuiz() {
  const title = document.getElementById('createQuizTitle').value.trim();
  const description = document.getElementById('createQuizDescription').value.trim();
  if (!title) {
    showMessage('createQuizMsg', 'Please enter a quiz title', false);
    return;
  }

  try {
    const response = await authenticatedFetch(`${API_BASE}/quizzes`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title, description, is_published: false })
    });
    const data = await response.json();
    if (!response.ok) {
      showMessage('createQuizMsg', data.message || 'Failed to create quiz', false);
      return;
    }

    const modal = window.bootstrap.Modal.getInstance(document.getElementById('createQuizModal'));
    if (modal) modal.hide();
    document.getElementById('createQuizTitle').value = '';
    document.getElementById('createQuizDescription').value = '';
    await loadQuizzes();
    document.getElementById('quizSelect').value = data.id;
    document.getElementById('qQuizSelect').value = data.id;
    await loadProblems(data.id);
    showMessage('msg', `Quiz "${title}" created successfully!`, true);
  } catch (error) {
    console.error('Error creating quiz:', error);
    showMessage('createQuizMsg', 'Error creating quiz', false);
  }
}

async function loadProblems(quizId = null) {
  currentQuizId = quizId;
  const params = new URLSearchParams();
  if (quizId) {
    params.append('quiz_id', quizId);
  } else if (showOnlyMyProblems) {
    params.append('created_by_me', 'true');
  }
  const url = `${API_BASE}/teacher/problems${params.toString() ? `?${params}` : ''}`;

  try {
    const response = await authenticatedFetch(url);
    const data = await response.json();
    if (!response.ok) {
      showEmptyState('Failed to load problems');
      return;
    }
    allProblems = Array.isArray(data) ? data : (data.items || []);
    renderProblems(allProblems);
    updateProblemCount(allProblems.length);
    updateFilterBadge();
  } catch (error) {
    console.error('Error loading problems:', error);
    showEmptyState('Error loading problems');
  }
}

function renderProblems(problems) {
  const tbody = document.getElementById('qTableBody');
  if (!problems || problems.length === 0) {
    showEmptyState(currentQuizId ? 'No problems in this quiz yet' : 'No problems yet. Create your first problem!');
    return;
  }

  tbody.innerHTML = problems.map(problem => {
    const languages = (problem.variants || [])
      .map(v => (v.language || '').toUpperCase())
      .filter(Boolean)
      .join(' / ') || '-';
    const creatorDisplay = problem.creator?.name ? escapeHtml(problem.creator.name) : 'Unknown';
    return `
      <tr data-question-id="${problem.id}">
        <td><span class="question-id">#${problem.id}</span></td>
        <td><span class="question-title" title="${escapeHtml(problem.title)}">${escapeHtml(problem.title)}</span></td>
        <td class="text-center"><span class="badge bg-creator">${creatorDisplay}</span></td>
        <td class="text-center"><span class="badge bg-info">${languages}</span></td>
        <td class="text-center"><span class="badge ${problem.test_case_count > 0 ? 'bg-success' : 'bg-secondary'}">${problem.test_case_count || 0}</span></td>
        <td class="text-center">
          <div class="btn-group-actions">
            <a href="/problem/${problem.id}?language=python" target="_blank" class="btn btn-outline-primary btn-sm btn-action" title="View problem">
              <i class="bi bi-eye"></i>
            </a>
            <button class="btn btn-outline-success btn-sm btn-action" data-manage="${problem.id}" title="Manage problem">
              <i class="bi bi-gear"></i>
            </button>
            <button class="btn btn-outline-danger btn-sm btn-action" data-delete="${problem.id}" title="Delete problem">
              <i class="bi bi-trash"></i>
            </button>
          </div>
        </td>
      </tr>
    `;
  }).join('');
}

function showEmptyState(message) {
  document.getElementById('qTableBody').innerHTML = `
    <tr>
      <td colspan="6" class="text-center py-5">
        <div class="empty-state">
          <i class="bi bi-inbox"></i>
          <div class="mt-2 text-muted">${escapeHtml(message)}</div>
        </div>
      </td>
    </tr>
  `;
}

function updateProblemCount(count) {
  document.getElementById('questionCount').textContent = `${count} problem${count !== 1 ? 's' : ''}`;
}

function updateFilterBadge() {
  const filterBadge = document.getElementById('filterBadge');
  if (!filterBadge) return;
  if (currentQuizId) {
    filterBadge.textContent = 'Quiz Filter Active';
    filterBadge.className = 'badge bg-primary ms-2';
  } else if (showOnlyMyProblems) {
    filterBadge.textContent = 'My Problems Only';
    filterBadge.className = 'badge bg-success ms-2';
  } else {
    filterBadge.textContent = 'All Problems';
    filterBadge.className = 'badge bg-secondary ms-2';
  }
}

function getValue(id) {
  return document.getElementById(id)?.value || '';
}

async function createProblem(event) {
  event.preventDefault();
  const title = getValue('qTitle').trim();
  const description = getValue('qDesc').trim();
  if (!title || !description) {
    showMessage('msg', 'Title and description are required', false);
    return;
  }

  const selectedQuizId = getValue('qQuizSelect');
  const payload = {
    quiz_id: selectedQuizId ? parseInt(selectedQuizId, 10) : null,
    title,
    description,
    difficulty: getValue('qDifficulty') || 'easy',
    order: parseInt(getValue('qOrder'), 10) || 1,
    points: parseInt(getValue('qPoints'), 10) || 10,
    python_starter_code: getValue('pythonStarter'),
    python_solution: getValue('pythonSolution'),
    python_solution_explanation: getValue('pythonSolutionExplanation'),
    c_starter_code: getValue('cStarter'),
    c_solution: getValue('cSolution'),
    c_solution_explanation: getValue('cSolutionExplanation')
  };

  try {
    showMessage('msg', 'Creating problem...', true);
    const response = await authenticatedFetch(`${API_BASE}/problems`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await response.json();
    if (!response.ok) {
      showMessage('msg', data.message || 'Failed to create problem', false);
      return;
    }

    ['qTitle', 'qDesc', 'pythonStarter', 'pythonSolution', 'pythonSolutionExplanation', 'cStarter', 'cSolution', 'cSolutionExplanation']
      .forEach(id => { document.getElementById(id).value = ''; });
    document.getElementById('qDifficulty').value = 'easy';
    document.getElementById('qOrder').value = '1';
    document.getElementById('qPoints').value = '10';
    await loadProblems(currentQuizId);
    highlightNewProblem(data.id);
    showMessage('msg', `Problem "${title}" created successfully!`, true);
  } catch (error) {
    console.error('Error creating problem:', error);
    showMessage('msg', 'Error creating problem', false);
  }
}

function highlightNewProblem(problemId) {
  setTimeout(() => {
    const row = document.querySelector(`tr[data-question-id="${problemId}"]`);
    if (!row) return;
    row.scrollIntoView({ behavior: 'smooth', block: 'center' });
    row.style.backgroundColor = '#dbeafe';
    setTimeout(() => { row.style.backgroundColor = ''; }, 2000);
  }, 300);
}

async function deleteProblem(id) {
  if (!confirm(`Are you sure you want to delete problem #${id}?\n\nThis will also delete all variants and test cases.`)) return;
  try {
    const response = await authenticatedFetch(`${API_BASE}/problems/${id}`, { method: 'DELETE' });
    if (response.ok) {
      showMessage('msg', 'Problem deleted successfully', true);
      await loadProblems(currentQuizId);
    } else {
      const data = await response.json();
      alert('Delete failed: ' + (data.message || 'Unknown error'));
    }
  } catch (error) {
    console.error('Error deleting problem:', error);
    alert('Error deleting problem');
  }
}

function filterProblems(searchTerm) {
  const term = searchTerm.toLowerCase().trim();
  if (!term) {
    renderProblems(allProblems);
    updateProblemCount(allProblems.length);
    return;
  }
  const filtered = allProblems.filter(problem => {
    return String(problem.id).includes(term)
      || (problem.title || '').toLowerCase().includes(term)
      || (problem.creator?.name || '').toLowerCase().includes(term);
  });
  renderProblems(filtered);
  updateProblemCount(filtered.length);
}

function toggleCreatorFilter() {
  showOnlyMyProblems = !showOnlyMyProblems;
  const btn = document.getElementById('creatorFilterBtn');
  if (btn) {
    if (showOnlyMyProblems) {
      btn.classList.add('active');
      btn.innerHTML = '<i class="bi bi-funnel-fill"></i> My Problems';
    } else {
      btn.classList.remove('active');
      btn.innerHTML = '<i class="bi bi-funnel"></i> All Problems';
    }
  }
  loadProblems(currentQuizId);
}

function debounce(func, wait) {
  let timeout;
  return (...args) => {
    clearTimeout(timeout);
    timeout = setTimeout(() => func(...args), wait);
  };
}

document.addEventListener('DOMContentLoaded', async () => {
  await loadQuizzes();
  await loadProblems();

  document.getElementById('refreshQuiz').addEventListener('click', loadQuizzes);
  document.getElementById('createQuizBtn').addEventListener('click', () => {
    new window.bootstrap.Modal(document.getElementById('createQuizModal')).show();
  });
  document.getElementById('saveCreateQuizBtn').addEventListener('click', createQuiz);
  document.getElementById('quizSelect').addEventListener('change', event => {
    loadProblems(event.target.value || null);
  });
  document.getElementById('creatorFilterBtn')?.addEventListener('click', toggleCreatorFilter);
  document.getElementById('questionForm').addEventListener('submit', createProblem);
  document.getElementById('createBtn').addEventListener('click', createProblem);
  document.getElementById('searchInput').addEventListener('input', debounce(event => {
    filterProblems(event.target.value);
  }, 300));
  document.getElementById('qTableBody').addEventListener('click', event => {
    const deleteBtn = event.target.closest('[data-delete]');
    if (deleteBtn) {
      deleteProblem(deleteBtn.getAttribute('data-delete'));
      return;
    }
    const manageBtn = event.target.closest('[data-manage]');
    if (manageBtn) {
      window.location.href = `/teacher/problems/${manageBtn.getAttribute('data-manage')}/manage`;
    }
  });
});

window.QuestionWorkspace = {
  loadQuestions: loadProblems,
  loadProblems,
  loadQuizzes,
  createQuestion: createProblem,
  createProblem,
  createQuiz,
  toggleCreatorFilter
};
