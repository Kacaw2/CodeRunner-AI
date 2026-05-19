// app/static/js/submission_detail.js
import { authenticatedFetch } from './auth.js';

const API_BASE = '/api/v1';
const submissionId = window.location.pathname.split('/').pop();

async function loadSubmissionDetail() {
    const container = document.getElementById('submissionDetail');

    try {
        //  API route
        const response = await authenticatedFetch(`${API_BASE}/submissions/${submissionId}`);

        if (!response.ok) {
            if (response.status === 401) {
                window.location.href = `/auth/login?next=/submissions/${submissionId}`;
                return;
            }
            if (response.status === 403) {
                container.innerHTML = `
                    <div class="error-container" style="padding: 2rem; text-align: center;">
                        <i class="bi bi-exclamation-triangle-fill" style="font-size: 3rem; color: #ef4444;"></i>
                        <p style="margin-top: 1rem; color: #64748b;">You do not have permission to view this submission.</p>
                    </div>
                `;
                return;
            }
            throw new Error('Failed to load submission');
        }

        const data = await response.json();
        const cases = Array.isArray(data.cases) ? data.cases : [];
        const passedCount = cases.filter(c => c.passed).length;
        const totalCases = cases.length;

        const questionTitle = data.question_title || `Question #${data.question_id}`;
        const statusRaw = (data.status || '').toLowerCase();
        const submittedAt = data.submitted_at ? new Date(data.submitted_at).toLocaleString() : '';
        const score = data.score || 0;

        // Determine status badge
        const statusBadge = statusRaw === 'completed' 
            ? '<span class="meta-badge" style="background: #dcfce7; color: #16a34a;"><i class="bi bi-check-circle-fill"></i> COMPLETED</span>'
            : '<span class="meta-badge" style="background: #fee2e2; color: #dc2626;"><i class="bi bi-x-circle-fill"></i> FAILED</span>';

let html = `
<!-- Submission Header -->
<div class="submission-header">
<div class="submission-info">
<h1 class="submission-title">${escapeHtml(questionTitle)}</h1>
<div class="submission-meta">
${statusBadge}
<span class="meta-badge" style="background: #fef3c7; color: #ca8a04;">
<i class="bi bi-trophy-fill"></i> Score: ${score}/100
</span>
${submittedAt ? `
<span class="meta-badge">
<i class="bi bi-clock"></i> ${submittedAt}
</span>` : ''}
</div>
</div>
<div>
<a href="/question/${data.question_id}" class="btn btn-run">
<i class="bi bi-arrow-repeat"></i> Try Again
</a>
</div>
</div>

<!-- Submission Body -->
<div class="submission-body">
<!-- Code Section -->
<div class="code-section">
<h3 class="section-title">
<i class="bi bi-code-square"></i>
Submitted Code
</h3>
<textarea id="codeView">${escapeHtml(data.code || '')}</textarea>
</div>

<!-- Test Cases Section -->
<div class="results-section">
<h3 class="section-title">
<i class="bi bi-list-check"></i>
Test Cases 
<span style="color: #64748b; font-size: 0.9rem; font-weight: 500;">
(${passedCount}/${totalCases} passed)
</span>
</h3>
`;

        if (totalCases > 0) {
            cases.forEach((testCase, idx) => {
                const pass = !!testCase.passed;
                const index = testCase.index || (idx + 1);
                const isHidden = !!testCase.hidden;
                const statusText = (testCase.status || (pass ? 'AC' : 'WA')).toUpperCase();
                const timeLabel = (testCase.time_ms !== undefined && testCase.time_ms !== null)
                    ? `${testCase.time_ms} ms`
                    : '';

html += `
<div class="single-test-case" style="margin-bottom: 1rem;">
<!-- Test Case Header -->
<div class="test-case-header-full">
<div class="header-left-group">
<div class="test-case-title-inline">
<i class="bi bi-file-code"></i>
Test Case ${index}${isHidden ? ' (Hidden)' : ''}
</div>
<span class="test-status-inline ${pass ? 'passed' : 'failed'}">
<i class="bi bi-${pass ? 'check-circle-fill' : 'x-circle-fill'}"></i>
${pass ? 'Passed' : 'Failed'}
</span>
</div>
<div class="header-right-group">
${statusText ? `<span class="meta-badge">${statusText}</span>` : ''}
${timeLabel ? `<span class="time-inline"><i class="bi bi-stopwatch"></i> ${timeLabel}</span>` : ''}
</div>
</div>

<!-- Test Case Details -->
<div class="output-container">
`;

                // Input and Expected (only if not hidden)
                if (!isHidden) {
html += `
<div class="output-block">
<div class="output-label">Input</div>
<div class="output-content ${testCase.input ? '' : 'empty'}">
${escapeHtml(testCase.input || '(empty)')}
</div>
</div>
<div class="output-block target-output">
<div class="output-label">Expected Output</div>
<div class="output-content ${testCase.expected ? '' : 'empty'}">
${escapeHtml(testCase.expected || '(empty)')}
</div>
</div>
`;
                } else {
html += `
<div class="output-block" style="border-left-color: #94a3b8;">
<div class="output-label">Hidden Test Case</div>
<div class="output-content empty">
This is a hidden test case. Only the result is visible.
</div>
</div>
`;
                }

                // Your Output
html += `
<div class="output-block your-output">
<div class="output-label">Your Output</div>
<div class="output-content ${testCase.output ? '' : 'empty'}">
${escapeHtml(testCase.output || '(empty)')}
</div>
</div>
`;

                // Error Output (if any)
                if (testCase.stderr) {
                    html += `
                        <div class="output-block error-output">
                            <div class="output-label">Error Output</div>
                            <div class="output-content">
                                ${escapeHtml(testCase.stderr)}
                            </div>
                        </div>
                    `;
                }

                html += `
                        </div> <!-- output-container -->
                    </div> <!-- single-test-case -->
                `;
            });
        } else {
            html += `
                <div class="result-placeholder">
                    <i class="bi bi-inbox" style="font-size: 2.5rem; opacity: 0.3;"></i>
                    <p>No test results available.</p>
                </div>
            `;
        }

        html += `
                </div> <!-- results-section -->
            </div> <!-- submission-body -->
        `;

        container.innerHTML = html;

        // Initialize CodeMirror for code view
        if (window.CodeMirror) {
            const editor = CodeMirror.fromTextArea(document.getElementById('codeView'), {
                mode: 'text/x-csrc',
                theme: 'darcula',
                lineNumbers: true,
                readOnly: true
            });
            editor.setSize('100%', '400px');
        }

    } catch (error) {
        container.innerHTML = `
            <div class="error-container" style="padding: 2rem; text-align: center;">
                <i class="bi bi-exclamation-triangle-fill" style="font-size: 3rem; color: #ef4444;"></i>
                <p style="margin-top: 1rem; color: #64748b;">Failed to load submission details. Please try again.</p>
            </div>
        `;
    }
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

document.addEventListener('DOMContentLoaded', loadSubmissionDetail);
