import { getToken, authenticatedFetch } from '/static/js/auth.js';

const API_BASE = '/api/v1';
const token = getToken();

if (!token) {
  window.location.href = '/auth/login?next=/teacher/profile';
}

let currentUserData = null;

// Load user info
async function loadUserInfo() {
  try {
    const response = await authenticatedFetch(`${API_BASE}/auth/me`);
    const data = await response.json();
    currentUserData = data;

    document.getElementById('t-name').textContent = data.username || 'Teacher';
    document.getElementById('t-username').textContent = data.username || '--';
    document.getElementById('t-email').textContent = data.email || '--';
    document.getElementById('t-role').textContent = (data.role || 'teacher').toUpperCase();

    // Update modal current values
    document.getElementById('current-email').textContent = data.email || '--';
    document.getElementById('current-username').textContent = data.username || '--';

    if (data.created_at) {
      const date = new Date(data.created_at);
      const createdElem = document.getElementById('t-created');
      if (createdElem) {
        createdElem.textContent = date.toLocaleDateString();
      }
    }
  } catch (error) {
  }
}

// Load statistics
async function loadStatistics() {
  try {
    const response = await authenticatedFetch(`${API_BASE}/teacher/stats`);
    const data = await response.json();

    if (!response.ok) {
      throw new Error(data?.message || 'Failed to load statistics');
    }

    document.getElementById('stat-questions').textContent = data.questions_count || 0;
    document.getElementById('stat-classrooms').textContent = data.classrooms_count || 0;
    document.getElementById('stat-students').textContent = data.students_count || 0;
    document.getElementById('stat-submissions').textContent = data.submissions_count || 0;
  } catch (error) {
    document.getElementById('stat-questions').textContent = '-';
    document.getElementById('stat-classrooms').textContent = '-';
    document.getElementById('stat-students').textContent = '-';
    document.getElementById('stat-submissions').textContent = '-';
  }
}

// Load recent questions
async function loadRecentQuestions() {
  const tbody = document.getElementById('recent-questions-tbody');
  
  try {
    const response = await authenticatedFetch(`${API_BASE}/questions/mine?limit=10`);
    const data = await response.json();

    if (!response.ok) {
      throw new Error(data?.message || 'Failed to load questions');
    }
    const items = data.items || [];

    if (!items.length) {
      tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted">No questions yet</td></tr>';
      return;
    }

    tbody.innerHTML = items.map(q => `
      <tr>
        <td><strong>#${q.id}</strong></td>
        <td>
        <span class="question-title" title="${q.title || 'Untitled'}">
          ${q.title || 'Untitled'}
        </span>
      </td>
        <td><span class="badge badge--language">${q.programming_language || 'N/A'}</span></td>
        <td><span class="badge bg-info">${q.difficulty || 'Medium'}</span></td>
        <td>

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
    `).join('');
  } catch (error) {
    tbody.innerHTML = '<tr><td colspan="5" class="text-center text-danger">Failed to load questions</td></tr>';
  }
}

// Delete question function
async function deleteQuestion(id) {
  if (!confirm('Are you sure you want to delete this question?')) {
    return;
  }

  try {
    const response = await authenticatedFetch(`${API_BASE}/questions/${id}`, {
      method: 'DELETE'
    });

    if (response.ok) {
      alert('Question deleted successfully!');
      await loadRecentQuestions();
    } else {
      const data = await response.json();
      alert(`Failed to delete: ${data.message || 'Unknown error'}`);
    }
  } catch (error) {
    alert('Failed to delete question');
  }
}

// Make stat cards clickable
document.querySelectorAll('.stat-card[data-href]').forEach(card => {
  card.style.cursor = 'pointer';
  card.addEventListener('click', () => {
    window.location.href = card.dataset.href;
  });
});

// Helper functions for showing messages
function showMessage(elementId, message, isError = false) {
  const errorDiv = document.getElementById(`${elementId}-error`);
  const successDiv = document.getElementById(`${elementId}-success`);
  
  if (isError) {
    errorDiv.textContent = message;
    errorDiv.classList.remove('d-none');
    successDiv.classList.add('d-none');
  } else {
    successDiv.textContent = message;
    successDiv.classList.remove('d-none');
    errorDiv.classList.add('d-none');
  }
}

function hideMessages(elementId) {
  document.getElementById(`${elementId}-error`).classList.add('d-none');
  document.getElementById(`${elementId}-success`).classList.add('d-none');
}

function setButtonLoading(buttonId, isLoading, originalText) {
  const btn = document.getElementById(buttonId);
  if (isLoading) {
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Saving...';
  } else {
    btn.disabled = false;
    btn.innerHTML = originalText;
  }
}

// Clear form on modal close
document.getElementById('editProfileModal').addEventListener('hidden.bs.modal', () => {
  // Clear all forms
  document.getElementById('email-form').reset();
  document.getElementById('username-form').reset();
  document.getElementById('password-form').reset();
  
  // Hide all messages
  hideMessages('email');
  hideMessages('username');
  hideMessages('password');
});

// Email Update Handler
document.getElementById('email-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  hideMessages('email');
  
  const originalBtnText = '<i class="bi bi-check-circle"></i> Update Email';
  setButtonLoading('email-submit-btn', true, originalBtnText);
  
  const email = document.getElementById('new-email').value.trim();

  try {
    // Check if email is the same as current
    if (email === currentUserData.email) {
      showMessage('email', 'New email is the same as current email', true);
      return;
    }

    const response = await authenticatedFetch(`${API_BASE}/profile/email`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email })
    });

    if (response.ok) {
      showMessage('email', 'Email updated successfully!', false);
      setTimeout(async () => {
        await loadUserInfo();
        document.getElementById('email-form').reset();
        hideMessages('email');
      }, 1500);
    } else {
      const data = await response.json();
      showMessage('email', data.message || 'Failed to update email', true);
    }
  } catch (error) {
    showMessage('email', 'Network error. Please try again.', true);
  } finally {
    setButtonLoading('email-submit-btn', false, originalBtnText);
  }
});

// Username Update Handler
document.getElementById('username-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  hideMessages('username');
  
  const originalBtnText = '<i class="bi bi-check-circle"></i> Update Username';
  setButtonLoading('username-submit-btn', true, originalBtnText);
  
  const new_username = document.getElementById('new-username').value.trim();
  const password = document.getElementById('username-password').value;

  try {
    // Validate
    if (new_username.length < 3) {
      showMessage('username', 'Username must be at least 3 characters', true);
      return;
    }

    if (new_username === currentUserData.username) {
      showMessage('username', 'New username is the same as current username', true);
      return;
    }

    const response = await authenticatedFetch(`${API_BASE}/profile/username`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ new_username, password })
    });

    if (response.ok) {
      showMessage('username', 'Username updated successfully! Redirecting to login...', false);
      setTimeout(() => {
        window.location.href = '/auth/login';
      }, 1500);
    } else {
      const data = await response.json();
      showMessage('username', data.message || 'Failed to update username', true);
    }
  } catch (error) {
    showMessage('username', 'Network error. Please try again.', true);
  } finally {
    setButtonLoading('username-submit-btn', false, originalBtnText);
  }
});

// Password Update Handler
document.getElementById('password-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  hideMessages('password');
  
  const originalBtnText = '<i class="bi bi-check-circle"></i> Update Password';
  setButtonLoading('password-submit-btn', true, originalBtnText);
  
  const current_password = document.getElementById('current-password').value;
  const new_password = document.getElementById('new-password').value;
  const confirm_password = document.getElementById('confirm-password').value;

  try {
    // Validate
    if (new_password !== confirm_password) {
      showMessage('password', 'New passwords do not match', true);
      return;
    }

    if (new_password.length < 6) {
      showMessage('password', 'New password must be at least 6 characters', true);
      return;
    }

    const response = await authenticatedFetch(`${API_BASE}/profile/password`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ current_password, new_password })
    });

    if (response.ok) {
      showMessage('password', 'Password updated successfully! Redirecting to login...', false);
      setTimeout(() => {
        window.location.href = '/auth/login';
      }, 1500);
    } else {
      const data = await response.json();
      showMessage('password', data.message || 'Failed to update password', true);
    }
  } catch (error) {
    showMessage('password', 'Network error. Please try again.', true);
  } finally {
    setButtonLoading('password-submit-btn', false, originalBtnText);
  }
});

// Initialize
document.addEventListener('DOMContentLoaded', async () => {
  await Promise.all([
    loadUserInfo(),
    loadStatistics(),
    loadRecentQuestions(),
  ]);

  const tbody = document.getElementById('recent-questions-tbody');
  if (!tbody) return;
  
  // Table action buttons
  tbody.addEventListener('click', (e) => {
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
