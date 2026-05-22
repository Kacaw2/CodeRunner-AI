import { getToken, authenticatedFetch } from '/static/js/auth.js';

const API_BASE = '/api/v1';
let problemId = null;
let problemData = null;

const token = getToken();
if (!token) {
  window.location.href = '/auth/login?next=' + window.location.pathname;
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

function getProblemIdFromUrl() {
  const parts = window.location.pathname.split('/');
  const index = parts.indexOf('problems');
  return index !== -1 && parts[index + 1] ? parseInt(parts[index + 1], 10) : null;
}

function variantFor(language) {
  return (problemData?.variants || []).find(v => (v.language || '').toLowerCase() === language) || {};
}

async function loadProblemDetails() {
  try {
    const response = await authenticatedFetch(`${API_BASE}/problems/${problemId}/manage`);
    if (!response.ok) {
      const data = await response.json();
      alert('Failed to load problem: ' + (data.message || 'Unknown error'));
      window.location.href = '/teacher/questions/create';
      return;
    }
    problemData = await response.json();

    document.getElementById('problemId').textContent = `#${problemData.id}`;
    document.getElementById('problemTitleInput').value = problemData.title || '';
    document.getElementById('problemDifficultyInput').value = problemData.difficulty || 'easy';
    document.getElementById('problemOrderInput').value = problemData.order || 1;
    document.getElementById('problemPointsInput').value = problemData.points || 10;
    document.getElementById('problemDescInput').value = problemData.description || '';
    document.getElementById('problemQuiz').textContent = problemData.quiz?.title || 'Not assigned';

    const py = variantFor('python');
    const c = variantFor('c');
    document.getElementById('pythonStarterInput').value = py.starter_code || '';
    document.getElementById('pythonSolutionInput').value = py.solution || '';
    document.getElementById('pythonExplanationInput').value = py.solution_explanation || '';
    document.getElementById('cStarterInput').value = c.starter_code || '';
    document.getElementById('cSolutionInput').value = c.solution || '';
    document.getElementById('cExplanationInput').value = c.solution_explanation || '';

    document.title = `Manage: ${problemData.title || 'Problem'} · Teacher`;
    renderTestCases(problemData.test_cases || []);
    updateTestCaseCount((problemData.test_cases || []).length);
  } catch (error) {
    console.error('Error loading problem:', error);
    alert('Error loading problem');
    window.location.href = '/teacher/questions/create';
  }
}

async function loadTestCases() {
  await loadProblemDetails();
}

function renderTestCases(testCases) {
  const container = document.getElementById('testCasesContainer');
  if (!testCases || testCases.length === 0) {
    showEmptyTestCases();
    return;
  }
  container.innerHTML = testCases.map((tc, index) => `
    <div class="testcase-item" data-tc-id="${tc.id}">
      <div class="testcase-item-header">
        <div class="testcase-item-title">
          <i class="bi bi-check2-square"></i>
          Test Case #${index + 1}
        </div>
        <div class="testcase-item-actions">
          <button class="btn btn-sm btn-outline-danger" data-delete-tc="${tc.id}" title="Delete">
            <i class="bi bi-trash"></i>
          </button>
        </div>
      </div>
      <div class="testcase-item-info">
        <div class="testcase-info-item">
          <span class="testcase-info-label">Visibility</span>
          <span class="testcase-info-value">
            <span class="badge ${tc.is_hidden ? 'bg-warning' : 'bg-success'}">${tc.is_hidden ? 'Hidden' : 'Public'}</span>
          </span>
        </div>
        <div class="testcase-info-item">
          <span class="testcase-info-label">Weight</span>
          <span class="testcase-info-value">${tc.weight || 1}</span>
        </div>
        <div class="testcase-info-item">
          <span class="testcase-info-label">ID</span>
          <span class="testcase-info-value">#${tc.id}</span>
        </div>
      </div>
      <div class="testcase-content">
        <div class="testcase-content-label">Input</div>
        <div class="testcase-content-value">${escapeHtml(tc.input || '(empty)')}</div>
      </div>
      <div class="testcase-content">
        <div class="testcase-content-label">Expected Output</div>
        <div class="testcase-content-value">${escapeHtml(tc.expected_output || '(empty)')}</div>
      </div>
    </div>
  `).join('');
}

function showEmptyTestCases() {
  document.getElementById('testCasesContainer').innerHTML = `
    <div class="empty-state">
      <i class="bi bi-inbox"></i>
      <div class="mt-2 text-muted">No test cases yet. Add your first test case!</div>
    </div>
  `;
}

function updateTestCaseCount(count) {
  document.getElementById('testCaseCount').textContent = `${count} test case${count !== 1 ? 's' : ''}`;
}

async function addTestCase(event) {
  event.preventDefault();
  let expectedOutput = document.getElementById('tcExpected').value;
  if (expectedOutput && !expectedOutput.endsWith('\n')) expectedOutput += '\n';

  const payload = {
    input: document.getElementById('tcInput').value,
    expected: expectedOutput,
    is_hidden: document.getElementById('tcHidden').value === 'true',
    weight: parseFloat(document.getElementById('tcWeight').value) || 1.0
  };

  try {
    showMessage('tcMsg', 'Adding test case...', true);
    const response = await authenticatedFetch(`${API_BASE}/problems/${problemId}/test-cases`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await response.json();
    if (!response.ok) {
      showMessage('tcMsg', 'Failed: ' + (data.message || 'Unknown error'), false);
      return;
    }
    showMessage('tcMsg', `Test case #${data.id} added successfully!`, true);
    document.getElementById('tcInput').value = '';
    document.getElementById('tcExpected').value = '';
    document.getElementById('tcHidden').value = 'false';
    document.getElementById('tcWeight').value = '1';
    await loadTestCases();
  } catch (error) {
    console.error('Error adding test case:', error);
    showMessage('tcMsg', 'Error adding test case', false);
  }
}

async function deleteTestCase(tcId) {
  if (!confirm(`Are you sure you want to delete test case #${tcId}?`)) return;
  try {
    const response = await authenticatedFetch(`${API_BASE}/test-cases/${tcId}`, { method: 'DELETE' });
    if (response.ok) {
      showMessage('tcMsg', 'Test case deleted successfully', true);
      await loadTestCases();
    } else {
      const data = await response.json();
      alert('Delete failed: ' + (data.message || 'Unknown error'));
    }
  } catch (error) {
    console.error('Error deleting test case:', error);
    alert('Error deleting test case');
  }
}

async function saveProblemUpdate() {
  const payload = {
    title: document.getElementById('problemTitleInput').value.trim(),
    description: document.getElementById('problemDescInput').value.trim(),
    difficulty: document.getElementById('problemDifficultyInput').value,
    order: parseInt(document.getElementById('problemOrderInput').value, 10) || 1,
    points: parseInt(document.getElementById('problemPointsInput').value, 10) || 10,
    python_starter_code: document.getElementById('pythonStarterInput').value,
    python_solution: document.getElementById('pythonSolutionInput').value,
    python_solution_explanation: document.getElementById('pythonExplanationInput').value,
    c_starter_code: document.getElementById('cStarterInput').value,
    c_solution: document.getElementById('cSolutionInput').value,
    c_solution_explanation: document.getElementById('cExplanationInput').value
  };

  if (!payload.title || !payload.description) {
    showMessage('problemMsg', 'Title and description are required', false);
    return;
  }

  try {
    const response = await authenticatedFetch(`${API_BASE}/problems/${problemId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await response.json();
    if (!response.ok) {
      showMessage('problemMsg', data.message || 'Failed to update problem', false);
      return;
    }
    problemData = data;
    showMessage('problemMsg', 'Problem updated successfully', true);
    await loadProblemDetails();
  } catch (error) {
    console.error('Error updating problem:', error);
    showMessage('problemMsg', 'Error updating problem', false);
  }
}

async function deleteProblem() {
  if (!confirm('Are you sure you want to delete this problem and all variants/test cases?')) return;
  if (!confirm('This action cannot be undone. Are you absolutely sure?')) return;
  try {
    const response = await authenticatedFetch(`${API_BASE}/problems/${problemId}`, { method: 'DELETE' });
    if (response.ok) {
      alert('Problem deleted successfully');
      window.location.href = '/teacher/questions/create';
    } else {
      const data = await response.json();
      alert('Delete failed: ' + (data.message || 'Unknown error'));
    }
  } catch (error) {
    console.error('Error deleting problem:', error);
    alert('Error deleting problem');
  }
}

document.addEventListener('DOMContentLoaded', async () => {
  problemId = getProblemIdFromUrl();
  if (!problemId) {
    alert('Invalid problem ID');
    window.location.href = '/teacher/questions/create';
    return;
  }

  await loadProblemDetails();
  document.getElementById('saveProblemBtn').addEventListener('click', saveProblemUpdate);
  document.getElementById('testCaseForm').addEventListener('submit', addTestCase);
  document.getElementById('addTcBtn').addEventListener('click', addTestCase);
  document.getElementById('clearTcBtn').addEventListener('click', () => {
    document.getElementById('tcInput').value = '';
    document.getElementById('tcExpected').value = '';
    document.getElementById('tcHidden').value = 'false';
    document.getElementById('tcWeight').value = '1';
    showMessage('tcMsg', 'Form cleared', true);
  });
  document.getElementById('refreshTestCases').addEventListener('click', loadTestCases);
  document.getElementById('deleteProblemBtn').addEventListener('click', deleteProblem);
  document.getElementById('testCasesContainer').addEventListener('click', event => {
    const deleteBtn = event.target.closest('[data-delete-tc]');
    if (deleteBtn) deleteTestCase(deleteBtn.getAttribute('data-delete-tc'));
  });
});

window.QuestionManage = {
  loadQuestionDetails: loadProblemDetails,
  loadTestCases,
  addTestCase,
  deleteTestCase,
  deleteQuestion: deleteProblem
};
