const quizzesFixture = require("../../fixtures/teacher/quizzes.json");
const workspaceQuestionsFixture = require("../../fixtures/teacher/workspace_questions.json");

const visitWorkspace = () => {
  cy.visit("/teacher/questions/create");
  cy.wait(["@quizzes", "@teacherQuestions"]);
};

describe("Teacher question workspace", () => {
  let quizzes;
  let workspaceQuestions;

  beforeEach(() => {
    cy.seedDatabase();
    cy.loginByApi("teacher");

    quizzes = JSON.parse(JSON.stringify(quizzesFixture));
    workspaceQuestions = JSON.parse(JSON.stringify(workspaceQuestionsFixture));

    cy.intercept("GET", "**/api/v1/quizzes", (req) => {
      req.reply(quizzes);
    }).as("quizzes");

    cy.intercept("GET", "**/api/v1/teacher/problems*", (req) => {
      req.reply(workspaceQuestions);
    }).as("teacherQuestions");
  });

  it("lists quizzes, toggles creator filter, and searches problems", () => {
    visitWorkspace();

    cy.get("#quizSelect option").should("have.length", quizzes.items.length + 1);
    cy.get("#questionCount").should("contain.text", "3");

    cy.contains("#creatorFilterBtn", "All Problems")
      .click()
      .should("contain.text", "My Problems");
    cy.wait("@teacherQuestions");

    cy.get("#searchInput").type("Stack");
    cy.wait(400);
    cy.contains("#qTableBody tr", "Stack Balancer").should("be.visible");
    cy.get("#qTableBody tr").should("have.length", 1);
  });

  it("creates quizzes and problems", () => {
    cy.intercept("POST", "**/api/v1/quizzes", (req) => {
      const payload =
        typeof req.body === "string" ? JSON.parse(req.body) : req.body;
      const newQuiz = { id: 77, title: payload.title };
      quizzes.items.push(newQuiz);
      req.reply({ statusCode: 201, body: newQuiz });
    }).as("createQuiz");

    cy.intercept("POST", "**/api/v1/problems", (req) => {
      const payload =
        typeof req.body === "string" ? JSON.parse(req.body) : req.body;
      expect(payload).to.include.keys("python_starter_code", "python_solution", "c_starter_code", "c_solution");
      const newQuestion = {
        id: 990,
        title: payload.title,
        description: payload.description,
        variants: [
          { language: "python", question_id: 1990 },
          { language: "c", question_id: 1991 }
        ],
        test_case_count: 0,
        quiz_ids: payload.quiz_id ? [payload.quiz_id] : [],
      };
      workspaceQuestions.items.unshift(newQuestion);
      req.reply({ statusCode: 201, body: newQuestion });
    }).as("createQuestion");

    visitWorkspace();

    cy.get("#createQuizBtn").click();
    cy.get("#createQuizModal").should("have.class", "show");
    cy.get("#createQuizTitle").type("Week 9 Graph Theory");
    cy.get("#saveCreateQuizBtn").click();

    cy.wait("@createQuiz");
    cy.wait("@quizzes");
    cy.get("#quizSelect").should("have.value", "77");
    cy.get("#qQuizSelect").should("have.value", "77");

    cy.get("#qTitle").type("Topological Sort Paths");
    cy.get("#qDesc").type("Describe the number of valid topological orders.");
    cy.contains("button", "Create Problem").click();

    cy.wait("@createQuestion");
    cy.wait("@teacherQuestions");
    cy.contains("#qTableBody tr", "Topological Sort Paths").should("exist");
  });

  it("deletes problems and refreshes table", () => {
    cy.intercept("DELETE", "**/api/v1/problems/905", {
      statusCode: 204,
      body: {},
    }).as("deleteQuestion");

    visitWorkspace();
    cy.contains("#qTableBody tr", "Stack Balancer")
      .find("[data-delete='905']")
      .click();

    cy.on("window:confirm", () => true);
    cy.wait("@deleteQuestion");
    cy.wait("@teacherQuestions");
  });

  it("prevents submitting the form when required fields are empty", () => {
    visitWorkspace();

    cy.get("#qTitle").clear();
    cy.get("#qDesc").clear();
    cy.get("#createBtn").click();

    cy.get("#msg").should("contain.text", "Title and description are required");
  });

  it("shows a helpful error when the problem API returns a failure", () => {
    cy.intercept("POST", "**/api/v1/problems", {
      statusCode: 500,
      body: { message: "Database unavailable" },
    }).as("createQuestionError");

    visitWorkspace();

    cy.get("#qTitle").type("Unhappy Path Question");
    cy.get("#qDesc").type("Force the creation endpoint to fail");
    cy.contains("button", "Create Problem").click();

    cy.wait("@createQuestionError");
    cy.get("#msg")
      .should("be.visible")
      .and("contain.text", "Database unavailable");
  });
});

describe("Teacher question test-case management", () => {
  let detailState;

  beforeEach(() => {
    cy.seedDatabase();
    cy.loginByApi("teacher");
    detailState = "initial";
    cy.intercept("GET", "**/api/v1/problems/870/manage*", (req) => {
      if (detailState === "initial") {
        req.reply({ fixture: "teacher/manage_question/detail.json" });
      } else if (detailState === "afterAdd") {
        req.reply({
          fixture: "teacher/manage_question/test_cases_after_add.json",
        });
      } else {
        req.reply({
          fixture: "teacher/manage_question/test_cases_after_delete.json",
        });
      }
    }).as("questionDetail");

    cy.intercept("POST", "**/api/v1/problems/870/test-cases", (req) => {
      detailState = "afterAdd";
      req.reply({
        statusCode: 201,
        fixture: "teacher/manage_question/test_case_new.json",
      });
    }).as("createTestCase");

    cy.intercept("DELETE", "**/api/v1/test-cases/5002", (req) => {
      detailState = "afterDelete";
      req.reply({
        statusCode: 200,
        fixture: "teacher/manage_question/test_case_deleted.json",
      });
    }).as("deleteTestCase");
  });

  it("adds and deletes test cases", () => {
    cy.visit("/teacher/problems/870/manage");
    cy.wait("@questionDetail");

    cy.get("#problemTitleInput").should("have.value", "Array Prefix Sum");
    cy.get("#testCaseCount").should("contain.text", "2 test cases");

    cy.get("#tcInput").type("8 8");
    cy.get("#tcExpected").type("8 16");
    cy.get("#tcHidden").select("false");
    cy.get("#tcWeight").clear().type("0.5");
    cy.get("#addTcBtn").click();

    cy.wait("@createTestCase");
    cy.wait("@questionDetail");
    cy.contains("#testCasesContainer .testcase-item", "Test Case #3").should(
      "exist"
    );

    cy.window().then((win) => {
      cy.stub(win, "confirm").returns(true);
    });

    cy.contains("#testCasesContainer .testcase-item", "Test Case #2")
      .scrollIntoView()
      .find("[data-delete-tc='5002']")
      .click();
    cy.wait("@deleteTestCase");
    cy.wait("@questionDetail");

    cy.contains("#testCasesContainer .testcase-item", "5 5").should("not.exist");
  });
});
