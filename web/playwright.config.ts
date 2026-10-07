import { defineConfig, devices } from "@playwright/test";

// Runs against the offline Compose stack that `make e2e` starts (replay provider, zero spend).
// 127.0.0.1, not localhost: web publishes on IPv4 loopback only, and localhost may resolve to ::1.
export default defineConfig({
  testDir: "./e2e",
  // Every test has its own browser context (and so its own sessionStorage thread); the replay streams run concurrently.
  fullyParallel: true,
  // A recorded stream replays in about 8–13 s end to end, so a test that waits for one or two results needs more than the default 30 s.
  timeout: 90_000,
  expect: { timeout: 20_000 },
  forbidOnly: Boolean(process.env.CI),
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:3000",
    // Off for MEDIA=1: the trace recorder would be the page's first screencast client and fix every frame at 800 px wide.
    trace: process.env.MEDIA === "1" ? "off" : "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } } }],
});
