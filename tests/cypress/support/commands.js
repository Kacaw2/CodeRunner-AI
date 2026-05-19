/**
 * @typedef {"teacher" | "student"} SupportedRole
 */

Cypress.Commands.add("loginByApi", (role = "teacher") => {
  /** @type {{ username?: string; password?: string }} */
  const credentials =
    role === "teacher"
      ? {
          username: Cypress.env("teacherUser"),
          password: Cypress.env("teacherPassword"),
        }
      : {
          username: Cypress.env("studentUser"),
          password: Cypress.env("studentPassword"),
        };

  if (!credentials.username || !credentials.password) {
    throw new Error(`Missing credentials for role "${role}". Update cypress.env.json.`);
  }

  const loginUrl = `${Cypress.env("apiUrl")}/auth/login`;

  return cy.request("POST", loginUrl, credentials).then(({ body }) => {
    const token = body && body.token;
    expect(token, "JWT token").to.be.a("string").and.have.length.greaterThan(10);

    cy.window().then((win) => {
      win.localStorage.setItem("token", token);
    });
  });
});

Cypress.Commands.add("seedDatabase", () => {
  return cy.task("seedDatabase");
});

