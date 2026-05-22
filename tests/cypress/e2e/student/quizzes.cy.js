describe("Student quizzes workspace", () => {
  before(() => {
    cy.seedDatabase();
  });

  beforeEach(() => {
    cy.loginByApi("student");
    cy.intercept("GET", "**/api/v1/quizzes/", {
      fixture: "student/quizzes.json",
    }).as("quizzes");
  });

  it("lists assigned quizzes with progress badges", () => {
    cy.visit("/student/quizzes");
    cy.wait("@quizzes");

    cy.get("#quiz-list .quiz-card").should("have.length", 3);
    cy.contains(".quiz-card", "Week 3 Arrays").within(() => {
      cy.contains("1/2 problems completed").should("exist");
      cy.contains("In Progress").should("exist");
    });
    cy.contains(".quiz-card", "Week 4 Pointers").within(() => {
      cy.contains("Overdue").should("exist");
    });
    cy.contains(".quiz-card", "Week 5 Recursion").within(() => {
      cy.contains("Completed").should("exist");
    });
  });

  it("shows quiz detail view when clicking a card", () => {
    cy.intercept("GET", "**/api/v1/quizzes/201", {
      fixture: "student/quiz_detail_201.json",
    }).as("quizDetail");

    cy.visit("/student/quizzes");
    cy.wait("@quizzes");

    cy.contains(".quiz-card", "Week 3 Arrays")
      .find("button.view-quiz-btn")
      .click();

    cy.wait("@quizDetail");

    cy.get("#quiz-detail-view").should("be.visible");
    cy.get("#detail-title").should("contain.text", "Week 3 Arrays");
    cy.get("#detail-progress-text").should("contain.text", "1/2 problems completed");
    cy.get("#detail-questions .question-item").should("have.length", 2);
    cy.contains("#detail-questions .question-item", "Array Prefix Sum").within(() => {
      cy.contains("Review").should("exist");
      cy.contains("Review")
        .should("have.attr", "href", "/problem/870?language=python");
    });

    cy.get("#back-to-list").click();
    cy.get("#quiz-list-view").should("be.visible");
  });

  it("shows an alert when the quiz list API fails", () => {
    cy.intercept("GET", "**/api/v1/quizzes/", {
      statusCode: 500,
      body: { message: "quizzes unavailable" },
    }).as("quizzesError");

    cy.visit("/student/quizzes");
    cy.wait("@quizzesError");

    cy.get("#quiz-list .alert.alert-danger")
      .should("be.visible")
      .and("contain.text", "Failed to load quizzes");
  });

  it("alerts the user if quiz details cannot be loaded", () => {
    cy.intercept("GET", "**/api/v1/quizzes/", {
      fixture: "student/quizzes.json",
    }).as("quizzes");
    cy.intercept("GET", "**/api/v1/quizzes/201", {
      statusCode: 500,
      body: { message: "detail error" },
    }).as("quizDetailError");

    cy.visit("/student/quizzes");
    cy.wait("@quizzes");

    const alertStub = cy.stub();
    cy.on("window:alert", alertStub);

    cy.contains(".quiz-card", "Week 3 Arrays")
      .find("button.view-quiz-btn")
      .click();

    cy.wait("@quizDetailError");
    cy.wrap(null).then(() => {
      expect(alertStub).to.have.been.calledWith(
        "Failed to load quiz details. Please try again."
      );
    });
  });
});
