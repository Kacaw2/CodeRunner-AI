// ============================================================
// Grades Management - JavaScript Module (Fixed Filters)
// ============================================================

import { getToken, authenticatedFetch } from '/static/js/auth.js';

const API_BASE = '/api/v1';

// ============================================================
// Authentication Check
// ============================================================

const token = getToken();
if (!token) {
  window.location.href = '/auth/login?next=/teacher/grades';
}

// ============================================================
// State Management
// ============================================================

let currentPage = 0;
const pageSize = 20;
let totalSubmissions = 0;
let allStudents = []; // Store all students for filter
let allQuestions = []; // Store all problems for filter

// ============================================================
// Load Initial Data (for filters)
// ============================================================

async function loadInitialFilterData() {
  try {
    // Load all students for filter
    const studentsResponse = await authenticatedFetch(`${API_BASE}/grades/students/summary`);
    const studentsData = await studentsResponse.json();
    allStudents = studentsData.items || [];
    
    // Load all submissions once to get all unique problems
    const submissionsResponse = await authenticatedFetch(`${API_BASE}/grades/submissions?limit=1000`);
    const submissionsData = await submissionsResponse.json();
    const submissions = submissionsData.items || [];
    
    // Extract unique problems
    const questionMap = new Map();
    submissions.forEach(sub => {
      const id = sub.problem_id || sub.question_id;
      if (!questionMap.has(id)) {
        questionMap.set(id, sub.question_title || `Problem #${id}`);
      }
    });
    allQuestions = Array.from(questionMap.entries()).map(([id, title]) => ({ id, title }));
    
    // Populate filter dropdowns
    populateFilters();
    
  } catch (error) {
  }
}

// ============================================================
// Populate Filter Dropdowns
// ============================================================

function populateFilters() {
  // Populate student filter
  const studentFilter = document.getElementById('filterStudent');
  studentFilter.innerHTML = '<option value="">All Students</option>' +
    allStudents.map(s => `<option value="${s.student_id}">${s.student_name}</option>`).join('');
  
  // Populate problem filter
  const questionFilter = document.getElementById('filterQuestion');
  questionFilter.innerHTML = '<option value="">All Problems</option>' +
    allQuestions.map(q => `<option value="${q.id}">${q.title}</option>`).join('');
}

// ============================================================
// Load Summary Statistics
// ============================================================

async function loadStatistics() {
  try {
    const response = await authenticatedFetch(`${API_BASE}/grades/students/summary`);
    const data = await response.json();
    
    const students = data.items || [];
    
    document.getElementById('totalStudents').textContent = students.length;
    
    if (students.length > 0) {
      const totalSubs = students.reduce((sum, s) => sum + s.total_submissions, 0);
      const avgScore = students.reduce((sum, s) => sum + s.average_score, 0) / students.length;
      const completedSubs = students.reduce((sum, s) => sum + s.completed_count, 0);
      
      document.getElementById('totalSubmissions').textContent = totalSubs;
      document.getElementById('averageScore').textContent = avgScore.toFixed(1) + '%';
      
      if (totalSubs > 0) {
        document.getElementById('completionRate').textContent = 
          ((completedSubs / totalSubs) * 100).toFixed(1) + '%';
      } else {
        document.getElementById('completionRate').textContent = '0%';
      }
    } else {
      document.getElementById('totalSubmissions').textContent = '0';
      document.getElementById('averageScore').textContent = '0%';
      document.getElementById('completionRate').textContent = '0%';
    }
  } catch (error) {
  }
}

// ============================================================
// Load Student Summary
// ============================================================

async function loadStudentSummary() {
  const container = document.getElementById('studentSummaryContainer');
  
  try {
    const response = await authenticatedFetch(`${API_BASE}/grades/students/summary`);
    const data = await response.json();

    if (!response.ok) {
      throw new Error(data?.message || 'Failed to load student summary');
    }
    const students = data.items || [];
    
    if (!students.length) {
      container.innerHTML = '<p class="text-center text-muted">No student data available</p>';
      return;
    }
    
    container.innerHTML = students.map((student, index) => `
      <div class="student-summary-card card mb-3">
        <div class="card-body">
          <div class="row align-items-center">
            <div class="col-md-1 text-center">
              <div class="h4 mb-0 text-muted">#${index + 1}</div>
            </div>
            <div class="col-md-3">
              <h6 class="mb-1">${student.student_name}</h6>
              <small class="text-muted">${student.student_email}</small>
            </div>
            <div class="col-md-2 text-center">
              <div class="small text-muted">Submissions</div>
              <div class="h5 mb-0">${student.total_submissions}</div>
            </div>
            <div class="col-md-2 text-center">
              <div class="small text-muted">Average</div>
              <div class="h5 mb-0 text-primary">${student.average_score}%</div>
            </div>
            <div class="col-md-2 text-center">
              <div class="small text-muted">Highest</div>
              <div class="h5 mb-0 text-success">${student.highest_score}%</div>
            </div>
            <div class="col-md-2 text-center">
              <div class="small text-muted">Completed</div>
              <div class="h5 mb-0">${student.completed_count}/${student.total_submissions}</div>
            </div>
          </div>
        </div>
      </div>
    `).join('');
    
  } catch (error) {
    container.innerHTML = '<p class="text-center text-danger">Failed to load student summary</p>';
  }
}

// ============================================================
// Load Submissions (Fixed Layout)
// ============================================================

async function loadSubmissions() {
  const container = document.getElementById('submissionsCardsContainer');
  
  try {
    const studentId = document.getElementById('filterStudent').value;
    const questionId = document.getElementById('filterQuestion').value;
    const status = document.getElementById('filterStatus').value;
    
    let url = `${API_BASE}/grades/submissions?limit=${pageSize}&offset=${currentPage * pageSize}`;
    if (studentId) url += `&student_id=${studentId}`;
    if (questionId) url += `&problem_id=${questionId}`;
    if (status) url += `&status=${status}`;
    
    const response = await authenticatedFetch(url);
    const data = await response.json();

    if (!response.ok) {
      throw new Error(data?.message || 'Failed to load submissions');
    }
    
    const submissions = data.items || [];
    totalSubmissions = data.total || 0;
    
    if (!submissions.length) {
      container.innerHTML = `
        <div class="empty-state">
          <i class="bi bi-inbox"></i>
          <p>No submissions found</p>
        </div>
      `;
      updatePaginationInfo();
      return;
    }
    
    // Render submissions with fixed layout
    container.innerHTML = submissions.map(sub => {
      const status = (sub.status || '').toLowerCase();
      const isPassed = status === 'completed' && (sub.score || 0) >= 60;
      const statusClass = isPassed ? 'passed' : 
                          status === 'pending' ? 'pending' : 'failed';
      const statusLabel = isPassed ? 'Passed' :
                          status === 'pending' ? 'Pending' : 'Failed';
      
      const score = sub.score !== null && sub.score !== undefined ? sub.score : 'N/A';
      const submittedAt = sub.submitted_at
        ? new Date(sub.submitted_at).toLocaleString()
        : 'N/A';
      
      return `
        <div class="submission-item ${statusClass}">
          <div class="submission-header">
            <div class="submission-title-container">
              <div class="submission-question-title">
                <i class="bi bi-file-code"></i>
                ${sub.question_title || `Problem #${sub.problem_id || sub.question_id}`}
              </div>
              <div class="submission-student-info">
                <i class="bi bi-person"></i> ${sub.student_name}
                <span class="text-muted">• ${sub.student_email}</span>
              </div>
            </div>
            <div class="submission-status ${statusClass}">
              <i class="bi bi-${isPassed ? 'check-circle-fill' : status === 'pending' ? 'clock' : 'x-circle-fill'}"></i>
              ${statusLabel}
            </div>
          </div>
          <div class="submission-details">
            <div class="submission-detail">
              <div class="submission-detail-label">Submission ID</div>
              <div class="submission-detail-value">#${sub.id}</div>
            </div>
            <div class="submission-detail">
              <div class="submission-detail-label">Score</div>
              <div class="submission-detail-value">${score}${typeof score === 'number' ? '%' : ''}</div>
            </div>
            <div class="submission-detail">
              <div class="submission-detail-label">Submitted At</div>
              <div class="submission-detail-value">${submittedAt}</div>
            </div>
            <div class="submission-detail">
              <div class="submission-detail-label">Action</div>
              <div class="submission-detail-value">
                <a href="/submissions/${sub.id}" class="btn btn-sm btn-outline-primary" target="_blank">
                  <i class="bi bi-eye"></i> View Details
                </a>
              </div>
            </div>
          </div>
        </div>
      `;
    }).join('');
    
    updatePaginationInfo();
    
  } catch (error) {
    container.innerHTML = `
      <div class="empty-state">
        <i class="bi bi-exclamation-circle text-danger"></i>
        <p>Failed to load submissions</p>
      </div>
    `;
  }
}

// ============================================================
// Update Pagination Info
// ============================================================

function updatePaginationInfo() {
  const start = totalSubmissions > 0 ? currentPage * pageSize + 1 : 0;
  const end = Math.min((currentPage + 1) * pageSize, totalSubmissions);
  
  document.getElementById('paginationInfo').textContent = 
    `Showing ${start} - ${end} of ${totalSubmissions} submissions`;
  
  document.getElementById('prevPage').disabled = currentPage === 0;
  document.getElementById('nextPage').disabled = end >= totalSubmissions;
}

// ============================================================
// Export CSV
// ============================================================

async function exportCsv() {
  const btn = document.getElementById('exportCsvBtn');
  const originalText = btn.innerHTML;
  
  try {
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Exporting...';
    
    const response = await authenticatedFetch(`${API_BASE}/grades/export/csv`);
    
    if (!response.ok) {
      const text = await response.text();
      throw new Error(text || 'Failed to export CSV. Please try again.');
    }

    const blob = await response.blob();
    
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `grade_report_${new Date().toISOString().split('T')[0]}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    window.URL.revokeObjectURL(url);
    
    btn.innerHTML = '<i class="bi bi-check-circle"></i> Exported!';
    setTimeout(() => {
      btn.innerHTML = originalText;
      btn.disabled = false;
    }, 2000);
    
  } catch (error) {
    alert('Failed to export CSV. Please try again.');
    btn.innerHTML = originalText;
    btn.disabled = false;
  }
}

// ============================================================
// Event Listeners
// ============================================================

document.getElementById('exportCsvBtn').addEventListener('click', exportCsv);

document.getElementById('applyFilters').addEventListener('click', () => {
  currentPage = 0;
  loadSubmissions();
});

document.getElementById('clearFilters').addEventListener('click', () => {
  document.getElementById('filterStudent').value = '';
  document.getElementById('filterQuestion').value = '';
  document.getElementById('filterStatus').value = '';
  currentPage = 0;
  loadSubmissions();
});

document.getElementById('prevPage').addEventListener('click', () => {
  if (currentPage > 0) {
    currentPage--;
    loadSubmissions();
  }
});

document.getElementById('nextPage').addEventListener('click', () => {
  if ((currentPage + 1) * pageSize < totalSubmissions) {
    currentPage++;
    loadSubmissions();
  }
});

// ============================================================
// Initialize
// ============================================================

document.addEventListener('DOMContentLoaded', async () => {
  try {
    // Load filter data first
    await loadInitialFilterData();
    
    // Then load all other data
    await Promise.all([
      loadStatistics(),
      loadStudentSummary(),
      loadSubmissions()
    ]);
  } catch (error) {
  }
});
