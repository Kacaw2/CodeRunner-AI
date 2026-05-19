describe("Authentication", () => {
  beforeEach(() => {
    cy.clearLocalStorage();
    cy.visit("/auth/login");
  });

  it("shows a validation message when credentials are invalid", () => {
    cy.intercept("POST", "**/api/v1/auth/login").as("login");

    cy.get("#login-username").type("teacher1");
    cy.get("#login-password").type("wrong-password");
    cy.get("#btn-login").click();

    cy.wait("@login").its("response.statusCode").should("eq", 401);
    cy.get("#login-msg").should("be.visible").and("not.be.empty");
  });

  it("stores the JWT token and redirects on success", () => {
    cy.intercept("POST", "**/api/v1/auth/login").as("login");

    cy.get("#login-username").type(Cypress.env("teacherUser"));
    cy.get("#login-password").type(Cypress.env("teacherPassword"), {
      log: false,
    });
    cy.get("#btn-login").click();

    cy.wait("@login").its("response.statusCode").should("eq", 200);
    cy.location("pathname").should("eq", "/");
    cy.window()
      .its("localStorage")
      .invoke("getItem", "token")
      .should("be.a", "string")
      .and("have.length.greaterThan", 10);
  });
});

