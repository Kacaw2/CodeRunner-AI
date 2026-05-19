// static/js/dashboard.js
import { getToken, authenticatedFetch } from '/static/js/auth.js';

const API_PUBLIC = "/api/v1";
const API_AUTH = "/api/v1";
const API_PUBLIC_QUIZ = "/api/public";
// Pagination state
let currentPage = 1;
let itemsPerPage = 12;
let totalQuestions = 0;

// Filter state
let currentFilters = {
    language: '',
    quiz: ''
};

/**
 * HTML escape function to prevent XSS
 */
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

/**
 * Load available languages for filter
 */
async function loadLanguages() {
    try {
        const response = await fetch(`${API_PUBLIC}/questions?limit=1000`);
        if (!response.ok) return;
        
        const data = await response.json();
        const items = data.items || [];
        
        // Extract unique languages
        const languages = [...new Set(items.map(q => q.programming_language).filter(Boolean))];
        languages.sort();
        
        const select = document.getElementById('languageFilter');
        const currentValue = select.value;
        
        // Keep "All Languages" option and add languages
        select.innerHTML = '<option value="">All Languages</option>';
        languages.forEach(lang => {
            const option = document.createElement('option');
            option.value = lang;
            option.textContent = lang;
            select.appendChild(option);
        });
        
        // Restore previous selection if exists
        if (currentValue && languages.includes(currentValue)) {
            select.value = currentValue;
        }
    } catch (error) {
    }
}

/**
 * Load available quizzes for filter
 */
async function loadQuizzes() {
    try {
        const response = await fetch(`${API_PUBLIC_QUIZ}/quizzes`);
        if (!response.ok) return;
        
        const data = await response.json();
        const quizzes = data.items || [];
        
        const select = document.getElementById('quizFilter');
        const currentValue = select.value;
        
        // Keep "All Quizzes" option and add quizzes
        select.innerHTML = '<option value="">All Quizzes</option>';
        quizzes.forEach(quiz => {
            const option = document.createElement('option');
            option.value = quiz.id;
            option.textContent = escapeHtml(quiz.title || `Quiz #${quiz.id}`);
            select.appendChild(option);
        });
        
        // Restore previous selection if exists
        if (currentValue) {
            select.value = currentValue;
        }
    } catch (error) {
    }
}

/**
 * Load overview statistics data
 */
async function loadOverview() {
    try {
        const response = await fetch(`${API_PUBLIC}/metrics/overview`);
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        
        const data = await response.json();
        
        // Update global statistics
        if (data.global) {
            document.getElementById("stat-challenges").textContent = data.global.questions || 0;
            document.getElementById("stat-quizzes").textContent = data.global.quizzes || 0;
            document.getElementById("stat-questions").textContent = data.global.active_users || 0;
            document.getElementById("stat-submissions24h").textContent = data.global.submissions_24h || 0;
            
            // Save total questions count for pagination
            totalQuestions = data.global.questions || 0;
        }

        // If user is logged in, try to load authenticated statistics
        const token = getToken();
        if (token) {
            try {
                const authResponse = await fetch(`${API_AUTH}/metrics/overview`, { 
                    headers: { 'Authorization': `Bearer ${token}` }
                });
                if (authResponse.ok) {
                    const authData = await authResponse.json();
                }
            } catch (error) {
            }
        }
    } catch (error) {
        document.getElementById("stat-challenges").textContent = '-';
        document.getElementById("stat-quizzes").textContent = '-';
        document.getElementById("stat-questions").textContent = '-';
        document.getElementById("stat-submissions24h").textContent = '-';
    }
}

/**
 * Load public question list (with pagination and filters)
 */
async function loadQuestionList(page = 1) {
    const container = document.getElementById('q-public-list');
    currentPage = page;

    try {
        // Show loading state
        container.innerHTML = `
            <div class="col-12">
                <div class="card p-4 text-center text-muted">
                    <div class="spinner-border spinner-border-sm me-2"></div>
                    Loading questions...
                </div>
            </div>
        `;

        // IMPORTANT: Always fetch all questions (or a large number) first
        // Then apply filters, then paginate
        // This ensures filtered results are correct regardless of their position
        
        // Build API URL with quiz_id parameter if quiz filter is active
        let apiUrl = `${API_PUBLIC}/questions?limit=1000&offset=0`;
        if (currentFilters.quiz) {
            apiUrl += `&quiz_id=${currentFilters.quiz}`;
        }
        
        const response = await fetch(apiUrl);
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const data = await response.json();
        let allItems = data.items || [];
        
        // Apply client-side filters FIRST
        let filteredItems = applyFilters(allItems);
        
        // Update total count with filtered results
        totalQuestions = filteredItems.length;

        // Clear entire container
        container.innerHTML = '';

        // If no questions after filtering, show empty state
        if (filteredItems.length === 0) {
            const hasActiveFilters = currentFilters.language || currentFilters.quiz;
            container.innerHTML = `
                <div class="col-12">
                    <div class="card p-4 text-center text-muted">
                        <i class="bi bi-inbox" style="font-size: 3rem; opacity: 0.3;"></i>
                        <p class="mb-2 mt-3">${hasActiveFilters ? 'No questions match your filters' : 'No questions available yet'}</p>
                        ${hasActiveFilters ? '<small>Try adjusting your filters</small>' : ''}
                    </div>
                </div>
            `;
            document.getElementById('pagination-container').style.display = 'none';
            return;
        }

        // Apply pagination AFTER filtering
        let paginatedItems;
        if (itemsPerPage === 'all') {
            paginatedItems = filteredItems;
        } else {
            const startIndex = (currentPage - 1) * itemsPerPage;
            const endIndex = startIndex + parseInt(itemsPerPage);
            paginatedItems = filteredItems.slice(startIndex, endIndex);
        }

        // Render each question card
        paginatedItems.forEach(question => {
            const col = document.createElement('div');
            col.className = 'col';

            const title = escapeHtml(question.title || 'Untitled');
            const lang = escapeHtml(question.programming_language || 'unknown');
            const desc = escapeHtml((question.description || '').trim() || 'No description available.');

            col.innerHTML = `
                <article class="card problem-card h-100">
                    <div class="problem-card__header">
                        <h3 class="problem-card__title">${title}</h3>
                        <div class="problem-card__badges">
                            <span class="badge badge--language">${lang}</span>
                            <span class="badge badge--status-not-started">Public</span>
                        </div>
                    </div>

                    <p class="problem-card__description">${desc}</p>

                    <div class="problem-card__footer">
                        <span class="problem-card__prompt">
                            <span aria-hidden="true">🎯</span> Start Challenge
                        </span>
                        <a class="btn btn-ghost" href="/question/${question.id}">Start</a>
                    </div>
                </article>
            `;
            
            container.appendChild(col);
        });

        // Update pagination (only if not showing all)
        if (itemsPerPage !== 'all' && totalQuestions > itemsPerPage) {
            updatePagination();
        } else {
            document.getElementById('pagination-container').style.display = 'none';
        }

    } catch (error) {
        
        container.innerHTML = `
            <div class="col-12">
                <div class="card p-4 text-center text-danger">
                    <p class="mb-2">Failed to load questions</p>
                    <small>${escapeHtml(error.message)}</small>
                </div>
            </div>
        `;
        document.getElementById('pagination-container').style.display = 'none';
    }
}

/**
 * Apply filters to question list
 */
function applyFilters(questions) {
    let filtered = [...questions];
    
    // Filter by language
    if (currentFilters.language) {
        filtered = filtered.filter(q => 
            q.programming_language === currentFilters.language
        );
    }
    
    // Note: Quiz filtering is handled by the backend API
    // using the quiz_id parameter in loadQuestionList()
    
    return filtered;
}

/**
 * Update pagination controls
 */
function updatePagination() {
    const totalPages = Math.ceil(totalQuestions / itemsPerPage);
    const paginationContainer = document.getElementById('pagination-container');
    const pagination = document.getElementById('pagination');
    const paginationInfo = document.getElementById('pagination-info');

    if (totalPages <= 1) {
        paginationContainer.style.display = 'none';
        return;
    }

    paginationContainer.style.display = 'flex';
    pagination.innerHTML = '';

    // Previous button
    const prevLi = document.createElement('li');
    prevLi.className = `page-item ${currentPage === 1 ? 'disabled' : ''}`;
    prevLi.innerHTML = `<a class="page-link" href="#" data-page="${currentPage - 1}">
        <i class="bi bi-chevron-left"></i>
    </a>`;
    pagination.appendChild(prevLi);

    // Page numbers
    const maxVisiblePages = 5;
    let startPage = Math.max(1, currentPage - Math.floor(maxVisiblePages / 2));
    let endPage = Math.min(totalPages, startPage + maxVisiblePages - 1);

    if (endPage - startPage < maxVisiblePages - 1) {
        startPage = Math.max(1, endPage - maxVisiblePages + 1);
    }

    // First page
    if (startPage > 1) {
        const firstLi = document.createElement('li');
        firstLi.className = 'page-item';
        firstLi.innerHTML = `<a class="page-link" href="#" data-page="1">1</a>`;
        pagination.appendChild(firstLi);

        if (startPage > 2) {
            const ellipsisLi = document.createElement('li');
            ellipsisLi.className = 'page-item disabled';
            ellipsisLi.innerHTML = `<span class="page-link">...</span>`;
            pagination.appendChild(ellipsisLi);
        }
    }

    // Page numbers
    for (let i = startPage; i <= endPage; i++) {
        const li = document.createElement('li');
        li.className = `page-item ${i === currentPage ? 'active' : ''}`;
        li.innerHTML = `<a class="page-link" href="#" data-page="${i}">${i}</a>`;
        pagination.appendChild(li);
    }

    // Last page
    if (endPage < totalPages) {
        if (endPage < totalPages - 1) {
            const ellipsisLi = document.createElement('li');
            ellipsisLi.className = 'page-item disabled';
            ellipsisLi.innerHTML = `<span class="page-link">...</span>`;
            pagination.appendChild(ellipsisLi);
        }

        const lastLi = document.createElement('li');
        lastLi.className = 'page-item';
        lastLi.innerHTML = `<a class="page-link" href="#" data-page="${totalPages}">${totalPages}</a>`;
        pagination.appendChild(lastLi);
    }

    // Next button
    const nextLi = document.createElement('li');
    nextLi.className = `page-item ${currentPage === totalPages ? 'disabled' : ''}`;
    nextLi.innerHTML = `<a class="page-link" href="#" data-page="${currentPage + 1}">
        <i class="bi bi-chevron-right"></i>
    </a>`;
    pagination.appendChild(nextLi);

    // Pagination info
    const start = (currentPage - 1) * itemsPerPage + 1;
    const end = Math.min(currentPage * itemsPerPage, totalQuestions);
    paginationInfo.textContent = `Showing ${start}-${end} of ${totalQuestions} questions`;

    // Add click handlers
    pagination.querySelectorAll('a.page-link').forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            const page = parseInt(link.dataset.page);
            if (page && page !== currentPage && page >= 1 && page <= totalPages) {
                loadQuestionList(page);
                // Scroll to top of question list
                document.querySelector('.page-section').scrollIntoView({ behavior: 'smooth' });
            }
        });
    });
}

/**
 * Items per page change handler
 */
document.getElementById('itemsPerPage').addEventListener('change', (e) => {
    itemsPerPage = e.target.value === 'all' ? 'all' : parseInt(e.target.value);
    currentPage = 1;
    loadQuestionList(1);
});

/**
 * Language filter change handler
 */
document.getElementById('languageFilter').addEventListener('change', (e) => {
    currentFilters.language = e.target.value;
    currentPage = 1;
    loadQuestionList(1);
});

/**
 * Quiz filter change handler
 */
document.getElementById('quizFilter').addEventListener('change', (e) => {
    currentFilters.quiz = e.target.value;
    currentPage = 1;
    loadQuestionList(1);
});

/**
 * Clear filters button handler
 */
document.getElementById('clearFilters').addEventListener('click', () => {
    currentFilters.language = '';
    currentFilters.quiz = '';
    document.getElementById('languageFilter').value = '';
    document.getElementById('quizFilter').value = '';
    currentPage = 1;
    loadQuestionList(1);
});

/**
 * Initialize dashboard - load all data
 */
async function initDashboard() {
    
    // Load all data in parallel
    await Promise.allSettled([
        loadOverview(),
        loadLanguages(),
        loadQuizzes(),
        loadQuestionList(1)
    ]);
    
}

// Initialize after page load
initDashboard();
