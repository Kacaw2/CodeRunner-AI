describe("Student profile dashboard", () => {
  before(() => {
    cy.seedDatabase();
  });

  beforeEach(() => {
    cy.loginByApi("student");
  });

  it("renders statistics and recent submissions", () => {
    cy.intercept("GET", "**/api/v1/auth/me", {
      fixture: "student/me.json",
    }).as("me");
    cy.intercept("GET", "**/api/v1/submissions/mine", {
      fixture: "student/submissions.json",
    }).as("submissions");

    cy.visit("/student/profile");
    cy.wait(["@me", "@submissions"]);

    cy.get("#sp-name").should("contain.text", "student1");
    cy.get("#sp-total-submissions").should("have.text", "3");
    cy.get("#sp-passed").should("have.text", "1");
    cy.get("#sp-failed").should("have.text", "2");
    cy.get("#sp-success-rate").should("have.text", "33%");

    cy.get("#sp-tbody tr").should("have.length", 3);
    cy.contains("#sp-tbody tr", "Array Prefix Sum").within(() => {
      cy.contains(".badge", "Passed").should("exist");
      cy.contains("View").should("have.attr", "href", "/submissions/501");
    });
  });

  it("updates email through the modal form", () => {
    let meCalls = 0;
    cy.intercept("GET", "**/api/v1/auth/me", (req) => {
      meCalls += 1;
      if (meCalls === 1) {
        req.reply({ fixture: "student/me.json" });
      } else {
        req.reply({
          id: 101,
          username: "student1",
          email: "student+qa@bread.dev",
          role: "student",
          created_at: "2024-02-01T10:00:00",
        });
      }
    }).as("me");
    cy.intercept("GET", "**/api/v1/submissions/mine", {
      fixture: "student/submissions.json",
    }).as("submissions");
    cy.intercept("PUT", "**/api/v1/profile/email", (req) => {
      const payload =
        typeof req.body === "string" ? JSON.parse(req.body) : req.body;
      expect(payload).to.deep.equal({ email: "student+qa@bread.dev" });
      req.reply({
        statusCode: 200,
        body: {
          id: 101,
          username: "student1",
          email: payload.email,
        },
      });
    }).as("updateEmail");

    cy.visit("/student/profile");
    cy.wait(["@me", "@submissions"]);

    cy.contains("button", "Edit Profile").click();
    cy.get("#editProfileModal").should("have.class", "show");

    cy.get("#new-email")
      .clear()
      .type("student+qa@bread.dev", { delay: 0 })
      .should("have.value", "student+qa@bread.dev");
    cy.contains("#email-form button", "Update Email").click();

    cy.wait("@updateEmail");
    cy.get("#email-success")
      .should("be.visible")
      .and("contain.text", "Email updated successfully!");

    cy.wait("@me"); // refreshed profile data
    cy.get("#sp-email").should("contain.text", "student+qa@bread.dev");
  });

  it("shows a failure message when submissions API errors", () => {
    cy.intercept("GET", "**/api/v1/auth/me", {
      fixture: "student/me.json",
    }).as("me");
    cy.intercept("GET", "**/api/v1/submissions/mine", {
      statusCode: 500,
      body: { message: "submissions unavailable" },
    }).as("submissions");

    cy.visit("/student/profile");
    cy.wait(["@me", "@submissions"]);

    cy.contains("#sp-tbody", "Failed to load submissions").should("be.visible");
  });

  it("displays an inline error when updating email fails", () => {
    cy.intercept("GET", "**/api/v1/auth/me", {
      fixture: "student/me.json",
    }).as("me");
    cy.intercept("GET", "**/api/v1/submissions/mine", {
      fixture: "student/submissions.json",
    }).as("submissions");
    cy.intercept("PUT", "**/api/v1/profile/email", {
      statusCode: 400,
      body: { message: "Email already exists" },
    }).as("updateEmailError");

    cy.visit("/student/profile");
    cy.wait(["@me", "@submissions"]);

    cy.contains("button", "Edit Profile").click();
    cy.get("#editProfileModal").should("have.class", "show");
    cy.get("#new-email").clear().type("student1@bread.dev");
    cy.contains("#email-form button", "Update Email").click();

    cy.wait("@updateEmailError");
    cy.get("#email-error")
      .should("be.visible")
      .and("contain.text", "Email already exists");
  });

  it("validates username length before submitting", () => {
    cy.intercept("GET", "**/api/v1/auth/me", {
      fixture: "student/me.json",
    }).as("me");
    cy.intercept("GET", "**/api/v1/submissions/mine", {
      fixture: "student/submissions.json",
    }).as("submissions");

    cy.visit("/student/profile");
    cy.wait(["@me", "@submissions"]);

    cy.contains("button", "Edit Profile").click();
    cy.get("#editProfileModal").should("have.class", "show");
    cy.get("#username-tab-btn").click();

    cy.get("#new-username").clear().type("xy");
    cy.get("#username-password").type("admin123");
    cy.contains("#username-form button", "Update Username").click();

    cy.get("#username-error")
      .should("be.visible")
      .and("contain.text", "Username must be at least 3 characters");
  });

  it("shows password mismatch and short password messages", () => {
    cy.intercept("GET", "**/api/v1/auth/me", {
      fixture: "student/me.json",
    }).as("me");
    cy.intercept("GET", "**/api/v1/submissions/mine", {
      fixture: "student/submissions.json",
    }).as("submissions");

    cy.visit("/student/profile");
    cy.wait(["@me", "@submissions"]);

    cy.contains("button", "Edit Profile").click();
    cy.get("#editProfileModal").should("have.class", "show");
    cy.get("#password-tab-btn").click();

    cy.get("#current-password").type("admin123");
    cy.get("#new-password").type("abcdef");
    cy.get("#confirm-password").type("abcdeg");
    cy.contains("#password-form button", "Update Password").click();

    cy.get("#password-error")
      .should("be.visible")
      .and("contain.text", "New passwords do not match");

    cy.get("#new-password").clear().type("123");
    cy.get("#confirm-password").clear().type("123");
    cy.contains("#password-form button", "Update Password").click();

    cy.get("#password-error")
      .should("be.visible")
      .and("contain.text", "New password must be at least 6 characters");
  });
});
