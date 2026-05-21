// static/js/dashboard.js
import { getToken } from '/static/js/auth.js';

const API_PUBLIC = "/api/v1";
const API_PUBLIC_QUIZ = "/api/public";

let currentPage = 1;
let itemsPerPage = 20;
let totalQuestions = 0;

let currentFilters = { quiz: '', difficulty: '' };

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

async function loadQuizzes() {
    try {
        const response = await fetch(`${API_PUBLIC_QUIZ}/quizzes`);
        if (!response.ok) return;
        const data = await response.json();
        const quizzes = data.items || [];
        const select = document.getElementById('quizFilter');
        const currentValue = select.value;
        select.innerHTML = '<option value="">All Quizzes</option>';
        quizzes.forEach(quiz => {
            const option = document.createElement('option');
            option.value = quiz.id;
            option.textContent = escapeHtml(quiz.title || `Quiz #${quiz.id}`);
            select.appendChild(option);
        });
        if (currentValue) select.value = currentValue;
    } catch (_) {}
}

async function loadOverview() {
    try {
        const response = await fetch(`${API_PUBLIC}/metrics/overview`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        if (data.global) {
            document.getElementById("stat-challenges").textContent = data.global.questions || 0;
            document.getElementById("stat-quizzes").textContent = data.global.quizzes || 0;
            document.getElementById("stat-questions").textContent = data.global.active_users || 0;
            document.getElementById("stat-submissions24h").textContent = data.global.submissions_24h || 0;
            totalQuestions = data.global.questions || 0;
        }
    } catch (_) {
        document.getElementById("stat-challenges").textContent = '-';
        document.getElementById("stat-quizzes").textContent = '-';
        document.getElementById("stat-questions").textContent = '-';
        document.getElementById("stat-submissions24h").textContent = '-';
    }
}

function langIcon(lang) {
    const l = (lang || '').toLowerCase();
    if (l === 'python' || l === 'python3') return '<i class="bi bi-filetype-py"></i>';
    if (l === 'c')      return '<i class="bi bi-filetype-cs"></i>';
    if (l === 'java')   return '<i class="bi bi-filetype-java"></i>';
    if (l === 'js' || l === 'javascript') return '<i class="bi bi-filetype-js"></i>';
    return '<i class="bi bi-code-slash"></i>';
}

async function loadQuestionList(page = 1) {
    const tbody = document.getElementById('q-public-tbody');
    currentPage = page;

    tbody.innerHTML = `<tr><td colspan="5" class="text-center text-muted py-4">
        <div class="spinner-border spinner-border-sm me-2"></div> Loading...
    </td></tr>`;

    try {
        let apiUrl = `${API_PUBLIC}/questions?limit=1000&offset=0`;
        if (currentFilters.quiz) apiUrl += `&quiz_id=${currentFilters.quiz}`;

        const response = await fetch(apiUrl);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);

        const data = await response.json();
        let allItems = data.items || [];

        // Apply difficulty filter
        if (currentFilters.difficulty) {
            allItems = allItems.filter(q =>
                (q.difficulty || '').toLowerCase() === currentFilters.difficulty
            );
        }

        totalQuestions = allItems.length;
        tbody.innerHTML = '';

        if (allItems.length === 0) {
            const hasFilters = currentFilters.quiz || currentFilters.difficulty;
            tbody.innerHTML = `<tr><td colspan="5">
                <div class="table-empty-state">
                    <i class="bi bi-inbox"></i>
                    <p>${hasFilters ? 'No questions match your filters' : 'No questions available yet'}</p>
                </div>
            </td></tr>`;
            document.getElementById('pagination-container').style.display = 'none';
            return;
        }

        // Paginate
        let pageItems;
        if (itemsPerPage === 'all') {
            pageItems = allItems;
        } else {
            const start = (currentPage - 1) * itemsPerPage;
            pageItems = allItems.slice(start, start + parseInt(itemsPerPage));
        }

        // Render rows
        pageItems.forEach((q, idx) => {
            const globalIdx = (itemsPerPage === 'all') ? idx + 1 : (currentPage - 1) * itemsPerPage + idx + 1;
            const tr = document.createElement('tr');
            tr.onclick = () => window.location.href = `/question/${q.id}`;

            const diff = (q.difficulty || '').toLowerCase();
            const diffHtml = diff
                ? `<span class="diff-badge ${escapeHtml(diff)}">${escapeHtml(diff)}</span>`
                : '<span class="diff-badge" style="background:#f3f4f6;color:#9ca3af;">—</span>';

            const lang = escapeHtml(q.programming_language || '—');

            tr.innerHTML = `
                <td class="col-status">
                    <span class="status-icon" title="Not attempted">
                        <i class="bi bi-circle"></i>
                    </span>
                </td>
                <td class="col-id"><span class="problem-id">${globalIdx}</span></td>
                <td class="col-title">
                    <a class="problem-title-link" href="/question/${q.id}">${escapeHtml(q.title || 'Untitled')}</a>
                </td>
                <td class="col-difficulty">${diffHtml}</td>
                <td class="col-lang"><span class="lang-tag">${langIcon(q.programming_language)} ${lang}</span></td>
            `;
            tbody.appendChild(tr);
        });

        if (itemsPerPage !== 'all' && totalQuestions > itemsPerPage) {
            updatePagination();
        } else {
            document.getElementById('pagination-container').style.display = 'none';
        }

    } catch (error) {
        tbody.innerHTML = `<tr><td colspan="5" class="text-center text-danger py-4">
            <p class="mb-1">Failed to load questions</p>
            <small>${escapeHtml(error.message)}</small>
        </td></tr>`;
        document.getElementById('pagination-container').style.display = 'none';
    }
}

function updatePagination() {
    const totalPages = Math.ceil(totalQuestions / itemsPerPage);
    const container = document.getElementById('pagination-container');
    const pagination = document.getElementById('pagination');
    const info = document.getElementById('pagination-info');

    if (totalPages <= 1) { container.style.display = 'none'; return; }

    container.style.display = 'flex';
    pagination.innerHTML = '';

    // Prev
    const prevLi = document.createElement('li');
    prevLi.className = `page-item ${currentPage === 1 ? 'disabled' : ''}`;
    prevLi.innerHTML = `<a class="page-link" href="#" data-page="${currentPage - 1}"><i class="bi bi-chevron-left"></i></a>`;
    pagination.appendChild(prevLi);

    const maxVisible = 5;
    let startPage = Math.max(1, currentPage - Math.floor(maxVisible / 2));
    let endPage = Math.min(totalPages, startPage + maxVisible - 1);
    if (endPage - startPage < maxVisible - 1) startPage = Math.max(1, endPage - maxVisible + 1);

    if (startPage > 1) {
        addPageItem(pagination, 1);
        if (startPage > 2) addEllipsis(pagination);
    }
    for (let i = startPage; i <= endPage; i++) addPageItem(pagination, i);
    if (endPage < totalPages) {
        if (endPage < totalPages - 1) addEllipsis(pagination);
        addPageItem(pagination, totalPages);
    }

    // Next
    const nextLi = document.createElement('li');
    nextLi.className = `page-item ${currentPage === totalPages ? 'disabled' : ''}`;
    nextLi.innerHTML = `<a class="page-link" href="#" data-page="${currentPage + 1}"><i class="bi bi-chevron-right"></i></a>`;
    pagination.appendChild(nextLi);

    const start = (currentPage - 1) * itemsPerPage + 1;
    const end = Math.min(currentPage * itemsPerPage, totalQuestions);
    info.textContent = `Showing ${start}–${end} of ${totalQuestions}`;

    pagination.querySelectorAll('a.page-link').forEach(link => {
        link.addEventListener('click', e => {
            e.preventDefault();
            const p = parseInt(link.dataset.page);
            if (p && p !== currentPage && p >= 1 && p <= totalPages) {
                loadQuestionList(p);
                document.querySelector('.page-section').scrollIntoView({ behavior: 'smooth' });
            }
        });
    });
}

function addPageItem(pagination, pageNum) {
    const li = document.createElement('li');
    li.className = `page-item ${pageNum === currentPage ? 'active' : ''}`;
    li.innerHTML = `<a class="page-link" href="#" data-page="${pageNum}">${pageNum}</a>`;
    pagination.appendChild(li);
}

function addEllipsis(pagination) {
    const li = document.createElement('li');
    li.className = 'page-item disabled';
    li.innerHTML = '<span class="page-link">…</span>';
    pagination.appendChild(li);
}

// Event listeners
document.getElementById('itemsPerPage').addEventListener('change', e => {
    itemsPerPage = e.target.value === 'all' ? 'all' : parseInt(e.target.value);
    currentPage = 1;
    loadQuestionList(1);
});

document.getElementById('quizFilter').addEventListener('change', e => {
    currentFilters.quiz = e.target.value;
    currentPage = 1;
    loadQuestionList(1);
});

document.getElementById('difficultyFilter').addEventListener('change', e => {
    currentFilters.difficulty = e.target.value;
    currentPage = 1;
    loadQuestionList(1);
});

document.getElementById('clearFilters').addEventListener('click', () => {
    currentFilters = { quiz: '', difficulty: '' };
    document.getElementById('quizFilter').value = '';
    document.getElementById('difficultyFilter').value = '';
    currentPage = 1;
    loadQuestionList(1);
});

async function initDashboard() {
    await Promise.allSettled([
        loadOverview(),
        loadQuizzes(),
        loadQuestionList(1)
    ]);
}

initDashboard();
