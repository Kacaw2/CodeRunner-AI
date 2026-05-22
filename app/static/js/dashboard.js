const API_PUBLIC = "/api/v1";
const API_PUBLIC_QUIZ = "/api/public";

let currentPage = 1;
let itemsPerPage = 20;
let totalProblems = 0;
let currentFilters = { quiz: "", difficulty: "" };

function escapeHtml(text) {
    if (text === null || text === undefined) return "";
    const div = document.createElement("div");
    div.textContent = String(text);
    return div.innerHTML;
}

async function loadQuizzes() {
    try {
        const response = await fetch(`${API_PUBLIC_QUIZ}/quizzes`);
        if (!response.ok) return;
        const data = await response.json();
        const select = document.getElementById("quizFilter");
        const currentValue = select.value;
        select.innerHTML = '<option value="">All Quizzes</option>';
        (data.items || []).forEach(quiz => {
            const option = document.createElement("option");
            option.value = quiz.id;
            option.textContent = quiz.title || `Quiz #${quiz.id}`;
            select.appendChild(option);
        });
        if (currentValue) select.value = currentValue;
    } catch (_) {
    }
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
            totalProblems = data.global.questions || 0;
        }
    } catch (_) {
        document.getElementById("stat-challenges").textContent = "-";
        document.getElementById("stat-quizzes").textContent = "-";
        document.getElementById("stat-questions").textContent = "-";
        document.getElementById("stat-submissions24h").textContent = "-";
    }
}

function renderDifficulty(difficulty) {
    const diff = (difficulty || "").toLowerCase();
    return diff
        ? `<span class="diff-badge ${escapeHtml(diff)}">${escapeHtml(diff)}</span>`
        : '<span class="diff-badge muted">-</span>';
}

function renderLanguageOptions(problem) {
    const defaultLang = problem.default_language || "python";
    return (problem.variants || []).map(variant => {
        const language = variant.language || "python";
        const selected = language === defaultLang ? "selected" : "";
        return `<option value="${escapeHtml(language)}" ${selected}>${escapeHtml(language.toUpperCase())}</option>`;
    }).join("");
}

async function loadQuestionList(page = 1) {
    const tbody = document.getElementById("q-public-tbody");
    currentPage = page;

    tbody.innerHTML = `<tr><td colspan="5" class="text-center text-muted py-4">
        <div class="spinner-border spinner-border-sm me-2"></div> Loading...
    </td></tr>`;

    try {
        let apiUrl = `${API_PUBLIC}/problems?limit=1000&offset=0`;
        if (currentFilters.quiz) apiUrl += `&quiz_id=${currentFilters.quiz}`;

        const response = await fetch(apiUrl);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);

        const data = await response.json();
        let allItems = data.items || [];

        if (currentFilters.difficulty) {
            allItems = allItems.filter(problem =>
                (problem.difficulty || "").toLowerCase() === currentFilters.difficulty
            );
        }

        totalProblems = allItems.length;
        tbody.innerHTML = "";

        if (allItems.length === 0) {
            const hasFilters = currentFilters.quiz || currentFilters.difficulty;
            tbody.innerHTML = `<tr><td colspan="5">
                <div class="table-empty-state">
                    <i class="bi bi-inbox"></i>
                    <p>${hasFilters ? "No problems match your filters" : "No problems available yet"}</p>
                </div>
            </td></tr>`;
            document.getElementById("pagination-container").style.display = "none";
            return;
        }

        const pageItems = itemsPerPage === "all"
            ? allItems
            : allItems.slice((currentPage - 1) * itemsPerPage, (currentPage - 1) * itemsPerPage + parseInt(itemsPerPage, 10));

        pageItems.forEach((problem, idx) => {
            const globalIdx = itemsPerPage === "all" ? idx + 1 : (currentPage - 1) * itemsPerPage + idx + 1;
            const tr = document.createElement("tr");
            tr.dataset.problemRow = String(problem.id);
            tr.onclick = event => {
                if (event.target.closest("select")) return;
                window.location.href = `/problem/${problem.id}?language=python`;
            };

            tr.innerHTML = `
                <td class="col-status">
                    <span class="status-icon" title="${problem.completed ? "Completed" : "Not attempted"}">
                        <i class="bi ${problem.completed ? "bi-check-circle-fill text-success" : "bi-circle"}"></i>
                    </span>
                </td>
                <td class="col-id"><span class="problem-id">${globalIdx}</span></td>
                <td class="col-title">
                    <a class="problem-title-link" href="/problem/${problem.id}?language=python">${escapeHtml(problem.title || "Untitled")}</a>
                </td>
                <td class="col-difficulty">${renderDifficulty(problem.difficulty)}</td>
                <td class="col-lang">
                    <select class="form-select form-select-sm problem-language-select" data-problem-language="${problem.id}">
                        ${renderLanguageOptions(problem)}
                    </select>
                </td>
            `;
            tbody.appendChild(tr);
        });

        tbody.querySelectorAll(".problem-language-select").forEach(select => {
            select.addEventListener("change", event => {
                const problemId = event.currentTarget.dataset.problemLanguage;
                const lang = event.currentTarget.value || "python";
                window.location.href = `/problem/${problemId}?language=${encodeURIComponent(lang)}`;
            });
        });

        if (itemsPerPage !== "all" && totalProblems > itemsPerPage) {
            updatePagination();
        } else {
            document.getElementById("pagination-container").style.display = "none";
        }
    } catch (error) {
        tbody.innerHTML = `<tr><td colspan="5" class="text-center text-danger py-4">
            <p class="mb-1">Failed to load problems</p>
            <small>${escapeHtml(error.message)}</small>
        </td></tr>`;
        document.getElementById("pagination-container").style.display = "none";
    }
}

function updatePagination() {
    const totalPages = Math.ceil(totalProblems / itemsPerPage);
    const container = document.getElementById("pagination-container");
    const pagination = document.getElementById("pagination");
    const info = document.getElementById("pagination-info");

    if (totalPages <= 1) {
        container.style.display = "none";
        return;
    }

    container.style.display = "flex";
    pagination.innerHTML = "";

    const prevLi = document.createElement("li");
    prevLi.className = `page-item ${currentPage === 1 ? "disabled" : ""}`;
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

    const nextLi = document.createElement("li");
    nextLi.className = `page-item ${currentPage === totalPages ? "disabled" : ""}`;
    nextLi.innerHTML = `<a class="page-link" href="#" data-page="${currentPage + 1}"><i class="bi bi-chevron-right"></i></a>`;
    pagination.appendChild(nextLi);

    const start = (currentPage - 1) * itemsPerPage + 1;
    const end = Math.min(currentPage * itemsPerPage, totalProblems);
    info.textContent = `Showing ${start}-${end} of ${totalProblems}`;

    pagination.querySelectorAll("a.page-link").forEach(link => {
        link.addEventListener("click", event => {
            event.preventDefault();
            const page = parseInt(link.dataset.page, 10);
            if (page && page !== currentPage && page >= 1 && page <= totalPages) {
                loadQuestionList(page);
                document.querySelector(".page-section").scrollIntoView({ behavior: "smooth" });
            }
        });
    });
}

function addPageItem(pagination, pageNum) {
    const li = document.createElement("li");
    li.className = `page-item ${pageNum === currentPage ? "active" : ""}`;
    li.innerHTML = `<a class="page-link" href="#" data-page="${pageNum}">${pageNum}</a>`;
    pagination.appendChild(li);
}

function addEllipsis(pagination) {
    const li = document.createElement("li");
    li.className = "page-item disabled";
    li.innerHTML = '<span class="page-link">...</span>';
    pagination.appendChild(li);
}

document.getElementById("itemsPerPage").addEventListener("change", event => {
    itemsPerPage = event.target.value === "all" ? "all" : parseInt(event.target.value, 10);
    currentPage = 1;
    loadQuestionList(1);
});

document.getElementById("quizFilter").addEventListener("change", event => {
    currentFilters.quiz = event.target.value;
    currentPage = 1;
    loadQuestionList(1);
});

document.getElementById("difficultyFilter").addEventListener("change", event => {
    currentFilters.difficulty = event.target.value;
    currentPage = 1;
    loadQuestionList(1);
});

document.getElementById("clearFilters").addEventListener("click", () => {
    currentFilters = { quiz: "", difficulty: "" };
    document.getElementById("quizFilter").value = "";
    document.getElementById("difficultyFilter").value = "";
    currentPage = 1;
    loadQuestionList(1);
});

async function initDashboard() {
    await Promise.allSettled([
        loadOverview(),
        loadQuizzes(),
        loadQuestionList(1),
    ]);
}

initDashboard();
