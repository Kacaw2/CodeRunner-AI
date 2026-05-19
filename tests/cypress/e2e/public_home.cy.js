describe("Public home", () => {
  it("renders hero copy and CTA links", () => {
    cy.visit("/");

    cy.contains("h1", /Keep your coding practice simple/i).should("be.visible");
    cy.get(".home-hero__lead").should("contain.text", "codeRunner");

    cy.get(".home-hero__actions .btn")
      .first()
      .should("have.attr", "href", "/auth/login");

    cy.get(".home-steps__item").should("have.length", 4);
  });

  it("passes the health check endpoint", () => {
    cy.request("/healthz").its("body").should("deep.equal", { ok: true });
  });
});

