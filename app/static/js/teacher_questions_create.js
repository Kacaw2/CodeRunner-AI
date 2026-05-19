// ==========================================================================
// Question Workspace - JavaScript (Updated with Filter)
// ==========================================================================

import { getToken, authenticatedFetch } from '/static/js/auth.js';

const API_BASE = '/api/v1';
let allQuestions = []; // Store all questions for filtering
let currentQuizId = null;
let showOnlyMyQuestions = false; 

// ==========================================================================
// Authentication Check
// ==========================================================================

const token = getToken();
if (!token) {
  window.location.href = '/auth/login?next=/teacher/questions/create';
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

// ==========================================================================
// Quiz Management
// ==========================================================================

async function loadQuizzes() {
  try {
    const response = await authenticatedFetch(`${API_BASE}/quizzes`);
    const data = await response.json();
    
    console.info('Quizzes loaded:', data);
    
    if (response.ok) {
      const quizSelect = document.getElementById('quizSelect');
      const qQuizSelect = document.getElementById('qQuizSelect');
      
      // Handle both array and object with items property
      const quizzes = Array.isArray(data) ? data : (data.items || []);
      
      // Update both dropdowns
      const quizOptions = quizzes.map(q => 
        `<option value="${q.id}">${q.title}</option>`
      ).join('');
      
      quizSelect.innerHTML = '<option value="">-- All Questions --</option>' + quizOptions;
      qQuizSelect.innerHTML = '<option value="">-- No Quiz --</option>' + quizOptions;
      
    } else {
      console.error('Failed to load quizzes:', data.message);
    }
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
      body: JSON.stringify({ 
        title,
        description: description || '',
        is_published: false
      })
    });
    
    const data = await response.json();
    
    if (response.ok) {
      // Close modal
      const modal = window.bootstrap.Modal.getInstance(
        document.getElementById('createQuizModal')
      );
      modal.hide();
      
      // Clear form
      document.getElementById('createQuizTitle').value = '';
      document.getElementById('createQuizDescription').value = '';
      
      // Reload quiz dropdowns
      await loadQuizzes();
      
      // Auto-select the new quiz
      document.getElementById('quizSelect').value = data.id;
      document.getElementById('qQuizSelect').value = data.id;
      
      // Load questions for the new quiz
      await loadQuestions(data.id);
      
      showMessage('msg', `Quiz "${title}" created successfully!`, true);
      
    } else {
      showMessage('createQuizMsg', data.message || 'Failed to create quiz', false);
    }
  } catch (error) {
    console.error('Error creating quiz:', error);
    showMessage('createQuizMsg', 'Error creating quiz', false);
  }
}

// ==========================================================================
// Question Management (Updated with Filter Support)
// ==========================================================================

async function loadQuestions(quizId = null) {
  try {
    currentQuizId = quizId;
    
    // Use the teacher questions endpoint
    let url = `${API_BASE}/teacher/questions`;
    
    // Build query parameters
    const params = new URLSearchParams();
    
    //  If quiz_id is provided, add it (takes priority)
    if (quizId) {
      params.append('quiz_id', quizId);
    } 
    //  Otherwise, apply the "created_by_me" filter if enabled
    else if (showOnlyMyQuestions) {
      params.append('created_by_me', 'true');
    }
    
    if (params.toString()) {
      url += `?${params.toString()}`;
    }
    
    console.info('Loading questions from:', url);
    
    const response = await authenticatedFetch(url);
    const data = await response.json();

    if (response.ok) {
      // Handle both array and object with items property
      let questions = Array.isArray(data) ? data : (data.items || []);
      allQuestions = questions;
      renderQuestions(questions);
      updateQuestionCount(questions.length);
      
      //  Update filter badge
      updateFilterBadge();
    } else {
      console.error('Failed to load questions:', data.message);
      showEmptyState('Failed to load questions');
    }
  } catch (error) {
    console.error('Error loading questions:', error);
    showEmptyState('Error loading questions');
  }
}

function renderQuestions(questions) {
  const tbody = document.getElementById('qTableBody');
  
  if (!questions || questions.length === 0) {
    showEmptyState(currentQuizId ? 'No questions in this quiz yet' : 'No questions yet. Create your first question!');
    return;
  }
  
  tbody.innerHTML = questions.map(q => {
    // Improved creator display
    let creatorDisplay = '';
    let creatorClass = '';
    if (q.creator) {
      if (q.creator.name === 'Legacy Question') {
        creatorDisplay = q.creator.name;
        creatorClass = 'bg-creator';
      } else {
        creatorDisplay = escapeHtml(q.creator.name);
        creatorClass = 'bg-creator';
      }
    } else {
      creatorDisplay = 'Unknown';
      creatorClass = 'bg-secondary';
    }
    
    return `
    <tr data-question-id="${q.id}">
      <td>
        <span class="question-id">#${q.id}</span>
      </td>
      <td>
        <span class="question-title" title="${escapeHtml(q.title)}">
          ${escapeHtml(q.title)}
        </span>
      </td>
      <td class="text-center">
        <span class="badge ${creatorClass}">
          ${creatorDisplay}
        </span>
      </td>
      <td class="text-center">
        <span class="badge bg-info">
          ${(q.programming_language || 'c').toUpperCase()}
        </span>
      </td>
      <td class="text-center">
        <span class="badge ${q.test_case_count > 0 ? 'bg-success' : 'bg-secondary'}">
          ${q.test_case_count || 0}
        </span>
      </td>
      <td class="text-center">
        <div class="btn-group-actions">
          <a href="/question/${q.id}" 
             target="_blank" 
             class="btn btn-outline-primary btn-sm btn-action"
             title="View question">
            <i class="bi bi-eye"></i>
          </a>
          <button class="btn btn-outline-success btn-sm btn-action" 
                  data-manage="${q.id}"
                  title="Manage test cases">
            <i class="bi bi-gear"></i>
          </button>
          <button class="btn btn-outline-danger btn-sm btn-action" 
                  data-delete="${q.id}"
                  title="Delete question">
            <i class="bi bi-trash"></i>
          </button>
        </div>
      </td>
    </tr>
  `;
  }).join('');
}

function showEmptyState(message) {
  const tbody = document.getElementById('qTableBody');
  tbody.innerHTML = `
    <tr>
      <td colspan="6" class="text-center py-5">
        <div class="empty-state">
          <i class="bi bi-inbox"></i>
          <div class="mt-2 text-muted">${message}</div>
        </div>
      </td>
    </tr>
  `;
}

function updateQuestionCount(count) {
  const badge = document.getElementById('questionCount');
  badge.textContent = `${count} question${count !== 1 ? 's' : ''}`;
}

//  Update filter badge
function updateFilterBadge() {
  const filterBadge = document.getElementById('filterBadge');
  if (!filterBadge) return;
  
  if (currentQuizId) {
    filterBadge.textContent = 'Quiz Filter Active';
    filterBadge.className = 'badge bg-primary ms-2';
  } else if (showOnlyMyQuestions) {
    filterBadge.textContent = 'My Questions Only';
    filterBadge.className = 'badge bg-success ms-2';
  } else {
    filterBadge.textContent = 'All Questions';
    filterBadge.className = 'badge bg-secondary ms-2';
  }
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

async function createQuestion(event) {
  event.preventDefault();
  
  const title = document.getElementById('qTitle').value.trim();
  const description = document.getElementById('qDesc').value.trim();
  
  if (!title || !description) {
    showMessage('msg', 'Title and description are required', false);
    return;
  }
  
  const quizId = document.getElementById('qQuizSelect').value;
  
  const payload = {
    title,
    description,
    programming_language: document.getElementById('qLang').value,
    order: parseInt(document.getElementById('qOrder').value) || 1,
    starter_code: document.getElementById('qStarter').value || ''
  };
  
  // Only add quiz_id if a quiz is actually selected (not empty string or null)
  if (quizId && quizId !== '' && quizId !== 'null') {
    payload.quiz_id = parseInt(quizId);
  }
  
  console.info('Creating question with payload:', payload);
  
  try {
    showMessage('msg', 'Creating question...', true);
    
    const response = await authenticatedFetch(`${API_BASE}/questions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    
    const data = await response.json();
    
    if (response.ok) {
      showMessage('msg', `✓ Question "${title}" created successfully!`, true);
      
      // Clear form
      document.getElementById('qTitle').value = '';
      document.getElementById('qDesc').value = '';
      document.getElementById('qStarter').value = '';
      document.getElementById('qOrder').value = '1';
      
      // Reload questions (maintain current filter)
      await loadQuestions(currentQuizId);
      
      // Show success indicator
      highlightNewQuestion(data.id);
      
    } else {
      console.error('Failed to create question:', data);
      showMessage('msg', data.message || 'Failed to create question', false);
    }
  } catch (error) {
    console.error('Error creating question:', error);
    showMessage('msg', 'Error creating question', false);
  }
}

function highlightNewQuestion(questionId) {
  setTimeout(() => {
    const row = document.querySelector(`tr[data-question-id="${questionId}"]`);
    if (row) {
      row.scrollIntoView({ behavior: 'smooth', block: 'center' });
      row.style.backgroundColor = '#dbeafe';
      setTimeout(() => {
        row.style.backgroundColor = '';
      }, 2000);
    }
  }, 300);
}

async function deleteQuestion(id) {
  if (!confirm(`Are you sure you want to delete question #${id}?\n\nThis will also delete all associated test cases.`)) {
    return;
  }
  
  try {
    const response = await authenticatedFetch(`${API_BASE}/questions/${id}`, {
      method: 'DELETE'
    });
    
    if (response.ok) {
      showMessage('msg', '✓ Question deleted successfully', true);
      await loadQuestions(currentQuizId);
    } else {
      const data = await response.json();
      alert('Delete failed: ' + (data.message || 'Unknown error'));
    }
  } catch (error) {
    console.error('Error deleting question:', error);
    alert('Error deleting question');
  }
}

// ==========================================================================
// Search & Filter 
// ==========================================================================

function filterQuestions(searchTerm) {
  const term = searchTerm.toLowerCase().trim();
  console.info(allQuestions);
  if (!term) {
    renderQuestions(allQuestions);
    updateQuestionCount(allQuestions.length);
    return;
  }
  
  const filtered = allQuestions.filter(q => {
    const matchesId = q.id.toString().includes(term);
    const matchesTitle = q.title.toLowerCase().includes(term);
    const matchesCreator = q.creator && q.creator.name.toLowerCase().includes(term);
    return matchesId || matchesTitle || matchesCreator;
  });
  
  renderQuestions(filtered);
  updateQuestionCount(filtered.length);
}

// New: Toggle filter
function toggleCreatorFilter() {
  showOnlyMyQuestions = !showOnlyMyQuestions;
  
  // Update button state
  const btn = document.getElementById('creatorFilterBtn');
  if (btn) {
    if (showOnlyMyQuestions) {
      btn.classList.add('active');
      btn.innerHTML = '<i class="bi bi-funnel-fill"></i> My Questions';
    } else {
      btn.classList.remove('active');
      btn.innerHTML = '<i class="bi bi-funnel"></i> All Questions';
    }
  }
  
  // Reload questions with new filter
  loadQuestions(currentQuizId);
}

// Debounce function for search
function debounce(func, wait) {
  let timeout;
  return function executedFunction(...args) {
    const later = () => {
      clearTimeout(timeout);
      func(...args);
    };
    clearTimeout(timeout);
    timeout = setTimeout(later, wait);
  };
}

// ==========================================================================
// Event Listeners
// ==========================================================================

document.addEventListener('DOMContentLoaded', async () => {
  // Load initial data
  await loadQuizzes();
  await loadQuestions(); // Load all questions initially
  
  // Quiz management
  document.getElementById('refreshQuiz').addEventListener('click', loadQuizzes);
  
  // Create quiz button - open modal
  document.getElementById('createQuizBtn').addEventListener('click', () => {
    const modal = new window.bootstrap.Modal(
      document.getElementById('createQuizModal')
    );
    modal.show();
  });
  
  // Save quiz button in modal
  document.getElementById('saveCreateQuizBtn').addEventListener('click', createQuiz);
  
  // Quiz selection change
  document.getElementById('quizSelect').addEventListener('change', (e) => {
    const quizId = e.target.value || null;
    loadQuestions(quizId);
  });
  
  // Creator filter button
  const creatorFilterBtn = document.getElementById('creatorFilterBtn');
  if (creatorFilterBtn) {
    creatorFilterBtn.addEventListener('click', toggleCreatorFilter);
  }
  
  // Question creation
  document.getElementById('questionForm').addEventListener('submit', createQuestion);
  document.getElementById('createBtn').addEventListener('click', createQuestion);
  
  // Search functionality
  const searchInput = document.getElementById('searchInput');
  const debouncedSearch = debounce((e) => {
    filterQuestions(e.target.value);
  }, 300);
  searchInput.addEventListener('input', debouncedSearch);
  
  // Table action buttons
  document.getElementById('qTableBody').addEventListener('click', (e) => {
    // Delete button
    const deleteBtn = e.target.closest('[data-delete]');
    if (deleteBtn) {
      const id = deleteBtn.getAttribute('data-delete');
      deleteQuestion(id);
      return;
    }
    
    // Manage button - navigate to question management page
    const manageBtn = e.target.closest('[data-manage]');
    if (manageBtn) {
      const id = manageBtn.getAttribute('data-manage');
      window.location.href = `/teacher/questions/${id}/manage`;
      return;
    }
    
  });
});

// ==========================================================================
// Export for external use (if needed)
// ==========================================================================
window.QuestionWorkspace = {
  loadQuestions,
  loadQuizzes,
  createQuestion,
  createQuiz,
  toggleCreatorFilter
};
