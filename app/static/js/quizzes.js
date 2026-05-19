import { getToken, authenticatedFetch } from "/static/js/auth.js";

const API_BASE = "/api/v1";
let currentQuizId = null;

// Check authentication
const token = getToken();
if (!token) {
  window.location.href = "/auth/login?next=/teacher/quizzes";
}

// ========== Load Quizzes ==========
async function loadQuizzes() {
  const container = document.getElementById("quizzesList");

  try {
    const response = await authenticatedFetch(`${API_BASE}/quizzes`);
    const data = await response.json();

    if (!response.ok) {
      throw new Error(data?.message || "Failed to load quizzes");
    }

    const quizzes = data.items || [];

    if (!quizzes.length) {
      container.innerHTML = `
        <div class="col-12 text-center text-muted py-5">
          <i class="bi bi-inbox" style="font-size: 3rem; opacity: 0.3;"></i>
          <h5 class="mt-3">No quizzes yet</h5>
          <p>Create your first quiz to get started</p>
        </div>
      `;
      return;
    }

    container.innerHTML = quizzes
      .map(
        (quiz) => `
      <div class="col-md-6 col-lg-4">
        <div class="quiz-card ${
          !quiz.is_published ? "unpublished" : ""
        }" 
              onclick="viewQuiz(${quiz.id})">
          <div class="d-flex justify-content-between align-items-start mb-3">
            <h5 class="mb-0">${quiz.title}</h5>
            <span class="quiz-badge ${
              quiz.is_published ? "badge-published" : "badge-draft"
            }">
              ${quiz.is_published ? "Published" : "Draft"}
            </span>
          </div>
          <p class="text-muted small mb-3" style="min-height: 3rem;">
            ${quiz.description || "No description"}
          </p>

          <div class="d-flex align-items-center">
            <div class="d-flex gap-2 align-items-center">
              <span class="badge-info-custom">
                ${quiz.question_count || 0} questions
              </span>
              <span class="badge-primary-custom">
                ${quiz.total_points || 0} points
              </span>
            </div>

            <small class="text-muted d-inline-flex align-items-center ms-auto text-nowrap">
              <i class="bi bi-building me-1"></i>
              ${quiz.assigned_to_count || 0} classrooms
            </small>
          </div>
        </div>
      </div>
    `
      )
      .join("");
  } catch (error) {
    container.innerHTML =
      '<div class="col-12"><div class="alert alert-danger">Failed to load quizzes</div></div>';
  }
}

// ========== Create Quiz ==========
async function createQuiz() {
  const title = document.getElementById("quizTitle").value.trim();
  const description = document.getElementById("quizDescription").value.trim();
  const duration = document.getElementById("quizDuration").value;
  const isPublished = document.getElementById("quizPublished").checked;

  if (!title) {
    alert("Please enter a quiz title");
    return;
  }

  try {
    const response = await authenticatedFetch(`${API_BASE}/quizzes`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title,
        description,
        duration_minutes: duration ? parseInt(duration) : null,
        is_published: isPublished,
      }),
    });

    if (response.ok) {
      const modal = window.bootstrap.Modal.getInstance(
        document.getElementById("createQuizModal")
      );
      modal.hide();

      // Clear form
      document.getElementById("createQuizForm").reset();

      // Reload quizzes
      await loadQuizzes();

      alert("Quiz created successfully!");
    } else {
      const error = await response.json();
      alert(error.message || "Failed to create quiz");
    }
  } catch (error) {
    alert("Failed to create quiz. Please try again.");
  }
}

function updateModalContent(quiz) {
  document.getElementById("quizDetailTitle").textContent = quiz.title;
  document.getElementById("quizDetailDescription").textContent =
    quiz.description || "No description";
  
  // Update badge styling
  const badge = document.getElementById("quizStatusBadge");
  badge.textContent = quiz.is_published ? "Published" : "Draft";
  badge.className = quiz.is_published
    ? "quiz-badge badge-published ms-2"
    : "quiz-badge badge-draft ms-2";
  
  document.getElementById("publishBtnText").textContent = quiz.is_published
    ? "Unpublish"
    : "Publish";
  document.getElementById("quizQuestionCount").textContent =
    quiz.question_count || 0;
  document.getElementById("quizTotalPoints").textContent =
    quiz.total_points || 0;
}

// ========== Refresh Modal Content (for already-open modal) ==========
async function refreshModalContent() {
  if (!currentQuizId) return;

  try {
    const response = await authenticatedFetch(
      `${API_BASE}/quizzes/${currentQuizId}`
    );
    const quiz = await response.json();

    // Update modal content without re-showing
    updateModalContent(quiz);

    // Reload tabs data
    await loadQuizQuestions(currentQuizId);
    await loadQuizAssignments(currentQuizId);
    await loadQuizAttempts(currentQuizId);
  } catch (error) {
  }
}

// ========== View Quiz Details ==========
window.viewQuiz = async function (quizId) {
  currentQuizId = quizId;

  try {
    const response = await authenticatedFetch(
      `${API_BASE}/quizzes/${quizId}`
    );
    const quiz = await response.json();

    // Set modal content
    updateModalContent(quiz);

    // Load tabs data
    await loadQuizQuestions(quizId);
    await loadQuizAssignments(quizId);
    await loadQuizAttempts(quizId);

    // Show modal
    const modal = new window.bootstrap.Modal(
      document.getElementById("quizDetailModal")
    );
    modal.show();
  } catch (error) {
    alert("Failed to load quiz details");
  }
};

// ========== Load Quiz Questions ==========
async function loadQuizQuestions(quizId) {
  const container = document.getElementById("questionsList");

  try {
    const response = await authenticatedFetch(
      `${API_BASE}/quizzes/${quizId}/questions`
    );
    const data = await response.json();

    const questions = data.items || [];

    if (!questions.length) {
      container.innerHTML = '<p class="text-muted text-center">No questions yet</p>';
      return;
    }

    container.innerHTML = questions
      .map(
        (q) => `
      <div class="question-item">
        <div class="flex-grow-1">
          <div class="d-flex align-items-center gap-2 mb-2">
            <i class="bi bi-code-square text-primary"></i>
            <strong>${q.title}</strong>
            <span class="badge bg-secondary">${q.programming_language}</span>
          </div>
          <div class="d-flex gap-3 small text-muted">
            <span><i class="bi bi-star"></i> ${q.points} points</span>
            <span><i class="bi bi-list-ol"></i> Order: ${q.order}</span>
            <span><i class="bi bi-check2-square"></i> ${
              q.test_case_count || 0
            } test cases</span>
          </div>
        </div>
        <button class="btn btn-sm btn-outline-danger" onclick="removeQuestion(${
          q.id
        })">
          <i class="bi bi-trash"></i>
        </button>
      </div>
    `
      )
      .join("");
  } catch (error) {
    container.innerHTML =
      '<p class="text-danger text-center">Failed to load questions</p>';
  }
}

// ========== Load Quiz Assignments ==========
async function loadQuizAssignments(quizId) {
  const container = document.getElementById("assignmentsList");

  try {
    const response = await authenticatedFetch(
      `${API_BASE}/quizzes/${quizId}/assignments`
    );
    const data = await response.json();

    const assignments = data.items || [];

    if (!assignments.length) {
      container.innerHTML =
        '<p class="text-muted text-center">No classroom assignments yet</p>';
      return;
    }

    container.innerHTML = assignments
      .map((a) => {
        const dueDate = a.due_date
          ? new Date(a.due_date).toLocaleString()
          : "No due date";
        const isOverdue = a.is_overdue;

        return `
      <div class="assignment-item">
        <div class="d-flex justify-content-between align-items-center">
          <div class="flex-grow-1">
            <div class="d-flex align-items-center gap-2 mb-1">
              <i class="bi bi-building text-success"></i>
              <strong>${a.classroom_name}</strong>
              <span class="badge bg-secondary">${a.classroom_code}</span>
              ${
                isOverdue
                  ? '<span class="badge bg-danger">Overdue</span>'
                  : ""
              }
            </div>
            <div class="small text-muted">
              <i class="bi bi-calendar-event"></i> Due: ${dueDate}
              ${
                a.allow_late_submission
                  ? ' | <span class="text-info"><i class="bi bi-check-circle"></i> Late submissions allowed</span>'
                  : ""
              }
            </div>
          </div>
          <button class="btn btn-sm btn-outline-danger" onclick="unassignClassroom(${
            a.classroom_id
          })">
            <i class="bi bi-x-circle"></i> Unassign
          </button>
        </div>
      </div>
    `;
      })
      .join("");
  } catch (error) {
    container.innerHTML =
      '<p class="text-danger text-center">Failed to load assignments</p>';
  }
}

// ========== Load Quiz Attempts ==========
async function loadQuizAttempts(quizId) {
  const container = document.getElementById("attemptsList");

  try {
    const response = await authenticatedFetch(
      `${API_BASE}/quizzes/${quizId}/attempts`
    );
    const data = await response.json();

    const attempts = data.items || [];

    if (!attempts.length) {
      container.innerHTML =
        '<p class="text-muted text-center">No student attempts yet</p>';
      return;
    }

    container.innerHTML = attempts
      .map((attempt) => {
        const startedAt = attempt.started_at
          ? new Date(attempt.started_at).toLocaleString()
          : "N/A";
        const completedAt = attempt.completed_at
          ? new Date(attempt.completed_at).toLocaleString()
          : "Not completed";
        
        const score = attempt.score !== null && attempt.score !== undefined
          ? attempt.score.toFixed(1)
          : "0.0";
        const percentage =
          attempt.percentage !== null && attempt.percentage !== undefined
            ? attempt.percentage.toFixed(1)
            : "0.0";
        const duration =
          attempt.duration_minutes !== null
            ? Math.round(attempt.duration_minutes)
            : "N/A";

        // Determine status badge style
        const statusBadge = attempt.status === "completed"
          ? '<span class="quiz-badge badge-completed">Completed</span>'
          : '<span class="quiz-badge badge-in-progress">In Progress</span>';

        return `
        <div class="attempt-item">
          <div class="d-flex justify-content-between align-items-start">
            <div class="flex-grow-1">
              <div class="d-flex align-items-center gap-2 mb-2">
                <i class="bi bi-person-circle text-warning"></i>
                <strong>${
                  attempt.student ? attempt.student.username : "Unknown"
                }</strong>
                ${statusBadge}
              </div>
              <div class="small text-muted">
                <div class="mb-1">
                  <i class="bi bi-clock"></i> Started: ${startedAt}
                </div>
                <div class="mb-1">
                  <i class="bi bi-check-circle"></i> Completed: ${completedAt}
                </div>
                <div class="d-flex gap-3">
                  <span><i class="bi bi-star"></i> Score: ${score}/${
          attempt.max_score || 100
        } (${percentage}%)</span>
                  <span><i class="bi bi-hourglass-split"></i> Duration: ${duration} min</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      `;
      })
      .join("");
  } catch (error) {
    container.innerHTML =
      '<p class="text-danger text-center">Failed to load attempts</p>';
  }
}

// ========== Add Question ==========
async function showAddQuestionModal() {
  // Load available questions
  const select = document.getElementById("selectQuestion");
  select.innerHTML = '<option value="">Loading...</option>';

  try {
    const response = await authenticatedFetch(`${API_BASE}/quizzes/mine`);
    const data = await response.json();

    // Get all questions from all quizzes
    const allQuestions = [];
    for (const quiz of data.items || []) {
      const qResponse = await authenticatedFetch(
        `${API_BASE}/quizzes/${quiz.id}/questions`
      );
      const qData = await qResponse.json();
      allQuestions.push(...(qData.items || []));
    }

    // Remove duplicates and current quiz questions
    const currentQuestions = new Set();
    const currentResponse = await authenticatedFetch(
      `${API_BASE}/quizzes/${currentQuizId}/questions`
    );
    const currentData = await currentResponse.json();
    (currentData.items || []).forEach((q) => currentQuestions.add(q.id));

    const uniqueQuestions = allQuestions.filter(
      (q, index, self) =>
        index === self.findIndex((t) => t.id === q.id) &&
        !currentQuestions.has(q.id)
    );

    if (!uniqueQuestions.length) {
      select.innerHTML = '<option value="">No available questions</option>';
      return;
    }

    select.innerHTML = uniqueQuestions
      .map(
        (q) =>
          `<option value="${q.id}">${q.title} (${q.programming_language})</option>`
      )
      .join("");
  } catch (error) {
    select.innerHTML = '<option value="">Error loading questions</option>';
  }

  // Show modal
  const modal = new window.bootstrap.Modal(
    document.getElementById("addQuestionModal")
  );
  modal.show();
}

async function confirmAddQuestion() {
  const questionId = document.getElementById("selectQuestion").value;
  const points = document.getElementById("questionPoints").value;
  const order = document.getElementById("questionOrder").value;

  if (!questionId) {
    alert("Please select a question");
    return;
  }

  try {
    const response = await authenticatedFetch(
      `${API_BASE}/quizzes/${currentQuizId}/questions`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question_id: parseInt(questionId),
          points: parseInt(points),
          order: parseInt(order),
        }),
      }
    );

    if (response.ok) {
      const modal = window.bootstrap.Modal.getInstance(
        document.getElementById("addQuestionModal")
      );
      modal.hide();

      // Reload questions and refresh modal
      await refreshModalContent();
    } else {
      const error = await response.json();
      alert(error.message || "Failed to add question");
    }
  } catch (error) {
    alert("Failed to add question");
  }
}

// ========== Remove Question ==========
window.removeQuestion = async function (questionId) {
  if (
    !confirm("Are you sure you want to remove this question from the quiz?")
  ) {
    return;
  }

  try {
    const response = await authenticatedFetch(
      `${API_BASE}/quizzes/${currentQuizId}/questions/${questionId}`,
      { method: "DELETE" }
    );

    if (response.ok) {
      await refreshModalContent();
    } else {
      const error = await response.json();
      alert(error.message || "Failed to remove question");
    }
  } catch (error) {
    alert("Failed to remove question");
  }
};

// ========== Assign to Classroom ==========
async function showAssignClassroomModal() {
  // Load classrooms
  const select = document.getElementById("selectClassroom");
  select.innerHTML = '<option value="">Loading...</option>';

  try {
    const response = await authenticatedFetch(`${API_BASE}/classrooms/mine`);
    const data = await response.json();
    const classrooms = data.items || [];

    if (!classrooms.length) {
      select.innerHTML = '<option value="">No classrooms available</option>';
      return;
    }

    select.innerHTML =
      '<option value="">-- Select Classroom --</option>' +
      classrooms
        .map((c) => `<option value="${c.id}">${c.name} (${c.code})</option>`)
        .join("");
  } catch (error) {
    select.innerHTML = '<option value="">Error loading classrooms</option>';
  }

  // Show modal
  const modal = new window.bootstrap.Modal(
    document.getElementById("assignClassroomModal")
  );
  modal.show();
}

async function confirmAssign() {
  const classroomId = document.getElementById("selectClassroom").value;
  const dueDate = document.getElementById("assignmentDueDate").value;
  const allowLate = document.getElementById("allowLateSubmission").checked;

  if (!classroomId) {
    alert("Please select a classroom");
    return;
  }

  const payload = {
    classroom_id: parseInt(classroomId),
    allow_late_submission: allowLate,
  };

  if (dueDate) {
    payload.due_date = new Date(dueDate).toISOString();
  }

  try {
    const response = await authenticatedFetch(
      `${API_BASE}/quizzes/${currentQuizId}/assign`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }
    );

    if (response.ok) {
      const modal = window.bootstrap.Modal.getInstance(
        document.getElementById("assignClassroomModal")
      );
      modal.hide();

      // Clear form
      document.getElementById("assignmentDueDate").value = "";
      document.getElementById("allowLateSubmission").checked = false;

      // Reload assignments
      await loadQuizAssignments(currentQuizId);
    } else {
      const error = await response.json();
      alert(error.message || "Failed to assign quiz");
    }
  } catch (error) {
    alert("Failed to assign quiz");
  }
}

// ========== Unassign Classroom ==========
window.unassignClassroom = async function (classroomId) {
  if (
    !confirm(
      "Are you sure you want to unassign this quiz from the classroom?"
    )
  ) {
    return;
  }

  try {
    const response = await authenticatedFetch(
      `${API_BASE}/quizzes/${currentQuizId}/assign/${classroomId}`,
      { method: "DELETE" }
    );

    if (response.ok) {
      await loadQuizAssignments(currentQuizId);
    } else {
      const error = await response.json();
      alert(error.message || "Failed to unassign quiz");
    }
  } catch (error) {
    alert("Failed to unassign quiz");
  }
};

// ========== Toggle Publish Status ==========
async function togglePublish() {
  if (!currentQuizId) return;

  try {
    // Get current quiz
    const response = await authenticatedFetch(
      `${API_BASE}/quizzes/${currentQuizId}`
    );
    const quiz = await response.json();

    // Toggle publish status
    const updateResponse = await authenticatedFetch(
      `${API_BASE}/quizzes/${currentQuizId}`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          is_published: !quiz.is_published,
        }),
      }
    );

    if (updateResponse.ok) {
      // Reload quiz details
      await refreshModalContent();
      // Reload quiz list
      loadQuizzes();
    }
  } catch (error) {
    alert("Failed to update quiz");
  }
}

// ========== Delete Quiz ==========
async function deleteQuiz() {
  if (!currentQuizId) return;

  if (
    !confirm(
      "Are you sure you want to delete this quiz? This action cannot be undone."
    )
  ) {
    return;
  }

  try {
    const response = await authenticatedFetch(
      `${API_BASE}/quizzes/${currentQuizId}`,
      {
        method: "DELETE",
      }
    );

    if (response.ok) {
      // Close modal
      const modal = window.bootstrap.Modal.getInstance(
        document.getElementById("quizDetailModal")
      );
      modal.hide();

      // Reload quiz list
      await loadQuizzes();

      alert("Quiz deleted successfully");
    } else {
      const error = await response.json();
      alert(error.message || "Failed to delete quiz");
    }
  } catch (error) {
    alert("Failed to delete quiz");
  }
}

// ========== Initialize ==========
document.addEventListener("DOMContentLoaded", () => {
  loadQuizzes();

  // Create quiz button
  document.getElementById("createQuizBtn").addEventListener("click", () => {
    const modal = new window.bootstrap.Modal(
      document.getElementById("createQuizModal")
    );
    modal.show();
  });

  // Save quiz button
  document
    .getElementById("saveQuizBtn")
    .addEventListener("click", createQuiz);

  // Toggle publish button
  document
    .getElementById("togglePublishBtn")
    .addEventListener("click", togglePublish);

  // Delete quiz button
  document
    .getElementById("deleteQuizBtn")
    .addEventListener("click", deleteQuiz);

  // Add question button
  document
    .getElementById("addQuestionBtn")
    .addEventListener("click", showAddQuestionModal);

  // Confirm add question
  document
    .getElementById("confirmAddQuestionBtn")
    .addEventListener("click", confirmAddQuestion);

  // Assign to classroom button
  document
    .getElementById("assignToClassroomBtn")
    .addEventListener("click", showAssignClassroomModal);

  // Confirm assign
  document
    .getElementById("confirmAssignBtn")
    .addEventListener("click", confirmAssign);
});
