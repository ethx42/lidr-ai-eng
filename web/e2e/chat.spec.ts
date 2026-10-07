import { spawnSync } from "node:child_process";
import { copyFileSync, mkdirSync } from "node:fs";
import path from "node:path";
import AxeBuilder from "@axe-core/playwright";
import { type Locator, type Page, expect, test } from "@playwright/test";

// Screenshots and the GIF are written only with MEDIA=1 (`MEDIA=1 make e2e`), so a plain run never dirties tracked files.
const MEDIA = process.env.MEDIA === "1";
const MEDIA_DIR = path.join(__dirname, "..", "..", "docs", "media", "session-03");
if (MEDIA) mkdirSync(MEDIA_DIR, { recursive: true });

// Its replay cassette streams for about 12 s, long enough to act mid-stream.
const SAMPLE = "Clinic portal";
const WCAG = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

const shot = async (page: Page, name: string) => {
  // "disabled" finishes transitions (a tab mid-switch) and stops the skeleton pulse
  if (MEDIA) await page.screenshot({ path: path.join(MEDIA_DIR, `${name}.png`), animations: "disabled" });
};

// Playwright video → GIF with ffmpeg; without ffmpeg the .webm itself is kept.
const saveGif = (webm: string) => {
  const ffmpeg = spawnSync("ffmpeg", [
    "-y", "-loglevel", "error", "-i", webm,
    "-vf", "fps=8,scale=800:-1:flags=lanczos,split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=5",
    path.join(MEDIA_DIR, "chat.gif"),
  ]);
  if (ffmpeg.error) return copyFileSync(webm, path.join(MEDIA_DIR, "chat.webm"));
  expect(ffmpeg.status, ffmpeg.stderr.toString()).toBe(0);
};

const expectAccessible = async (page: Page, state: string) => {
  const { violations } = await new AxeBuilder({ page }).withTags(WCAG).analyze();
  const blocking = violations
    .filter(({ impact }) => impact === "serious" || impact === "critical")
    .map(({ id, impact, nodes }) => ({ id, impact, targets: nodes.map(({ target }) => target.join(" ")) }));
  expect(blocking, `serious or critical axe violations (${state})`).toEqual([]);
};

const expectNoHorizontalScroll = async (page: Page) => {
  const overflow = await page.evaluate(() =>
    [document.documentElement, ...document.querySelectorAll("main")].map((element) => element.scrollWidth - element.clientWidth),
  );
  expect(overflow, "horizontal overflow of the page and the scrolling thread, in px").toEqual(overflow.map(() => 0));
};

// Waits for open and close animations (the sheet's 150 ms fade and slide) before axe or focus checks.
const settled = (locator: Locator) =>
  locator.evaluate((element) => Promise.all(element.getAnimations({ subtree: true }).map((animation) => animation.finished)));

const composer = (page: Page) => page.getByRole("textbox", { name: "Meeting transcript" });
const sampleCard = (page: Page) => page.getByRole("button", { name: SAMPLE, exact: true });
const estimate = (page: Page) => page.getByRole("article");
const projectName = (page: Page) => estimate(page).getByRole("heading", { level: 2 });
const totals = (page: Page) => estimate(page).locator("header dl");
const stopped = (page: Page) => page.getByRole("status").filter({ hasText: "Stopped" });
const valueOf = (scope: Locator, label: string) => scope.locator(`dt:text-is("${label}") + dd`);

// The sample cards render once the thread has hydrated from sessionStorage.
const pickSample = async (page: Page) => {
  await sampleCard(page).click();
  await expect(composer(page)).toHaveValue(/physiotherapy/i);
};

const sendSample = async (page: Page) => {
  await pickSample(page);
  await page.getByRole("button", { name: "Estimate", exact: true }).click();
};

// A partial render: the project name has streamed in while the totals, computed server-side and sent only with the
// result, are still skeletons. Checked in one pass in the page, so both hold at the same moment.
const expectPartial = (page: Page) =>
  expect
    .poll(
      () =>
        page.evaluate(() => {
          const article = document.querySelector("article[aria-busy=true]");
          return Boolean(article?.querySelector("h2:not(.sr-only)")?.textContent && article.querySelector("header dl [data-slot=skeleton]"));
        }),
      { message: "partial render: project name streamed in, totals still skeletons" },
    )
    .toBe(true);

const expectResult = async (page: Page) => {
  await expect(estimate(page).getByRole("status")).toHaveText("Estimate ready");
  await expect(estimate(page)).toHaveAttribute("aria-busy", "false");
  await expect(totals(page).locator("[data-slot=skeleton]")).toHaveCount(0);
  await expect(totals(page)).toContainText(/Expected\s*[\d,.]+ h/);
};

const openLastCall = async (scope: Locator) => {
  await scope.getByRole("tab", { name: "Last call" }).click();
  return scope.getByRole("tabpanel", { name: "Last call" });
};

test.describe("chat", () => {
  test.use({ permissions: ["clipboard-read", "clipboard-write"] });

  test("streams a sample estimate, copies it as markdown and shows the call in the inspector", async ({ page }, testInfo) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 2, name: /^Paste a meeting transcript/ })).toBeVisible();
    await expect(page.getByRole("list", { name: "Sample transcripts" }).getByRole("button")).toHaveCount(3);
    const inspector = page.getByRole("complementary", { name: "Inspector" });
    await expect(inspector.getByRole("region", { name: "System prompt" })).toContainText("<role>");
    await shot(page, "empty-state");
    const video = testInfo.outputPath("chat.webm");
    if (MEDIA) await page.screencast.start({ path: video, size: { width: 1280, height: 800 } });

    const response = page.waitForResponse((res) => res.url().endsWith("/api/estimate/stream"));
    await sendSample(page);
    const requestId = (await response).headers()["x-request-id"];
    expect(requestId).toBeTruthy();

    const progress = page.getByRole("list", { name: "Progress" });
    await expect(progress).toBeVisible();
    await expect(progress.getByRole("listitem")).toHaveText(["Contacting the model", "Drafting the estimate", "Checking the estimate"].map((step) => new RegExp(step)));
    await expect(page.getByRole("button", { name: "Stop", exact: true })).toBeVisible();
    await expectPartial(page);
    await shot(page, "streaming");

    await expectResult(page);
    await expect(projectName(page)).toHaveText(/\S/);
    const tasks = estimate(page).getByRole("table");
    await expect(tasks.getByRole("columnheader")).toHaveText(["Task", "Range", "Expected"]);
    await expect(tasks.locator("th[scope=row]").first()).toBeVisible();

    const call = await openLastCall(inspector);
    await expect(valueOf(call, "Provider")).toHaveText("Replay");
    await expect(valueOf(call, "Model")).toHaveText("replay");
    await expect(valueOf(call, "Request ID").locator("code")).toHaveText(requestId);
    await shot(page, "result-inspector");

    await estimate(page).getByRole("button", { name: /^Evidence for / }).first().hover();
    const evidence = page.locator("[data-slot=hover-card-content]");
    await expect(evidence).toBeVisible();
    await expect(evidence).toContainText(/Quote (from the transcript|given by the model)/);
    await expect(evidence.locator("blockquote")).toHaveText(/“.+”/);
    await page.mouse.move(0, 0);
    await expect(evidence).toBeHidden();

    await page.getByRole("button", { name: "Copy as markdown" }).click();
    await expect(page.getByText("Estimate copied as markdown")).toBeVisible();
    const markdown = await page.evaluate(() => navigator.clipboard.readText());
    expect(markdown.split("\n")[0]).toBe(`## Estimation: ${await projectName(page).textContent()}`);
    expect(markdown).toContain("| ID | Phase | Task |");
    if (MEDIA) {
      await page.screencast.stop();
      saveGif(video);
    }
  });

  test("Stop keeps the partial estimate and Regenerate runs it again", async ({ page }) => {
    await page.goto("/");
    await sendSample(page);
    await expectPartial(page);
    await page.getByRole("button", { name: "Stop", exact: true }).click();

    await expect(stopped(page)).toBeVisible();
    await expect(estimate(page)).toHaveAttribute("aria-busy", "false");
    await expect(projectName(page)).toHaveText(/\S/);
    await expect(totals(page).locator("[data-slot=skeleton]").first()).toBeVisible();
    const regenerate = page.getByRole("button", { name: "Regenerate" });
    await expect(regenerate).toBeFocused(); // Stop is gone, so focus moves to the message's next action

    await regenerate.click();
    await expect(page.getByRole("button", { name: "Stop", exact: true })).toBeVisible();
    await expect(stopped(page)).toHaveCount(0);
    await expectResult(page);
    await expect(page.getByRole("button", { name: "Copy as markdown" })).toBeVisible();
  });

  test("a reload restores the completed turn", async ({ page }) => {
    await page.goto("/");
    await sendSample(page);
    await expectResult(page);
    const name = await projectName(page).textContent();
    const expected = await totals(page).textContent();

    await page.reload();
    await expect(page.getByRole("list", { name: "Estimates" }).locator(":scope > li")).toHaveCount(1);
    await expect(projectName(page)).toHaveText(name ?? "");
    await expect(totals(page)).toHaveText(expected ?? "");
    await expect(page.getByRole("button", { name: "Copy as markdown" })).toBeVisible();
    const call = await openLastCall(page.getByRole("complementary", { name: "Inspector" }));
    await expect(valueOf(call, "Provider")).toHaveText("Replay");
  });

  test("keyboard only: Tab reaches the composer, Ctrl/Cmd+Enter sends and Esc stops", async ({ page }) => {
    await page.goto("/");
    await expect(sampleCard(page)).toBeVisible();
    const input = composer(page);
    const focused = (locator: Locator) => locator.evaluate((element) => element === document.activeElement);
    for (let presses = 0; presses < 20 && !(await focused(input)); presses++) await page.keyboard.press("Tab");
    await expect(input).toBeFocused();

    // The sample comes from the Samples menu next to the textarea, by keyboard as well.
    await page.keyboard.press("Tab");
    await expect(page.getByRole("button", { name: "Samples" })).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("menuitem").first()).toBeFocused();
    const item = page.getByRole("menuitem", { name: new RegExp(`^${SAMPLE}`) });
    for (let presses = 0; presses < 3 && !(await focused(item)); presses++) await page.keyboard.press("ArrowDown");
    await page.keyboard.press("Enter");
    await expect(input).toBeFocused();
    await expect(input).toHaveValue(/physiotherapy/i);

    await page.keyboard.press("ControlOrMeta+Enter");
    await expect(page.getByRole("button", { name: "Stop", exact: true })).toBeVisible();
    await expect(input).toBeFocused();
    await expectPartial(page);
    await page.keyboard.press("Escape");
    await expect(stopped(page)).toBeVisible();
    await expect(page.getByRole("button", { name: "Stop", exact: true })).toHaveCount(0);
  });
});

for (const colorScheme of ["light", "dark"] as const) {
  test.describe(`${colorScheme} theme`, () => {
    test.use({ colorScheme });

    test(`no serious or critical axe violations when empty, streaming and done (${colorScheme})`, async ({ page }) => {
      await page.goto("/");
      await expect(page.locator("html")).toHaveClass(new RegExp(`\\b${colorScheme}\\b`));
      await expect(sampleCard(page)).toBeVisible();
      await expectAccessible(page, "empty");

      // The enabled Estimate button fades in from its disabled opacity; axe mid-transition reports a false contrast failure.
      await pickSample(page);
      await settled(page.getByRole("form", { name: "New estimate" }));
      await expectAccessible(page, "sample picked");
      // axe checks contrast in the state it finds: hovered, the primary button must keep 4.5:1 too
      const estimateButton = page.getByRole("button", { name: "Estimate", exact: true });
      await estimateButton.hover();
      await settled(estimateButton);
      await expectAccessible(page, "Estimate hovered");

      await estimateButton.click();
      await expectPartial(page);
      await expectAccessible(page, "streaming");

      await expectResult(page);
      await expectAccessible(page, "done");
      await openLastCall(page.getByRole("complementary", { name: "Inspector" }));
      await expectAccessible(page, "done, Last call tab");
      if (colorScheme === "dark") await shot(page, "dark-theme");
    });
  });
}

test.describe("375 px wide", () => {
  test.use({ viewport: { width: 375, height: 812 } });

  test("the inspector opens as a sheet and nothing scrolls horizontally", async ({ page }) => {
    await page.goto("/");
    await expect(sampleCard(page)).toBeVisible();
    await expect(page.getByRole("complementary", { name: "Inspector" })).toBeHidden();
    await expectNoHorizontalScroll(page);

    await sendSample(page);
    await expectResult(page);
    await expectNoHorizontalScroll(page);
    await shot(page, "mobile");

    const trigger = page.getByRole("button", { name: "Inspector" });
    await trigger.click();
    const sheet = page.getByRole("dialog", { name: "Inspector" });
    await expect(sheet).toBeVisible();
    await settled(sheet);
    const call = await openLastCall(sheet);
    await expect(valueOf(call, "Provider")).toHaveText("Replay");
    await expectNoHorizontalScroll(page);
    await expectAccessible(page, "inspector sheet");

    await page.keyboard.press("Escape");
    await expect(sheet).toHaveCount(0);
    await expect(trigger).toBeFocused();
  });
});
