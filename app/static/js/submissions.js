// app/static/js/submissions.js
import { authenticatedFetch } from './auth.js';

const API_BASE = '/api/v1';

async function loadSubmissions() {
    const container = document.getElementById('submissionsList');
    
    try {
        const response = await authenticatedFetch(`${API_BASE}/submissions/mine`);
        
        if (!response.ok) {
            if (response.status === 401) {
                window.location.href = '/auth/login?next=/submissions';
                return;
            }
            throw new Error('Failed to load submissions');
        }
        
        const data = await response.json();
        
        if (!data.items || data.items.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <i class="bi bi-inbox"></i>
                    <p>No submissions yet</p>
                    <a href="/dashboard" class="btn btn-primary mt-3">
                        <i class="bi bi-search"></i> Browse Questions
                    </a>
                </div>
            `;
            return;
        }
        
        // Render submissions as cards
        container.innerHTML = data.items.map(item => {
            const status = (item.status || '').toLowerCase();
            const isPassed = status === 'completed' && (item.score || 0) >= 60;
            const statusClass = isPassed ? 'passed' : 
                               status === 'pending' ? 'pending' : 'failed';
            const statusLabel = isPassed ? 'Passed' :
                               status === 'pending' ? 'Pending' : 'Failed';
            
            const questionTitle = item.question_title || `Problem #${item.problem_id || item.question_id || '?'}`;
            const problemHref = item.problem_id
                ? `/problem/${item.problem_id}?language=${encodeURIComponent(item.language || 'python')}`
                : '/dashboard';
            const score = item.score !== null && item.score !== undefined ? item.score : 'N/A';
            const submittedAt = item.submitted_at
                ? new Date(item.submitted_at).toLocaleString()
                : 'N/A';
            
            return `
                <div class="submission-item ${statusClass}">
                    <div class="submission-header">
                        <div class="submission-title">
                            <i class="bi bi-file-code"></i>
                            <a href="${problemHref}" class="text-decoration-none text-dark">
                                ${questionTitle}
                            </a>
                        </div>
                        <div class="submission-status ${statusClass}">
                            <i class="bi bi-${isPassed ? 'check-circle-fill' : status === 'pending' ? 'clock' : 'x-circle-fill'}"></i>
                            ${statusLabel}
                        </div>
                    </div>
                    <div class="submission-details">
                        <div class="submission-detail">
                            <div class="submission-detail-label">Submission ID</div>
                            <div class="submission-detail-value">#${item.id}</div>
                        </div>
                        <div class="submission-detail">
                            <div class="submission-detail-label">Score</div>
                            <div class="submission-detail-value">${score}</div>
                        </div>
                        <div class="submission-detail">
                            <div class="submission-detail-label">Submitted At</div>
                            <div class="submission-detail-value">${submittedAt}</div>
                        </div>
                        <div class="submission-detail">
                            <div class="submission-detail-label">Action</div>
                            <div class="submission-detail-value">
                                <a href="/submissions/${item.id}" class="btn btn-sm btn-outline-primary">
                                    <i class="bi bi-eye"></i> View Details
                                </a>
                            </div>
                        </div>
                    </div>
                </div>
            `;
        }).join('');
        
    } catch (error) {
        container.innerHTML = `
            <div class="empty-state">
                <i class="bi bi-exclamation-circle text-danger"></i>
                <p>Failed to load submissions</p>
                <button onclick="location.reload()" class="btn btn-outline-primary mt-3">
                    <i class="bi bi-arrow-clockwise"></i> Try Again
                </button>
            </div>
        `;
    }
}

document.addEventListener('DOMContentLoaded', loadSubmissions);
