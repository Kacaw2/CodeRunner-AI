describe("Teacher grade reports", () => {
  beforeEach(() => {
    cy.seedDatabase();
    cy.loginByApi("teacher");

    cy.intercept("GET", "**/api/v1/grades/students/summary", {
      fixture: "teacher/grades_students_summary.json",
    }).as("studentsSummary");

    cy.intercept("GET", "**/api/v1/grades/submissions*", (req) => {
      const { limit, student_id } = req.query;

      if (limit === "1000") {
        req.reply({ fixture: "teacher/grades_submissions_bootstrap.json" });
        req.alias = "submissionsBootstrap";
        return;
      }

      if (student_id === "501") {
        req.reply({ fixture: "teacher/grades_submissions_student1.json" });
        req.alias = "submissionsStudent";
        return;
      }

      req.reply({ fixture: "teacher/grades_submissions_all.json" });
      req.alias = "submissionsPage";
    });

    cy.intercept("GET", "**/api/v1/grades/export/csv", {
      statusCode: 200,
      body: "student,score\nstudent1,85",
      headers: { "content-type": "text/csv" },
    }).as("exportCsv");
  });

  it("displays summary metrics and student cards", () => {
    cy.visit("/teacher/grades");
    cy.wait(["@studentsSummary", "@submissionsBootstrap", "@submissionsPage"]);

    cy.get("#totalStudents").should("have.text", "2");
    cy.get("#totalSubmissions").should("have.text", "8");
    cy.get("#averageScore").should("contain.text", "78.5%");
    cy.get("#completionRate").should("contain.text", "75.0%");

    cy.contains("#studentSummaryContainer .student-summary-card", "student1")
      .should("exist")
      .within(() => {
        cy.contains("5").should("exist");
        cy.contains("98%").should("exist");
      });

    cy.contains("#submissionsCardsContainer .submission-item", "Array Prefix Sum")
      .should("exist")
      .within(() => {
        cy.contains("student1").should("exist");
        cy.contains("Passed").should("exist");
      });
  });

  it("filters submissions and exports CSV", () => {
    cy.visit("/teacher/grades");
    cy.wait(["@studentsSummary", "@submissionsBootstrap", "@submissionsPage"]);

    cy.contains("button", "All Submissions").click();
    cy.get("#filterStudent").should("be.visible").select("student1");
    cy.get("#applyFilters").click();
    cy.wait("@submissionsStudent");

    cy.get("#submissionsCardsContainer .submission-item").should(
      "have.length",
      1
    );
    cy.contains("#submissionsCardsContainer .submission-item", "student1").should(
      "exist"
    );

    cy.get("#clearFilters").click();
    cy.wait("@submissionsPage");

    cy.get("#exportCsvBtn").click();
    cy.get("#exportCsvBtn").should("be.disabled");
    cy.wait("@exportCsv");
    cy.get("#exportCsvBtn").should("not.be.disabled");
  });

  it("displays an error card when the student summary API fails", () => {
    let summaryCalls = 0;
    cy.intercept("GET", "**/api/v1/grades/students/summary", (req) => {
      summaryCalls += 1;
      if (summaryCalls === 3) {
        req.reply({ statusCode: 500, body: { message: "summary down" } });
      } else {
        req.reply({ fixture: "teacher/grades_students_summary.json" });
      }
    }).as("studentsSummary");

    cy.visit("/teacher/grades");

    cy.contains("#studentSummaryContainer", "Failed to load student summary").should(
      "be.visible"
    );
  });

  it("shows a failure state when submissions cannot be loaded", () => {
    cy.intercept("GET", "**/api/v1/grades/submissions*", (req) => {
      const { limit } = req.query || {};
      if (limit === "1000") {
        req.reply({ fixture: "teacher/grades_submissions_bootstrap.json" });
        req.alias = "submissionsBootstrap";
        return;
      }

      req.reply({
        statusCode: 500,
        body: { message: "submissions offline" },
      });
      req.alias = "submissionsPage";
    });

    cy.visit("/teacher/grades");
    cy.contains("button", "All Submissions").click();

    cy.contains("#submissionsCardsContainer", "Failed to load submissions")
      .should("be.visible");
  });

  it("alerts when CSV export fails", () => {
    cy.intercept("GET", "**/api/v1/grades/export/csv", {
      statusCode: 500,
      body: "error",
    }).as("exportCsvFailure");

    cy.visit("/teacher/grades");
    cy.wait(["@studentsSummary", "@submissionsBootstrap", "@submissionsPage"]);

    const alertStub = cy.stub();
    cy.on("window:alert", alertStub);

    cy.get("#exportCsvBtn").click().then(() => {
      expect(alertStub).to.have.been.calledWith(
        "Failed to export CSV. Please try again."
      );
    });
    cy.wait("@exportCsvFailure");
    cy.get("#exportCsvBtn").should("not.be.disabled");
  });
});
