const quizzesListFixture = require("../../fixtures/teacher/quizzes_list.json");

describe("Teacher quizzes page", () => {
  let quizzesData;

  beforeEach(() => {
    cy.seedDatabase();
    cy.loginByApi("teacher");

    quizzesData = JSON.parse(JSON.stringify(quizzesListFixture));

    cy.intercept("GET", "**/api/v1/quizzes", (req) => {
      req.reply(quizzesData);
    }).as("quizzesList");

    cy.intercept("GET", "**/api/v1/quizzes/301", {
      fixture: "teacher/quiz_detail.json",
    }).as("quizDetail");

    cy.intercept("GET", "**/api/v1/quizzes/301/questions", {
      fixture: "teacher/quiz_questions.json",
    }).as("quizQuestions");

    cy.intercept("GET", "**/api/v1/quizzes/301/assignments", {
      fixture: "teacher/quiz_assignments.json",
    }).as("quizAssignments");

    cy.intercept("GET", "**/api/v1/quizzes/301/attempts", {
      fixture: "teacher/quiz_attempts.json",
    }).as("quizAttempts");
  });

  it("renders quiz cards with publish state and stats", () => {
    cy.visit("/teacher/quizzes");
    cy.wait("@quizzesList");

    cy.get(".quiz-card").should("have.length", quizzesData.items.length);
    cy.contains(".quiz-card", "Week 6 Sorting").within(() => {
      cy.contains("Published").should("exist");
      cy.contains("4 questions").should("exist");
      cy.contains("80 points").should("exist");
    });
    cy.contains(".quiz-card", "Week 7 Graphs")
      .contains("Draft")
      .should("exist");
  });

  it("opens quiz detail modal and loads tabs", () => {
    cy.visit("/teacher/quizzes");
    cy.wait("@quizzesList");

    cy.contains(".quiz-card", "Week 6 Sorting").click();
    cy.wait(["@quizDetail", "@quizQuestions", "@quizAssignments", "@quizAttempts"]);

    cy.get("#quizDetailModal").should("have.class", "show");
    cy.get("#quizDetailTitle").should("contain.text", "Week 6 Sorting");
    cy.contains("#questionsList .question-item", "Array Prefix Sum").should(
      "exist"
    );
    cy.contains("button", "Assignments").click();
    cy.contains("#assignmentsList .assignment-item", "COMP1511").should(
      "exist"
    );
    cy.contains("button", "Attempts").click();
    cy.contains("#attemptsList .attempt-item", "Completed").should("exist");
  });

  it("creates a new quiz via the modal", () => {
    cy.intercept("POST", "**/api/v1/quizzes", (req) => {
      const payload =
        typeof req.body === "string" ? JSON.parse(req.body) : req.body;
      expect(payload).to.deep.include({
        title: "Week 10 Review",
        description: "Capstone revision",
        is_published: true,
      });

      const newQuiz = {
        id: 399,
        ...payload,
        question_count: 0,
        total_points: 0,
        assigned_to_count: 0,
      };
      quizzesData.items.push(newQuiz);

      req.reply({
        statusCode: 201,
        body: newQuiz,
      });
    }).as("createQuiz");

    cy.visit("/teacher/quizzes");
    cy.wait("@quizzesList");

    cy.get("#createQuizBtn").click();
    cy.get("#createQuizModal").should("have.class", "show");
    cy.get("#quizTitle").type("Week 10 Review");
    cy.get("#quizDescription").type("Capstone revision");
    cy.get("#quizDuration").type("30");
    cy.get("#quizPublished").check();
    cy.get("#saveQuizBtn").click();

    cy.wait("@createQuiz");
    cy.wait("@quizzesList");
    cy.contains(".quiz-card", "Week 10 Review").should("exist");
  });

  it("displays an error alert when the quiz list request fails", () => {
    cy.intercept("GET", "**/api/v1/quizzes", {
      statusCode: 500,
      body: { message: "quizzes offline" },
    }).as("quizzesError");

    cy.visit("/teacher/quizzes");
    cy.wait("@quizzesError");

    cy.get("#quizzesList .alert.alert-danger")
      .should("be.visible")
      .and("contain.text", "Failed to load quizzes");
  });
});
