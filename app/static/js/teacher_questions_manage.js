// ==========================================================================
// Question Management - JavaScript
// ==========================================================================

import { getToken, authenticatedFetch } from '/static/js/auth.js';

const API_BASE = '/api/v1';
let questionId = null;
let questionData = null; // Store current question data
let isEditMode = false;

// ==========================================================================
// Authentication Check
// ==========================================================================

const token = getToken();
if (!token) {
  window.location.href = '/auth/login?next=' + window.location.pathname;
}

// ==========================================================================
// Utility Functions
// ==========================================================================

function showMessage(elementId, message, isSuccess) {
  const el = document.getElementById(elementId);
  if (!el) return;
  
  el.textContent = message;
  el.className = isSuccess ? 'success-msg' : 'error-msg';
  
  // Auto-clear after 5 seconds
  setTimeout(() => {
    el.textContent = '';
    el.className = '';
  }, 5000);
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// Get question ID from URL
function getQuestionIdFromUrl() {
  const pathParts = window.location.pathname.split('/');
  const manageIndex = pathParts.indexOf('questions');
  if (manageIndex !== -1 && pathParts[manageIndex + 1]) {
    return parseInt(pathParts[manageIndex + 1]);
  }
  return null;
}

// ==========================================================================
// Load Question Details
// ==========================================================================

async function loadQuestionDetails() {
  try {
    const response = await authenticatedFetch(`${API_BASE}/questions/${questionId}/detail`);
    
    if (!response.ok) {
      const data = await response.json();
      alert('Failed to load question: ' + (data.message || 'Unknown error'));
      window.location.href = '/teacher/questions/create';
      return;
    }
    
    const data = await response.json();
    
    // Store question data
    questionData = data;
    
    // Update question details in view mode
    document.getElementById('questionId').textContent = `#${data.id}`;
    document.getElementById('questionTitle').textContent = data.title || 'Untitled';
    document.getElementById('questionLang').textContent = (data.programming_language || 'c').toUpperCase();
    document.getElementById('questionOrder').textContent = data.order || '-';
    document.getElementById('questionDesc').textContent = data.description || 'No description';
    document.getElementById('questionStarter').textContent = data.starter_code || 'No starter code';
    
    // Update form inputs with current values
    document.getElementById('questionTitleInput').value = data.title || '';
    document.getElementById('questionLangInput').value = data.programming_language || 'c';
    document.getElementById('questionOrderInput').value = data.order || 1;
    document.getElementById('questionDescInput').value = data.description || '';
    document.getElementById('questionStarterInput').value = data.starter_code || '';
    
    // Update quiz info if available
    if (data.quiz) {
      document.getElementById('questionQuiz').textContent = data.quiz.title;
    } else {
      document.getElementById('questionQuiz').textContent = 'Not assigned';
    }
    
    // Update page title
    document.title = `Manage: ${data.title} · Teacher`;
    
    // Load test cases from the response
    if (data.test_cases && data.test_cases.length > 0) {
      renderTestCases(data.test_cases);
      updateTestCaseCount(data.test_cases.length);
    } else {
      // If no test_cases field or empty, show empty state
      showEmptyTestCases();
      updateTestCaseCount(0);
    }
    
  } catch (error) {
    alert('Error loading question');
    window.location.href = '/teacher/questions/create';
  }
}

// ==========================================================================
// Load Test Cases
// ==========================================================================

async function loadTestCases() {
  try {
    // Re-fetch question details to get updated test cases
    const response = await authenticatedFetch(`${API_BASE}/questions/${questionId}/detail`);
    
    if (!response.ok) {
      showEmptyTestCases();
      updateTestCaseCount(0);
      return;
    }
    
    const data = await response.json();
    
    if (data.test_cases && data.test_cases.length > 0) {
      renderTestCases(data.test_cases);
      updateTestCaseCount(data.test_cases.length);
    } else {
      showEmptyTestCases();
      updateTestCaseCount(0);
    }
  } catch (error) {
    showEmptyTestCases();
    updateTestCaseCount(0);
  }
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
            <span class="badge ${tc.is_hidden ? 'bg-warning' : 'bg-success'}">
              ${tc.is_hidden ? 'Hidden' : 'Public'}
            </span>
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
  const container = document.getElementById('testCasesContainer');
  container.innerHTML = `
    <div class="empty-state">
      <i class="bi bi-inbox"></i>
      <div class="mt-2 text-muted">No test cases yet. Add your first test case!</div>
    </div>
  `;
}

function updateTestCaseCount(count) {
  const badge = document.getElementById('testCaseCount');
  badge.textContent = `${count} test case${count !== 1 ? 's' : ''}`;
}

// ==========================================================================
// Add Test Case
// ==========================================================================

async function addTestCase(event) {
  event.preventDefault();
  
  let expectedOutput = document.getElementById('tcExpected').value;
  
  // Auto-add trailing newline if missing
  if (expectedOutput && !expectedOutput.endsWith('\n')) {
    expectedOutput += '\n';
  }
  
  const payload = {
    input: document.getElementById('tcInput').value,
    expected: expectedOutput,
    is_hidden: document.getElementById('tcHidden').value === 'true',
    weight: parseFloat(document.getElementById('tcWeight').value) || 1.0
  };
  
  try {
    showMessage('tcMsg', 'Adding test case...', true);
    
    const response = await authenticatedFetch(`${API_BASE}/questions/${questionId}/test-cases`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    
    const data = await response.json();
    
    if (response.ok) {
      showMessage('tcMsg', `✓ Test case #${data.id} added successfully!`, true);
      
      // Clear form
      document.getElementById('tcInput').value = '';
      document.getElementById('tcExpected').value = '';
      document.getElementById('tcHidden').value = 'false';
      document.getElementById('tcWeight').value = '1';
      
      // Reload test cases
      await loadTestCases();
      
    } else {
      showMessage('tcMsg', 'Failed: ' + (data.message || 'Unknown error'), false);
    }
  } catch (error) {
    showMessage('tcMsg', 'Error adding test case', false);
  }
}

// ==========================================================================
// Delete Test Case
// ==========================================================================

async function deleteTestCase(tcId) {
  if (!confirm(`Are you sure you want to delete test case #${tcId}?`)) {
    return;
  }
  
  try {
    const response = await authenticatedFetch(`${API_BASE}/test-cases/${tcId}`, {
      method: 'DELETE'
    });
    
    if (response.ok) {
      showMessage('tcMsg', '✓ Test case deleted successfully', true);
      await loadTestCases();
    } else {
      const data = await response.json();
      alert('Delete failed: ' + (data.message || 'Unknown error'));
    }
  } catch (error) {
    alert('Error deleting test case');
  }
}

// ==========================================================================
// Delete Question
// ==========================================================================

async function deleteQuestion() {
  if (!confirm(`Are you sure you want to delete this question?\n\nThis will also delete all ${document.getElementById('testCaseCount').textContent}.`)) {
    return;
  }
  
  // Double confirmation for safety
  if (!confirm('This action cannot be undone. Are you absolutely sure?')) {
    return;
  }
  
  try {
    const response = await authenticatedFetch(`${API_BASE}/questions/${questionId}`, {
      method: 'DELETE'
    });
    
    if (response.ok) {
      alert('✓ Question deleted successfully');
      window.location.href = '/teacher/questions/create';
    } else {
      const data = await response.json();
      alert('Delete failed: ' + (data.message || 'Unknown error'));
    }
  } catch (error) {
    alert('Error deleting question');
  }
}

// ==========================================================================
// Edit Mode Management
// ==========================================================================

function toggleEditMode() {
  isEditMode = !isEditMode;
  const detailCard = document.querySelector('.detail-card .card-body');
  const editBtn = document.getElementById('editQuestionBtn');
  const saveBtn = document.getElementById('saveQuestionBtn');
  const cancelBtn = document.getElementById('cancelEditBtn');
  
  if (isEditMode) {
    // Enter edit mode
    detailCard.classList.add('edit-mode');
    editBtn.classList.add('d-none');
    saveBtn.classList.remove('d-none');
    cancelBtn.classList.remove('d-none');
  } else {
    // Exit edit mode
    detailCard.classList.remove('edit-mode');
    editBtn.classList.remove('d-none');
    saveBtn.classList.add('d-none');
    cancelBtn.classList.add('d-none');
  }
}

function cancelEdit() {
  // Restore original values
  if (questionData) {
    document.getElementById('questionTitleInput').value = questionData.title || '';
    document.getElementById('questionLangInput').value = questionData.programming_language || 'c';
    document.getElementById('questionOrderInput').value = questionData.order || 1;
    document.getElementById('questionDescInput').value = questionData.description || '';
    document.getElementById('questionStarterInput').value = questionData.starter_code || '';
  }
  toggleEditMode();
}

async function saveQuestionUpdate() {
  // Get updated values
  const updatedData = {
    title: document.getElementById('questionTitleInput').value.trim(),
    programming_language: document.getElementById('questionLangInput').value,
    order: parseInt(document.getElementById('questionOrderInput').value) || 1,
    description: document.getElementById('questionDescInput').value.trim(),
    starter_code: document.getElementById('questionStarterInput').value
  };
  
  // Validate
  if (!updatedData.title) {
    alert('Title is required');
    return;
  }
  
  if (!updatedData.description) {
    alert('Description is required');
    return;
  }
  
  try {
    const response = await authenticatedFetch(`${API_BASE}/questions/${questionId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updatedData)
    });
    
    if (!response.ok) {
      const data = await response.json();
      alert('Failed to update: ' + (data.message || 'Unknown error'));
      return;
    }
    
    const data = await response.json();
    
    // Update successful
    alert('✓ Question updated successfully');
    toggleEditMode();
    // Reload question details
    await loadQuestionDetails();
    
  } catch (error) {
    alert('Error updating question');
  }
}

// ==========================================================================
// Event Listeners
// ==========================================================================

document.addEventListener('DOMContentLoaded', async () => {
  // Get question ID from URL
  questionId = getQuestionIdFromUrl();
  
  if (!questionId) {
    alert('Invalid question ID');
    window.location.href = '/teacher/questions/create';
    return;
  }
  
  // Load data (loadQuestionDetails now loads test cases too)
  await loadQuestionDetails();
  
  // Edit mode buttons
  document.getElementById('editQuestionBtn').addEventListener('click', toggleEditMode);
  document.getElementById('saveQuestionBtn').addEventListener('click', saveQuestionUpdate);
  document.getElementById('cancelEditBtn').addEventListener('click', cancelEdit);
  
  // Test case form
  document.getElementById('testCaseForm').addEventListener('submit', addTestCase);
  document.getElementById('addTcBtn').addEventListener('click', addTestCase);
  
  // Clear test case form
  document.getElementById('clearTcBtn').addEventListener('click', () => {
    document.getElementById('tcInput').value = '';
    document.getElementById('tcExpected').value = '';
    document.getElementById('tcHidden').value = 'false';
    document.getElementById('tcWeight').value = '1';
    showMessage('tcMsg', 'Form cleared', true);
  });
  
  // Refresh test cases
  document.getElementById('refreshTestCases').addEventListener('click', loadTestCases);
  
  // Delete question
  document.getElementById('deleteQuestionBtn').addEventListener('click', deleteQuestion);
  
  // Test case actions (event delegation)
  document.getElementById('testCasesContainer').addEventListener('click', (e) => {
    const deleteBtn = e.target.closest('[data-delete-tc]');
    if (deleteBtn) {
      const tcId = deleteBtn.getAttribute('data-delete-tc');
      deleteTestCase(tcId);
    }
  });
});

// ==========================================================================
// Export for external use (if needed)
// ==========================================================================
window.QuestionManage = {
  loadQuestionDetails,
  loadTestCases,
  addTestCase,
  deleteTestCase,
  deleteQuestion
};
