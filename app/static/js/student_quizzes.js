import { authenticatedFetch } from '/static/js/auth.js';

const API_BASE = '/api/v1/quizzes';
let currentView = 'list'; // 'list' or 'detail'

/**
 * HTML escape function to prevent XSS attacks
 */
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

/**
 * Format date string
 */
function formatDate(dateString) {
    if (!dateString) return 'No deadline';
    const date = new Date(dateString);
    const now = new Date();
    const isOverdue = date < now;
    
    const formatted = date.toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
        year: date.getFullYear() !== now.getFullYear() ? 'numeric' : undefined
    });
    
    return isOverdue ? `<span class="text-danger">${formatted} (Overdue)</span>` : formatted;
}

/**
 * Get status badge HTML
 * Handles both list view (with 'attempt') and detail view (with 'progress')
 */
function getStatusBadge(quiz) {
    // Check if overdue and not completed
    if (quiz.is_overdue) {
        // Check completion status from either attempt or progress
        const isCompleted = (quiz.attempt && quiz.attempt.status === 'completed') ||
                           (quiz.progress && quiz.progress.completed_questions === quiz.progress.total_questions);
        
        if (!isCompleted) {
            return '<span class="quiz-badge badge-overdue">Overdue</span>';
        }
    }
    
    // Check for 'attempt' (list view format)
    if (quiz.attempt) {
        if (quiz.attempt.status === 'completed') {
            return '<span class="quiz-badge badge-completed">✓ Completed</span>';
        }
        return '<span class="quiz-badge badge-in-progress">In Progress</span>';
    }
    
    // Check for 'progress' (detail view format)
    if (quiz.progress) {
        const { completed_questions, total_questions } = quiz.progress;
        
        if (completed_questions === total_questions && total_questions > 0) {
            return '<span class="quiz-badge badge-completed">✓ Completed</span>';
        } else if (completed_questions > 0) {
            return '<span class="quiz-badge badge-in-progress">In Progress</span>';
        }
    }
    
    // Default: Not started
    return '<span class="quiz-badge badge-pending">Not Started</span>';
}

/**
 * Check if error is authentication-related
 */
function isAuthError(error) {
    return error.message && (
        error.message.includes('authentication') ||
        error.message.includes('token') ||
        error.message.includes('401') ||
        error.message.toLowerCase().includes('unauthorized')
    );
}

/**
 * Display authentication required message
 */
function showAuthRequired(container) {
    container.innerHTML = `
        <div class="col-12">
            <div class="alert alert-warning text-center py-5" role="alert" style="background-color: #f8fafc; border-color: #e2e8f0;">
                <i class="bi bi-lock" style="font-size: 3rem; color: #64748b;"></i>
                <h4 class="mt-3 mb-2" style="color: #1e293b;">Authentication Required</h4>
                <p class="mb-3" style="color: #475569;">You need to log in to view your quizzes.</p>
                <a href="/auth/login?next=${encodeURIComponent(window.location.pathname)}" class="btn btn-primary">
                    <i class="bi bi-box-arrow-in-right"></i> Log In
                </a>
            </div>
        </div>
    `;
}

/**
 * Display generic error message
 */
function showErrorMessage(container, message) {
    container.innerHTML = `
        <div class="col-12">
            <div class="alert alert-danger text-center py-5" role="alert">
                <i class="bi bi-exclamation-triangle" style="font-size: 3rem; color: #dc3545;"></i>
                <h4 class="mt-3 mb-2">Error</h4>
                <p class="mb-3">${escapeHtml(message)}</p>
                <button class="btn btn-primary" onclick="location.reload()">
                    <i class="bi bi-arrow-clockwise"></i> Try Again
                </button>
            </div>
        </div>
    `;
}

/**
 * Load quiz list
 */
async function loadQuizzes() {
    const container = document.getElementById('quiz-list');
    
    try {
        const response = await authenticatedFetch(`${API_BASE}/`);
        const data = await response.json();

        if (!response.ok) {
            throw new Error(data?.message || 'Failed to load quizzes.');
        }
        
        container.innerHTML = '';
        const quizzes = data.items || [];

        if (quizzes.length === 0) {
            container.innerHTML = `
                <div class="col-12 text-center py-5">
                    <i class="bi bi-inbox" style="font-size: 3rem; color: #adb5bd;"></i>
                    <p class="text-muted mt-3">No quizzes assigned yet</p>
                </div>
            `;
            return;
        }

        quizzes.forEach(quiz => {
            const statusBadge = getStatusBadge(quiz);
            const col = document.createElement('div');
            col.className = 'col-12 col-md-6 col-lg-4';
            col.innerHTML = `
                <div class="quiz-card">
                    <div class="d-flex justify-content-between align-items-start mb-2">
                        <h5 class="mb-0">${escapeHtml(quiz.title)}</h5>
                        ${statusBadge}
                    </div>
                    <small class="text-muted d-block mb-3">
                        <i class="bi bi-building"></i> ${escapeHtml(quiz.classroom?.name || 'Unknown')}
                    </small>
                    
                    <div class="mb-3">
                        <div class="quiz-progress">
                            <div class="quiz-progress-bar" style="width: ${quiz.progress_percentage}%"></div>
                        </div>
                        <small class="text-muted">
                            ${quiz.completed_questions}/${quiz.question_count} questions completed
                        </small>
                    </div>

                    <div class="d-flex justify-content-between align-items-center">
                        <div class="text-muted small">
                            <i class="bi bi-clock"></i>
                            ${quiz.duration_minutes ? quiz.duration_minutes + ' min' : 'No time limit'}
                        </div>
                        <button class="btn btn-sm btn-primary view-quiz-btn" data-quiz-id="${quiz.id}">
                            View Details
                        </button>
                    </div>
                </div>
            `;
            container.appendChild(col);
        });

        // Add event listeners
        document.querySelectorAll('.view-quiz-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const quizId = e.target.dataset.quizId;
                loadQuizDetail(quizId);
            });
        });
    } catch (error) {
        
        // Check if it's an authentication error
        if (isAuthError(error)) {
            showAuthRequired(container);
        } else {
            // Generic error message
            showErrorMessage(container, 'Failed to load quizzes. Please try again later.');
        }
    }
}

/**
 * Load quiz details
 */
async function loadQuizDetail(quizId) {
    try {
        const response = await authenticatedFetch(`${API_BASE}/${quizId}`);
        const data = await response.json();

        if (!response.ok) {
            throw new Error(data?.message || 'Failed to load quiz detail.');
        }

        const quiz = data;
        
        // Basic information
        document.getElementById('detail-title').textContent = quiz.title;
        document.getElementById('detail-description').textContent = 
            quiz.description || 'No description provided';
        document.getElementById('detail-classroom').textContent = 
            quiz.classroom?.name || '';
        
        // Status badge - quiz detail has 'progress' not 'attempt'
        const statusBadgeHtml = getStatusBadge(quiz);
        document.getElementById('detail-status-badge').innerHTML = statusBadgeHtml;

        // Progress - use progress object from backend
        let completedCount = 0;
        let totalCount = quiz.questions.length;
        
        if (quiz.progress) {
            completedCount = quiz.progress.completed_questions;
            totalCount = quiz.progress.total_questions;
        } else {
            // Fallback: count from questions
            completedCount = quiz.questions.filter(q => q.submission).length;
        }
        
        const progress = totalCount > 0 ? Math.round((completedCount / totalCount) * 100) : 0;
        
        document.getElementById('detail-progress-bar').style.width = progress + '%';
        document.getElementById('detail-progress-text').textContent = 
            `${completedCount}/${totalCount} questions completed`;

        // Statistics
        document.getElementById('detail-duration').textContent = 
            quiz.duration_minutes ? `${quiz.duration_minutes} minutes` : 'No time limit';
        document.getElementById('detail-due-date').innerHTML = 
            formatDate(quiz.due_date);
        
        // Display score if available
        if (quiz.progress && quiz.progress.percentage !== undefined) {
            document.getElementById('detail-score-stat').style.display = 'flex';
            document.getElementById('detail-score').textContent = 
                `Score: ${quiz.progress.total_score.toFixed(1)}/${quiz.progress.max_score} (${Math.round(quiz.progress.percentage)}%)`;
        } else {
            document.getElementById('detail-score-stat').style.display = 'none';
        }

        // Question list
        const questionsContainer = document.getElementById('detail-questions');
        questionsContainer.innerHTML = '';

        if (quiz.questions.length === 0) {
            questionsContainer.innerHTML = `
                <div class="text-center text-muted py-4">
                    <p>No questions in this quiz yet</p>
                </div>
            `;
        } else {
            quiz.questions.forEach((question, index) => {
                const hasSubmission = question.submission !== null && question.submission !== undefined;
                const div = document.createElement('div');
                div.className = 'question-item' + (hasSubmission ? ' completed' : '');
                
                let scoreInfo = '';
                if (hasSubmission && question.submission.score !== null) {
                    scoreInfo = `<span class="ms-2 badge ${question.submission.score >= 70 ? 'bg-success' : 'bg-warning'}">
                        ${question.submission.score}%
                    </span>`;
                }
                
                div.innerHTML = `
                    <div class="question-item-content">
                        <div class="question-item-header">
                            <div class="question-item-title">
                                ${hasSubmission ? '<i class="bi bi-check-circle-fill text-success"></i>' : '<i class="bi bi-circle text-muted"></i>'}
                                <strong>${escapeHtml(question.title)}</strong>
                                ${scoreInfo}
                            </div>
                        </div>
                        <div class="question-item-meta">
                            <span class="question-meta-item">
                                <i class="bi bi-code-slash"></i> ${escapeHtml(question.programming_language)}
                            </span>
                            <span class="question-meta-item">
                                <i class="bi bi-star"></i> ${question.points} points
                            </span>
                        </div>
                    </div>
                    <div class="question-item-action">
                        <a href="/question/${question.id}" class="btn btn-sm ${hasSubmission ? 'btn-outline-success' : 'btn-primary'}">
                            ${hasSubmission ? 'Review' : 'Start'}
                        </a>
                    </div>
                `;
                questionsContainer.appendChild(div);
            });
        }

        // Switch view
        document.getElementById('quiz-list-view').style.display = 'none';
        document.getElementById('quiz-detail-view').style.display = 'block';
        currentView = 'detail';
        
        // Scroll to top
        window.scrollTo({ top: 0, behavior: 'smooth' });
    } catch (error) {
        
        // Check if it's an authentication error
        if (isAuthError(error)) {
            alert('Authentication required. Please log in to view quiz details.');
            window.location.href = `/auth/login?next=${encodeURIComponent(window.location.pathname)}`;
        } else {
            alert('Failed to load quiz details. Please try again.');
        }
    }
}

/**
 * Return to list view
 */
document.getElementById('back-to-list').addEventListener('click', () => {
    document.getElementById('quiz-list-view').style.display = 'block';
    document.getElementById('quiz-detail-view').style.display = 'none';
    currentView = 'list';
    window.scrollTo({ top: 0, behavior: 'smooth' });
});

// Initialize
loadQuizzes();
