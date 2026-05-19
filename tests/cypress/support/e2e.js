require("./commands");

Cypress.on("uncaught:exception", (err) => {
  if (err.message && err.message.includes("ResizeObserver")) {
    return false;
  }
});
