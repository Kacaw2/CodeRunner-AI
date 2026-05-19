// ============================================================
// Classrooms Management - JavaScript Module (Fixed Layout)
// ============================================================

import { getToken, authenticatedFetch } from "/static/js/auth.js";

// ============================================================
// Constants and State
// ============================================================

const API_BASE = "/api/v1";
let currentClassroomId = null;
let currentClassroomCode = null;
let allStudents = [];

// ============================================================
// Authentication Check
// ============================================================

const token = getToken();
if (!token) {
  window.location.href = "/auth/login?next=/teacher/classrooms";
}

// ============================================================
// Load Classrooms
// ============================================================

async function loadClassrooms() {
  const container = document.getElementById("classroomsList");

  try {
    const response = await authenticatedFetch(`${API_BASE}/classrooms/mine`);
    const data = await response.json();

    if (!response.ok) {
      throw new Error(data?.message || "Failed to load classrooms");
    }

    const classrooms = data.items || [];

    // Empty state
    if (!classrooms.length) {
      container.innerHTML = `
        <div class="col-12">
          <div class="empty-state">
            <i class="bi bi-inbox" style="font-size: 3rem; opacity: 0.3;"></i>
            <h5 class="mt-3">No classrooms yet</h5>
            <p class="text-muted">Create your first classroom to get started</p>
            <button class="btn btn-primary" id="emptyCreateBtn">
              <i class="bi bi-plus-circle"></i> Create Classroom
            </button>
          </div>
        </div>
      `;

      // Add event listener for empty state button
      const emptyBtn = document.getElementById("emptyCreateBtn");
      if (emptyBtn) {
        emptyBtn.addEventListener("click", () => {
          const modal = new window.bootstrap.Modal(
            document.getElementById("createClassroomModal")
          );
          modal.show();
        });
      }
      return;
    }

    // Render classroom cards with fixed height
    container.innerHTML = classrooms
      .map(
        (classroom) => `
      <div class="col-md-6 col-lg-4">
        <div class="classroom-card" onclick="viewClassroom(${classroom.id})">
          <div class="d-flex justify-content-between align-items-start mb-1">
            <h5 class="card-title">${classroom.name}</h5>
            <span class="badge-success-custom">
              ${classroom.student_count} students
            </span>
          </div>
          <p class="card-text">
            ${classroom.description || "No description"}
          </p>
          <div class="mb-1 d-flex align-items-center">
            <span class="classroom-code">
              ${classroom.code}
            </span>
              <small class="text-muted ms-auto">
                <i class="bi bi-calendar"></i>
                ${
                  classroom.created_at
                    ? new Date(classroom.created_at).toLocaleDateString()
                    : "N/A"
                }
            </small>
          </div>
        </div>
      </div>
    `
      )
      .join("");
  } catch (error) {
    container.innerHTML =
      '<div class="col-12"><div class="alert alert-danger">Failed to load classrooms</div></div>';
  }
}

// ============================================================
// View Classroom Details
// ============================================================

window.viewClassroom = async function (classroomId) {
  currentClassroomId = classroomId;

  try {
    const response = await authenticatedFetch(
      `${API_BASE}/classrooms/${classroomId}`
    );
    const classroom = await response.json();

    currentClassroomCode = classroom.code;

    // Update modal content
    document.getElementById("classroomDetailTitle").textContent =
      classroom.name;
    document.getElementById("classroomDetailDescription").textContent =
      classroom.description || "No description";
    document.getElementById("classroomCode").textContent = classroom.code;

    // Load students
    await loadCurrentStudents(classroomId);
    await loadAllStudents();

    // Show modal
    const modal = new window.bootstrap.Modal(
      document.getElementById("classroomDetailModal")
    );
    modal.show();
  } catch (error) {
    alert("Failed to load classroom details");
  }
};

// ============================================================
// Create Classroom
// ============================================================

async function createClassroom() {
  const name = document.getElementById("classroomName").value.trim();
  const description = document
    .getElementById("classroomDescription")
    .value.trim();

  if (!name) {
    alert("Please enter a classroom name");
    return;
  }

  try {
    const response = await authenticatedFetch(`${API_BASE}/classrooms`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, description }),
    });

    if (response.ok) {
      // Close modal
      const modal = window.bootstrap.Modal.getInstance(
        document.getElementById("createClassroomModal")
      );
      modal.hide();

      // Clear form
      document.getElementById("createClassroomForm").reset();

      // Reload classrooms
      await loadClassrooms();

      alert("Classroom created successfully!");
    } else {
      const error = await response.json();
      alert(error.message || "Failed to create classroom");
    }
  } catch (error) {
    alert("Failed to create classroom. Please try again.");
  }
}

// ============================================================
// Load Current Students
// ============================================================

async function loadCurrentStudents(classroomId) {
  const container = document.getElementById("currentStudentsList");

  try {
    const response = await authenticatedFetch(
      `${API_BASE}/classrooms/${classroomId}/students`
    );
    const data = await response.json();

    const students = data.items || [];
    document.getElementById("studentCount").textContent = students.length;

    if (!students.length) {
      container.innerHTML =
        '<p class="text-center text-muted py-4">No students yet. Add students using the "Add Students" tab.</p>';
      return;
    }

    container.innerHTML = students
      .map(
        (student) => `
      <div class="student-item">
        <div class="d-flex justify-content-between align-items-center">
          <div class="student-info">
            <div class="student-name">${student.username}</div>
            <div class="student-email">${student.email || "No email"}</div>
          </div>
          <button class="btn btn-sm btn-outline-danger remove-student-btn" data-student-id="${
            student.id
          }">
            <i class="bi bi-x-circle"></i> Remove
          </button>
        </div>
      </div>
    `
      )
      .join("");

    // Add remove handlers
    document.querySelectorAll(".remove-student-btn").forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        const studentId = e.target.closest(".remove-student-btn").dataset
          .studentId;
        if (
          confirm(
            "Are you sure you want to remove this student from the classroom?"
          )
        ) {
          await removeStudent(classroomId, parseInt(studentId));
        }
      });
    });
  } catch (error) {
    container.innerHTML =
      '<p class="text-center text-danger">Failed to load students</p>';
  }
}

// ============================================================
// Load All Students (for adding)
// ============================================================

async function loadAllStudents() {
  const container = document.getElementById("allStudentsList");

  try {
    const response = await authenticatedFetch(
      `${API_BASE}/classrooms/all-students`
    );
    const data = await response.json();

    allStudents = data.items || [];
    renderAllStudents(allStudents);
  } catch (error) {
    container.innerHTML =
      '<p class="text-center text-danger">Failed to load students</p>';
  }
}

// ============================================================
// Render All Students List (Fixed Layout)
// ============================================================

function renderAllStudents(students) {
  const container = document.getElementById("allStudentsList");

  if (!students.length) {
    container.innerHTML =
      '<p class="text-center text-muted">No students available</p>';
    return;
  }

  container.innerHTML = students
    .map((student) => {
      const inCurrentClassroom =
        student.classrooms &&
        student.classrooms.some((c) => c.id === currentClassroomId);
      
      // Build classroom badges HTML with better layout
      let classroomBadgesHtml = '';
      if (student.classrooms && student.classrooms.length > 0) {
        const badgesArray = student.classrooms.map(
          (c) => `<span class="badge badge-classroom">${c.name}</span>`
        );
        classroomBadgesHtml = `
          <div class="student-classrooms">
            ${badgesArray.join('')}
          </div>
        `;
      }

      return `
      <div class="student-item">
        <div class="d-flex justify-content-between align-items-start gap-3">
          <div class="student-info">
            <div class="student-name">${student.username}</div>
            <div class="student-email">${student.email || "No email"}</div>
            ${classroomBadgesHtml}
          </div>
          <div class="d-flex align-items-center" style="margin-top: 0.25rem;">
            ${
              inCurrentClassroom
                ? '<span class="badge bg-success">Already in this classroom</span>'
                : `<button class="btn btn-sm btn-outline-primary add-student-btn" data-student-id="${student.id}">
                <i class="bi bi-plus-circle"></i> Add
              </button>`
            }
          </div>
        </div>
      </div>
    `;
    })
    .join("");

  // Add click handlers
  document.querySelectorAll(".add-student-btn").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      const studentId = e.target.closest(".add-student-btn").dataset.studentId;
      await addStudent(currentClassroomId, parseInt(studentId));
    });
  });
}

// ============================================================
// Add Student to Classroom
// ============================================================

async function addStudent(classroomId, studentId) {
  try {
    const response = await authenticatedFetch(
      `${API_BASE}/classrooms/${classroomId}/students/${studentId}`,
      { method: "POST" }
    );

    if (response.ok) {
      await loadCurrentStudents(classroomId);
      await loadAllStudents();

      // Switch to students tab
      document.getElementById("students-tab").click();
    } else {
      const error = await response.json();
      alert(error.message || "Failed to add student");
    }
  } catch (error) {
    alert("Failed to add student. Please try again.");
  }
}

// ============================================================
// Remove Student from Classroom
// ============================================================

async function removeStudent(classroomId, studentId) {
  try {
    const response = await authenticatedFetch(
      `${API_BASE}/classrooms/${classroomId}/students/${studentId}`,
      { method: "DELETE" }
    );

    if (response.ok) {
      await loadCurrentStudents(classroomId);
      await loadAllStudents();
    } else {
      const error = await response.json();
      alert(error.message || "Failed to remove student");
    }
  } catch (error) {
    alert("Failed to remove student. Please try again.");
  }
}

// ============================================================
// Delete Classroom
// ============================================================

async function deleteClassroom() {
  if (!currentClassroomId) return;

  if (
    !confirm(
      "Are you sure you want to delete this classroom? All students will be removed from it."
    )
  ) {
    return;
  }

  try {
    const response = await authenticatedFetch(
      `${API_BASE}/classrooms/${currentClassroomId}`,
      {
        method: "DELETE",
      }
    );

    if (response.ok) {
      // Close modal
      const modalElement = document.getElementById("classroomDetailModal");
      const modal = window.bootstrap.Modal.getInstance(modalElement);
      if (modal) {
        modal.hide();
      }

      // Reload classrooms
      await loadClassrooms();

      alert("Classroom deleted successfully!");
    } else {
      const error = await response.json();
      alert(error.message || "Failed to delete classroom");
    }
  } catch (error) {
    alert("Failed to delete classroom. Please try again.");
  }
}

// ============================================================
// Initialize Event Listeners
// ============================================================

document.addEventListener("DOMContentLoaded", () => {

  // Load classrooms on page load
  loadClassrooms();

  // Create classroom modal button
  const openCreateBtn = document.getElementById("openCreateModalBtn");
  if (openCreateBtn) {
    openCreateBtn.addEventListener("click", () => {
      const modal = new window.bootstrap.Modal(
        document.getElementById("createClassroomModal")
      );
      modal.show();
    });
  }

  // Create classroom button
  const createBtn = document.getElementById("createClassroomBtn");
  if (createBtn) {
    createBtn.addEventListener("click", createClassroom);
  }

  // Delete classroom button
  const deleteBtn = document.getElementById("deleteClassroomBtn");
  if (deleteBtn) {
    deleteBtn.addEventListener("click", deleteClassroom);
  }

  // Copy code button
  const copyBtn = document.getElementById("copyCodeBtn");
  if (copyBtn) {
    copyBtn.addEventListener("click", () => {
      if (currentClassroomCode) {
        navigator.clipboard.writeText(currentClassroomCode).then(() => {
          const originalHtml = copyBtn.innerHTML;
          copyBtn.innerHTML = '<i class="bi bi-check"></i>';
          setTimeout(() => {
            copyBtn.innerHTML = originalHtml;
          }, 2000);
        });
      }
    });
  }

  // Search students input
  const searchInput = document.getElementById("searchStudents");
  if (searchInput) {
    searchInput.addEventListener("input", (e) => {
      const query = e.target.value.toLowerCase();
      const filtered = allStudents.filter(
        (s) =>
          s.username.toLowerCase().includes(query) ||
          (s.email && s.email.toLowerCase().includes(query))
      );
      renderAllStudents(filtered);
    });
  }
});
