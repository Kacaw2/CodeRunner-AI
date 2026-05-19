const { defineConfig } = require("cypress");
const { execSync } = require("child_process");

module.exports = defineConfig({
  e2e: {
    setupNodeEvents(on, config) {
      on("task", {
        seedDatabase() {
          try {
            execSync(
              "docker-compose -f docker/docker-compose.yml exec -T web python -m app.core.init_db --drop --seed --force",
              {
                stdio: "inherit",
                cwd: process.cwd(),
              }
            );
            return null;
          } catch (error) {
            throw new Error(`Database init failed: ${error.message}`);
          }
        },
      });

      return config;
    },
    
    // base URL
    baseUrl: "http://localhost:9900",
    
    specPattern: "tests/cypress/e2e/**/*.cy.{js,jsx,ts,tsx}",
    
    fixturesFolder: "tests/cypress/fixtures",
    
    supportFile: "tests/cypress/support/e2e.js",
    
    viewportWidth: 1280,
    viewportHeight: 720,
    video: true,
    screenshotOnRunFailure: true,
    
    defaultCommandTimeout: 10000,
    requestTimeout: 10000,
    responseTimeout: 10000,
  },
});
