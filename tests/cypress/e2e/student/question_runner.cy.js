describe("Student question runner", () => {
  beforeEach(() => {
    cy.loginByApi("student");
    cy.intercept("GET", "**/api/v1/problems/1?language=python", {
      fixture: "student/question_solution.json",
    }).as("problemDetail");
    cy.visit("/problem/1?language=python");
    cy.wait("@problemDetail");
  });

  it("runs a custom test case and shows the results", () => {
    cy.intercept("POST", "**/api/v1/judge/run", {
      fixture: "student/judge_result.json",
    }).as("judgeRun");

    cy.get(".case-inputs .input-param textarea")
      .first()
      .clear()
      .type("1 2 3");

    cy.get(".CodeMirror").first().click();
    cy.get(".CodeMirror textarea")
      .first()
      .type("{selectall}print(sum(map(int, input().split())))", {
        force: true,
      });

    cy.get("#runBtn").click();
    cy.wait("@judgeRun");

    cy.get("#runResults")
      .should("contain.text", "Test Case 1")
      .and("contain.text", "Your Output")
      .and("contain.text", "1 3 6");
  });

  it("surfaces API errors when the judge service is unavailable", () => {
    cy.intercept("POST", "**/api/v1/judge/run", {
      statusCode: 500,
      body: { message: "Sandbox offline" },
    }).as("judgeRunError");

    cy.get(".case-inputs .input-param textarea").first().clear().type("4 5 6");

    cy.get(".CodeMirror").first().click();
    cy.get(".CodeMirror textarea")
      .first()
      .type("{selectall}print(sum(map(int, input().split())))", {
        force: true,
      });

    cy.get("#runBtn").click();
    cy.wait("@judgeRunError");

    cy.get("#runResults .error-output")
      .scrollIntoView()
      .should("be.visible")
      .and("contain.text", "Sandbox offline");
  });

  it("displays the unlocked solution tab content", () => {
    cy.contains(".editor-tab", "Solution").click();
    cy.get("#solutionUnlocked").should("be.visible");
    cy.get("#solutionCode").should("contain.text", "def prefix");
  });
});
