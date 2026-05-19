import { getToken, authenticatedFetch } from '/static/js/auth.js';

const API_BASE = '/api/v1';
const token = getToken();

if (!token) {
  window.location.href = '/auth/login?next=/student/profile';
}

let currentUserData = null;

async function loadUserInfo() {
  try {
    const response = await authenticatedFetch(`${API_BASE}/auth/me`);
    const data = await response.json();
    currentUserData = data;

    document.getElementById('sp-name').textContent = data.username || 'Student';
    document.getElementById('sp-username').textContent = data.username || '--';
    document.getElementById('sp-email').textContent = data.email || '--';
    document.getElementById('sp-role').textContent = (data.role || 'student').toUpperCase();

    // Update modal current values
    document.getElementById('current-email').textContent = data.email || '--';
    document.getElementById('current-username').textContent = data.username || '--';

    if (data.created_at) {
      const date = new Date(data.created_at);
      const createdElem = document.getElementById('sp-created');
      if (createdElem) {
        createdElem.textContent = date.toLocaleDateString();
      }
    }
  } catch (error) {
  }
}

async function loadSubmissions() {
  try {
    const response = await authenticatedFetch(`${API_BASE}/submissions/mine`);
    const data = await response.json();

    if (!response.ok) {
      throw new Error(data?.message || 'Failed to load submissions');
    }

    const items = data.items || [];

    updateStatistics(items);
    renderSubmissions(items.slice(0, 10));
  } catch (error) {
    document.getElementById('sp-tbody').innerHTML =
      `<tr><td colspan="6" class="text-center">
        <div class="empty-state">
          <i class="bi bi-exclamation-circle"></i>
          <p>Failed to load submissions</p>
        </div>
      </td></tr>`;
  }
}

function updateStatistics(items) {
  const total = items.length;
  const passed = items.filter(item => {
    const status = (item.status || '').toLowerCase();
    return status === 'completed' && (item.score || 0) >= 60;
  }).length;
  const failed = total - passed;
  const successRate = total > 0 ? Math.round((passed / total) * 100) : 0;

  document.getElementById('sp-total-submissions').textContent = total;
  document.getElementById('sp-passed').textContent = passed;
  document.getElementById('sp-failed').textContent = failed;
  document.getElementById('sp-success-rate').textContent = `${successRate}%`;
}

function formatQuestionTitle(item) {
  if (!item) return 'Question';
  if (item.question_title) return item.question_title;
  if (item.question_id) return `Question #${item.question_id}`;
  return 'Question';
}

function renderSubmissions(items) {
  const tbody = document.getElementById('sp-tbody');

  if (!items.length) {
    tbody.innerHTML = `
      <tr><td colspan="6" class="text-center">
        <div class="empty-state">
          <i class="bi bi-inbox"></i>
          <p>No submissions yet</p>
        </div>
      </td></tr>
    `;
    return;
  }

  tbody.innerHTML = '';

  items.forEach(item => {
    const status = (item.status || '').toLowerCase();
    const isPassed = status === 'completed' && (item.score || 0) >= 60;
    const badgeClass = isPassed ? 'badge bg-success' :
                      status === 'pending' ? 'badge bg-warning text-dark' : 
                      'badge bg-danger';
    const badgeLabel = isPassed ? 'Passed' :
                      status === 'pending' ? 'Pending' : 'Failed';

    const score = item.score !== null && item.score !== undefined ? item.score : 'N/A';
    const submittedAt = item.submitted_at
      ? new Date(item.submitted_at).toLocaleString()
      : 'N/A';

    const row = document.createElement('tr');
    row.innerHTML = `
      <td><strong>#${item.id}</strong></td>
      <td>
        <a href="/question/${item.question_id}" class="text-decoration-none">
          ${formatQuestionTitle(item)}
        </a>
      </td>
      <td><span class="${badgeClass}">${badgeLabel}</span></td>
      <td><strong>${score}</strong></td>
      <td>${submittedAt}</td>

      <td>
        <a href="/submissions/${item.id}" class="btn btn-sm btn-outline-primary">
          <i class="bi bi-eye"></i> View
        </a>
      </td>
      
    `;
    tbody.appendChild(row);
  });
}

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
  try {
    await loadUserInfo();
    await loadSubmissions();
  } catch (error) {
  }
});
