describe("Dashboard problem list", () => {
  it("shows one problem row with a language dropdown and defaults row click to Python", () => {
    cy.intercept("GET", "**/api/v1/problems*", { fixture: "public/problems.json" }).as("problems");
    cy.intercept("GET", "**/api/v1/metrics/overview", {
      body: { global: { questions: 1, quizzes: 0, active_users: 0, submissions_24h: 0 } },
    });
    cy.intercept("GET", "**/api/public/quizzes", { body: { items: [], total: 0 } });
    cy.intercept("GET", "**/api/v1/quizzes", { body: { items: [], total: 0 } });

    cy.visit("/dashboard");
    cy.wait("@problems");
    cy.contains("td", "Add Two Numbers").should("exist");
    cy.get("[data-problem-language='1']").should("have.value", "python");
    cy.get("[data-problem-row='1']").click();
    cy.location("pathname").should("eq", "/problem/1");
    cy.location("search").should("contain", "language=python");
  });
});
