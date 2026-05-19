const classroomsListFixture = require("../../fixtures/teacher/classrooms_list.json");
const classroomDetailFixture = require("../../fixtures/teacher/classroom_detail.json");
const classroomStudentsFixture = require("../../fixtures/teacher/classroom_students.json");
const allStudentsFixture = require("../../fixtures/teacher/all_students.json");

describe("Teacher classrooms page", () => {
  let classroomsData;

  beforeEach(() => {
    cy.seedDatabase();
    cy.loginByApi("teacher");

    classroomsData = JSON.parse(JSON.stringify(classroomsListFixture));

    cy.intercept("GET", "**/api/v1/classrooms/mine", (req) => {
      req.reply(classroomsData);
    }).as("classrooms");

    cy.intercept("GET", "**/api/v1/classrooms/201", {
      fixture: "teacher/classroom_detail.json",
    }).as("classroomDetail");

    cy.intercept("GET", "**/api/v1/classrooms/201/students", {
      fixture: "teacher/classroom_students.json",
    }).as("classroomStudents");

    cy.intercept("GET", "**/api/v1/classrooms/all-students", {
      fixture: "teacher/all_students.json",
    }).as("allStudents");
  });

  it("lists classrooms and opens classroom detail modal", () => {
    cy.visit("/teacher/classrooms");
    cy.wait("@classrooms");

    cy.get(".classroom-card").should("have.length", classroomsData.items.length);
    cy.contains(".classroom-card", "COMP1511").click();

    cy.wait(["@classroomDetail", "@classroomStudents", "@allStudents"]);

    cy.get("#classroomDetailModal").should("have.class", "show");
    cy.get("#classroomDetailTitle").should(
      "contain.text",
      classroomDetailFixture.name
    );
    cy.get("#classroomCode").should("have.text", classroomDetailFixture.code);
    cy.get("#studentCount").should(
      "have.text",
      String(classroomStudentsFixture.items.length)
    );
    cy.contains("#currentStudentsList .student-name", "student1").should(
      "exist"
    );
    cy.contains("#allStudentsList .student-name", "student3").should("exist");
  });

  it("creates a new classroom via the modal", () => {
    cy.intercept("POST", "**/api/v1/classrooms", (req) => {
      const payload =
        typeof req.body === "string" ? JSON.parse(req.body) : req.body;
      expect(payload).to.deep.include({
        name: "COMP2511 Tutorials",
        description: "Advanced OOP practice",
      });

      const newClassroom = {
        id: 250,
        name: payload.name,
        description: payload.description,
        code: "NEW-2511",
        student_count: 0,
        created_at: new Date().toISOString(),
      };
      classroomsData.items.push(newClassroom);

      req.reply({
        statusCode: 201,
        body: newClassroom,
      });
    }).as("createClassroom");

    cy.visit("/teacher/classrooms");
    cy.wait("@classrooms");

    cy.get("#openCreateModalBtn").click();
    cy.get("#createClassroomModal").should("have.class", "show");
    cy.get("#classroomName").type("COMP2511 Tutorials");
    cy.get("#classroomDescription").type("Advanced OOP practice");
    cy.get("#createClassroomBtn").click();

    cy.wait("@createClassroom");
    cy.wait("@classrooms");
    cy.contains(".classroom-card", "COMP2511 Tutorials").should("exist");
  });

  it("shows an inline error when the classrooms API fails", () => {
    cy.intercept(
      {
        method: "GET",
        url: "**/api/v1/classrooms/mine",
        times: 1,
      },
      {
        statusCode: 500,
        body: { message: "Database down" },
      },
    ).as("classroomsError");

    cy.visit("/teacher/classrooms");
    cy.wait("@classroomsError");

    cy.get("#classroomsList .alert.alert-danger")
      .should("be.visible")
      .and("contain.text", "Failed to load classrooms");
  });
});
