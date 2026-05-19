const visitTeacherProfile = () => {
  cy.visit("/teacher/profile");
  cy.wait(["@me", "@stats", "@recentQuestions"]);
};

describe("Teacher profile dashboard", () => {
  beforeEach(() => {
    cy.seedDatabase();
    cy.loginByApi("teacher");

    cy.intercept("GET", "**/api/v1/auth/me", {
      fixture: "teacher/me.json",
    }).as("me");
    cy.intercept("GET", "**/api/v1/teacher/stats", {
      fixture: "teacher/stats.json",
    }).as("stats");
    cy.intercept("GET", "**/api/v1/questions/mine*", {
      fixture: "teacher/recent_questions.json",
    }).as("recentQuestions");
  });

  it("shows welcome banner, info, stats, and quick actions", () => {
    visitTeacherProfile();

    cy.contains(".welcome-banner h2", "Welcome back").should("be.visible");
    cy.get("#t-name").should("have.text", "teacher1");
    cy.get("#t-email").should("contain.text", "teacher1@bread.dev");

    cy.get("#stat-questions").should("have.text", "42");
    cy.get("#stat-classrooms").should("have.text", "3");
    cy.get("#stat-students").should("have.text", "118");

    cy.get(".quick-actions__item").should("have.length", 4);
    const actions = [
      "Create Question",
      "Manage Classrooms",
      "View Students",
      "Grade Reports",
    ];
    actions.forEach((text) => {
      cy.contains(".quick-actions__item", text).should("be.visible");
    });
  });

  it("renders recent published questions with actions", () => {
    visitTeacherProfile();

    cy.get("#recent-questions-tbody tr").should("have.length", 2);
    cy.contains("#recent-questions-tbody tr", "Binary Search Warmup").within(
      () => {
        cy.contains("td", "#101").should("exist");
        cy.contains(".badge", /python/i).should("exist");
        cy.contains(".badge", "Easy").should("exist");
        cy.get(".btn-action").should("have.length", 3);
      }
    );
  });

  it("updates email through the profile modal", () => {
    let meCalls = 0;
    cy.intercept("GET", "**/api/v1/auth/me", (req) => {
      meCalls += 1;
      if (meCalls === 1) {
        req.reply({ fixture: "teacher/me.json" });
      } else {
        req.reply({
          id: 1,
          username: "teacher1",
          email: "teacher+qa@bread.dev",
          role: "teacher",
        });
      }
    }).as("me");

    cy.intercept("PUT", "**/api/v1/profile/email", (req) => {
      const payload =
        typeof req.body === "string" ? JSON.parse(req.body) : req.body;
      expect(payload).to.deep.equal({ email: "teacher+qa@bread.dev" });
      req.reply({
        statusCode: 200,
        body: {
          id: 1,
          username: "teacher1",
          email: payload.email,
        },
      });
    }).as("updateEmail");

    visitTeacherProfile();

    cy.contains("button", "Edit Profile").click();
    cy.get("#editProfileModal").should("have.class", "show");

    cy.get("#new-email")
      .clear()
      .type("teacher+qa@bread.dev", { delay: 0 })
      .should("have.value", "teacher+qa@bread.dev");
    cy.contains("#email-form button", "Update Email").click();

    cy.wait("@updateEmail");
    cy.get("#email-success")
      .should("be.visible")
      .and("contain.text", "Email updated successfully!");

    cy.wait("@me");
    cy.get("#t-email").should("contain.text", "teacher+qa@bread.dev");
  });

  it("shows fallback values when stats or recent questions fail", () => {
    cy.intercept("GET", "**/api/v1/teacher/stats", {
      statusCode: 500,
      body: { message: "stats offline" },
    }).as("stats");
    cy.intercept("GET", "**/api/v1/questions/mine*", {
      statusCode: 500,
      body: { message: "recent questions down" },
    }).as("recentQuestions");

    visitTeacherProfile();

    cy.get("#stat-questions").should("have.text", "-");
    cy.get("#stat-classrooms").should("have.text", "-");
    cy.get("#stat-students").should("have.text", "-");

    cy.get("#recent-questions-tbody")
      .find("td")
      .first()
      .should("contain.text", "Failed to load questions");
  });

  it("surfaces validation errors when updating email fails", () => {
    cy.intercept("PUT", "**/api/v1/profile/email", {
      statusCode: 400,
      body: { message: "Email already taken" },
    }).as("updateEmailError");

    visitTeacherProfile();

    cy.contains("button", "Edit Profile").click();
    cy.get("#editProfileModal").should("have.class", "show");
    cy.get("#new-email")
      .clear()
      .type("teacher1+dup@bread.dev", { delay: 0 })
      .then(($input) => {
        if ($input.val() !== "teacher1+dup@bread.dev") {
          cy.wrap($input)
            .invoke("val", "teacher1+dup@bread.dev")
            .trigger("input");
        }
      });
    cy.contains("#email-form button", "Update Email").click();

    cy.wait("@updateEmailError");
    cy.get("#email-error")
      .should("be.visible")
      .and("contain.text", "Email already taken");
  });

  it("warns when the new email matches the current email", () => {
    visitTeacherProfile();

    cy.contains("button", "Edit Profile")
      .should("be.visible")
      .click();
    cy.get("#editProfileModal").should("have.class", "show");
    cy.get("#new-email")
      .clear()
      .type("teacher1@bread.dev", { delay: 0 })
      .then(($input) => {
        if ($input.val() !== "teacher1@bread.dev") {
          cy.wrap($input)
            .invoke("val", "teacher1@bread.dev")
            .trigger("input");
        }
      });
    cy.get("#new-email").should("have.value", "teacher1@bread.dev");
    cy.contains("#email-form button", "Update Email").click();

    cy.get("#email-error")
      .should("be.visible")
      .and("contain.text", "New email is the same as current email");
    cy.loginByApi("teacher");
  });

  it("shows a validation error when the username is too short", () => {
    visitTeacherProfile();

    cy.contains("button", "Edit Profile").click();
    cy.get("#editProfileModal").should("have.class", "show");
    cy.get("#username-tab-btn").click();

    cy.get("#new-username").clear().type("ab");
    cy.get("#username-password").type("admin123");
    cy.contains("#username-form button", "Update Username").click();

    cy.get("#username-error")
      .should("be.visible")
      .and("contain.text", "Username must be at least 3 characters");
  });

  it("surfaces password mismatch and length errors", () => {
    visitTeacherProfile();

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

describe("Teacher profile access control", () => {
  it("redirects unauthenticated visitors to the login page", () => {
    cy.clearLocalStorage();
    cy.visit("/teacher/profile", { failOnStatusCode: false });
    cy.location("pathname").should("eq", "/auth/login");
    cy.location("search").should(
      "eq",
      "?next=http://localhost:9900/teacher/profile"
    );
    cy.loginByApi("teacher");
  });
});
