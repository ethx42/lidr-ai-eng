import { spawnSync } from "node:child_process";
import { copyFileSync, mkdirSync } from "node:fs";
import path from "node:path";
import AxeBuilder from "@axe-core/playwright";
import { type Locator, type Page, expect, test } from "@playwright/test";

// Screenshots and the GIF are written only with MEDIA=1 (`MEDIA=1 make e2e`), so a plain run never dirties tracked files.
const MEDIA = process.env.MEDIA === "1";
const MEDIA_DIR = path.join(__dirname, "..", "..", "docs", "media", "session-04");
if (MEDIA) mkdirSync(MEDIA_DIR, { recursive: true });

// Its replay cassette (default choices, default prompt version) streams for about 13 s end to end, long enough to act
// mid-stream. Other choices get a stream synthesised from a fixture estimate.
const SAMPLE = "Clinic portal";
// WCAG 2.2 AA plus axe's best practices; only serious and critical findings fail the run.
const AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"];
const PHASES = ["Discovery", "UX/UI", "Backend", "Frontend", "Integrations", "QA", "DevOps", "Project management"];

const shot = async (page: Page, name: string) => {
  // "disabled" finishes transitions (a tab mid-switch) and stops the skeleton pulse
  if (MEDIA) await page.screenshot({ path: path.join(MEDIA_DIR, `${name}.png`), animations: "disabled" });
};

// Playwright video → GIF with ffmpeg; without ffmpeg the .webm itself is kept.
const saveGif = (webm: string) => {
  const ffmpeg = spawnSync("ffmpeg", [
    "-y", "-loglevel", "error", "-i", webm,
    "-vf", "fps=8,scale=800:-1:flags=lanczos,split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=5",
    path.join(MEDIA_DIR, "estimate.gif"),
  ]);
  if (ffmpeg.error) return copyFileSync(webm, path.join(MEDIA_DIR, "estimate.webm"));
  expect(ffmpeg.status, ffmpeg.stderr.toString()).toBe(0);
};

const expectAccessible = async (page: Page, state: string) => {
  const { violations } = await new AxeBuilder({ page }).withTags(AXE_TAGS).analyze();
  const blocking = violations
    .filter(({ impact }) => impact === "serious" || impact === "critical")
    .map(({ id, impact, nodes }) => ({ id, impact, targets: nodes.map(({ target }) => target.join(" ")) }));
  expect(blocking, `serious or critical axe violations (${state})`).toEqual([]);
};

const expectNoHorizontalScroll = async (page: Page) => {
  const overflow = await page.evaluate(() =>
    [document.documentElement, ...document.querySelectorAll("main")].map((element) => element.scrollWidth - element.clientWidth),
  );
  expect(overflow, "horizontal overflow of the page and the scrolling workspace, in px").toEqual(overflow.map(() => 0));
};

// Waits for open and close animations (the sheet's 150 ms fade and slide) before axe or focus checks.
const settled = (locator: Locator) =>
  locator.evaluate((element) => Promise.all(element.getAnimations({ subtree: true }).map((animation) => animation.finished)));

// The px of an element in view: its box clipped by every scrolling or clipping ancestor and by the viewport.
const visibleHeight = (element: Element) => {
  let { top, bottom } = element.getBoundingClientRect();
  for (let parent = element.parentElement; parent; parent = parent.parentElement) {
    if (getComputedStyle(parent).overflowY === "visible") continue;
    const box = parent.getBoundingClientRect();
    [top, bottom] = [Math.max(top, box.top), Math.min(bottom, box.bottom)];
  }
  return Math.max(0, Math.min(bottom, window.innerHeight) - Math.max(top, 0));
};

const transcript = (page: Page) => page.getByRole("textbox", { name: "Transcript" });
const estimateButton = (page: Page) => page.getByRole("button", { name: "Estimate", exact: true });
const estimate = (page: Page) => page.getByRole("article");
// Side by side (from 768 px) each pane is a group named by its heading.
const estimatePane = (page: Page) => page.getByRole("group", { name: "Estimate", exact: true });
const transcriptPane = (page: Page) => page.getByRole("region", { name: "Submitted transcript" });
const projectName = (page: Page) => estimate(page).getByRole("heading", { level: 2 });
const totals = (page: Page) => estimate(page).locator("header dl");
const stopped = (page: Page) => page.getByRole("status").filter({ hasText: /^Stopped/ });
// Announces how a run ends while the estimate sits behind the Transcript tab (below 768 px).
const runStatus = (page: Page) => page.locator("[data-slot=run-status]");
const valueOf = (scope: Locator, label: string) => scope.locator(`dt:text-is("${label}") + dd`);
// A Range over the text has one client rect per line it spans. The element's own rects do not count lines: a flex item
// (the request ID's <code>) is a single box however its text wraps.
const lineCount = (element: Element) => {
  const range = document.createRange();
  range.selectNodeContents(element);
  return range.getClientRects().length;
};
const expectOneLine = async (locator: Locator, what: string) => expect(await locator.evaluate(lineCount), `${what} on one line`).toBe(1);

const choose = async (page: Page, group: string, option: string) => {
  const radio = page.getByRole("radiogroup", { name: group }).getByRole("radio", { name: option, exact: true });
  await radio.click();
  await expect(radio).toBeChecked();
};

const pickSample = async (page: Page) => {
  await page.getByRole("button", { name: "Load sample" }).click();
  await expect(page.getByRole("menuitem")).toHaveCount(3);
  await page.getByRole("menuitem", { name: new RegExp(`^${SAMPLE}`) }).click();
  await expect(transcript(page)).toHaveValue(/physiotherapy/i);
  await expect(page.getByRole("menu")).toHaveCount(0);
};

const sendSample = async (page: Page) => {
  await pickSample(page);
  await estimateButton(page).click();
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

const expectResult = async (page: Page, { timeout }: { timeout?: number } = {}) => {
  await expect(estimate(page).getByRole("status")).toHaveText("Estimate ready", { timeout });
  await expect(estimate(page)).toHaveAttribute("aria-busy", "false");
  await expect(totals(page).locator("[data-slot=skeleton]")).toHaveCount(0);
  await expect(totals(page)).toContainText(/Expected\s*[\d,.]+ h/);
};

const openLastCall = async (scope: Locator) => {
  await scope.getByRole("tab", { name: "Last call" }).click();
  return scope.getByRole("tabpanel", { name: "Last call" });
};

const showDocument = async (page: Page) => {
  const document = page.getByRole("radiogroup", { name: "Result view" }).getByRole("radio", { name: "Document" });
  await document.click();
  await expect(document).toBeChecked();
  await expect(estimatePane(page).getByRole("heading", { level: 2, name: /^Estimation: / })).toBeVisible();
};

// The transcript's marks for the active requirement: in view in the pane, and only that requirement's.
const expectHighlighted = async (page: Page, id: string) => {
  const active = transcriptPane(page).locator("mark[data-active]");
  await expect(active.first()).toBeInViewport();
  const linked = await active.evaluateAll((marks) => marks.map((mark) => (mark as HTMLElement).dataset.req ?? ""));
  expect(linked.every((ids) => ids.split(" ").includes(id)), `highlighted marks (${linked.join(" | ")}) belong to ${id}`).toBe(true);
};

test.describe("estimate", () => {
  test.use({ permissions: ["clipboard-read", "clipboard-write"] });

  test("streams an estimate from the typed form, links requirements to their quotes and copies the phases table", async ({ page }, testInfo) => {
    await page.goto("/");
    await expect(page.getByText("Your estimate appears here")).toBeVisible();
    const inspector = page.getByRole("complementary", { name: "Inspector" });
    await expect(inspector.getByRole("region", { name: "System prompt" })).toContainText("<role>");

    await pickSample(page);
    await choose(page, "Project type", "Web SaaS");
    await choose(page, "Detail level", "Medium");
    await choose(page, "Output format", "Phases table");
    await shot(page, "form");
    const video = testInfo.outputPath("estimate.webm");
    if (MEDIA) await page.screencast.start({ path: video, size: { width: 1280, height: 800 } });

    const response = page.waitForResponse((res) => res.url().endsWith("/api/estimate/stream?prompt_version=v2"));
    await estimateButton(page).click();
    const requestId = (await response).headers()["x-request-id"];
    expect(requestId).toBeTruthy();
    await expect(page.getByText("Web SaaS, medium detail, phases table, prompt v2")).toBeVisible();
    await expect(transcriptPane(page)).toContainText(/physiotherapy/i);

    const progress = page.getByRole("list", { name: "Progress" });
    await expect(progress).toBeVisible();
    await expect(progress.getByRole("listitem")).toHaveText(["Contacting the model", "Drafting the estimate", "Checking the estimate"].map((step) => new RegExp(step)));
    await expect(page.getByRole("button", { name: "Stop", exact: true })).toBeVisible();
    await expectPartial(page);
    await shot(page, "streaming");

    await expectResult(page);
    await expect(projectName(page)).toHaveText(/\S/);
    // Tasks grouped by phase: one row group per phase, each with its tasks.
    const tasks = estimate(page).getByRole("table");
    await expect(tasks.getByRole("columnheader")).toHaveText(["Task", "Range", "Expected"]);
    const phases = await tasks.locator("th[scope=rowgroup]").allTextContents();
    expect(phases.length, "phase groups").toBeGreaterThan(1);
    expect(phases.every((phase) => PHASES.includes(phase)), `phase labels: ${phases.join(", ")}`).toBe(true);
    expect(new Set(phases).size, "each phase is one group").toBe(phases.length);
    for (const group of await tasks.locator("tbody").all()) await expect(group.locator("th[scope=row]").first()).toBeVisible();

    const call = await openLastCall(inspector);
    await expect(valueOf(call, "Provider")).toHaveText("Replay");
    await expect(valueOf(call, "Model")).toHaveText("replay");
    await expect(valueOf(call, "Request ID").locator("code")).toHaveText(requestId);
    await expectOneLine(valueOf(call, "Request ID").locator("code"), "the request ID");

    // Hovering a grounded requirement highlights its quote in the transcript; so does reaching it with Tab.
    const marks = transcriptPane(page).locator("mark[data-req]");
    await expect(marks.first()).toBeVisible();
    const requirement = estimate(page).getByRole("listitem").filter({ has: page.getByRole("button", { name: /^Evidence for / }) }).filter({ hasNotText: "Quote not found in the transcript" }).first();
    const evidenceButton = requirement.getByRole("button", { name: /^Evidence for / });
    const id = (await evidenceButton.getAttribute("aria-label"))?.replace("Evidence for ", "") ?? "";
    expect(id).toMatch(/^R\d+$/);
    await expect(transcriptPane(page).locator("mark[data-active]")).toHaveCount(0);
    await requirement.locator("p").first().hover();
    await expectHighlighted(page, id);
    await shot(page, "result");
    if (MEDIA) await page.waitForTimeout(1500); // the GIF holds on the highlighted quote
    await page.mouse.move(0, 0);
    await expect(transcriptPane(page).locator("mark[data-active]")).toHaveCount(0);
    await evidenceButton.focus();
    await page.keyboard.press("Shift+Tab");
    await expect(evidenceButton).not.toBeFocused();
    await expect(transcriptPane(page).locator("mark[data-active]")).toHaveCount(0);
    await page.keyboard.press("Tab");
    await expect(evidenceButton).toBeFocused();
    await expectHighlighted(page, id);
    await evidenceButton.blur();

    await evidenceButton.hover();
    const evidence = page.locator("[data-slot=hover-card-content]");
    await expect(evidence).toBeVisible();
    await expect(evidence).toContainText("Quote from the transcript");
    await expect(evidence.locator("blockquote")).toHaveText(/“.+”/);
    await page.mouse.move(0, 0);
    await expect(evidence).toBeHidden();

    await page.getByRole("button", { name: "Copy as markdown" }).click();
    await expect(page.getByText("Estimate copied as markdown")).toBeVisible();
    const markdown = await page.evaluate(() => navigator.clipboard.readText());
    expect(markdown.split("\n")[0]).toBe(`## Estimation: ${await projectName(page).textContent()}`);
    expect(markdown).toContain("| Phase | Tasks | Expected h | Range h |");
    // Sonner's own CSS animates toasts for 400 ms in 13 px system-ui; they follow the motion and type tokens instead.
    const toast = await page.locator("[data-sonner-toast]").filter({ hasText: "Estimate copied as markdown" }).evaluate((element) => {
      const style = getComputedStyle(element);
      return { durations: style.transitionDuration.split(",").map(parseFloat), fontSize: style.fontSize, fontFamily: style.fontFamily, body: getComputedStyle(document.body).fontFamily };
    });
    expect(Math.max(...toast.durations), "toast transition duration, in s").toBeLessThanOrEqual(0.15);
    expect(toast.fontSize).toBe("14px");
    expect(toast.fontFamily).toBe(toast.body);
    if (MEDIA) {
      await page.waitForTimeout(1500); // the GIF holds on the toast
      await page.screencast.stop();
      saveGif(video);
    }
  });

  test("the Document view follows the output format: a phases table, then narrative prose", async ({ page }) => {
    await page.goto("/");
    await sendSample(page);
    await expectResult(page);
    await showDocument(page);
    const table = estimatePane(page).getByRole("region", { name: "Table" });
    await expect(table).toHaveCount(1);
    await expect(table.getByRole("columnheader")).toHaveText(["Phase", "Tasks", "Expected h", "Range h"]);
    await expect(table.getByRole("row")).not.toHaveCount(1);

    await choose(page, "Output format", "Narrative");
    await estimateButton(page).click();
    await expect(page.getByText("Web SaaS, medium detail, narrative, prompt v2")).toBeVisible();
    await expectResult(page, { timeout: 45_000 });
    await expect(page.getByRole("radiogroup", { name: "Result view" }).getByRole("radio", { name: "Structured" })).toBeChecked();
    await showDocument(page);
    // One paragraph per phase: "**Backend** — 3 tasks, 40 h expected (30–55 h). T3 …", and no table.
    const paragraphs = estimatePane(page).locator("p").filter({ hasText: /— \d+ tasks?, [\d.,]+ h expected \(/ });
    await expect(paragraphs.first()).toBeVisible();
    for (const phase of await paragraphs.locator("strong").allTextContents()) expect(PHASES).toContain(phase);
    await expect(estimatePane(page).getByRole("region", { name: "Table" })).toHaveCount(0);
    await expect(estimatePane(page).getByRole("table")).toHaveCount(0);
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
    await expect(regenerate).toBeFocused(); // Stop is gone, so focus moves to the estimate's next action

    await regenerate.click();
    await expect(page.getByRole("button", { name: "Stop", exact: true })).toBeVisible();
    await expect(stopped(page)).toHaveCount(0);
    await expectResult(page, { timeout: 45_000 }); // a whole replay (about 13 s), under parallel load
    await expect(page.getByRole("button", { name: "Copy as markdown" })).toBeVisible();
  });

  test("keyboard only: Tab reaches the transcript, the sample menu opens by keyboard, Ctrl/Cmd+Enter estimates and Esc stops", async ({ page }) => {
    await page.goto("/");
    const input = transcript(page);
    await expect(input).toBeVisible();
    const focused = (locator: Locator) => locator.evaluate((element) => element === document.activeElement);
    for (let presses = 0; presses < 20 && !(await focused(input)); presses++) await page.keyboard.press("Tab");
    await expect(input).toBeFocused();

    // The sample menu sits in the transcript's label row, before the textarea: Load sample, Upload .txt, then the text.
    await page.keyboard.press("Shift+Tab");
    await expect(page.getByRole("button", { name: "Upload .txt" })).toBeFocused();
    await page.keyboard.press("Shift+Tab");
    await expect(page.getByRole("button", { name: "Load sample" })).toBeFocused();
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

    test(`no serious or critical axe violations when empty, sample picked, streaming and done (${colorScheme})`, async ({ page }) => {
      await page.goto("/");
      await expect(page.locator("html")).toHaveClass(new RegExp(`\\b${colorScheme}\\b`));
      await expect(transcript(page)).toBeVisible();
      await expectAccessible(page, "empty");

      // The enabled Estimate button fades in from its disabled opacity; axe mid-transition reports a false contrast failure.
      await pickSample(page);
      await settled(page.getByRole("form", { name: "Estimate request" }));
      await expectAccessible(page, "sample picked");
      // axe checks contrast in the state it finds: hovered, the primary button must keep 4.5:1 too
      await estimateButton(page).hover();
      await settled(estimateButton(page));
      await expectAccessible(page, "Estimate hovered");

      await estimateButton(page).click();
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

  test("Transcript | Estimate tabs keep Esc-to-stop and announce the end; the inspector opens as a sheet; nothing scrolls horizontally", async ({ page }) => {
    await page.goto("/");
    await expect(transcript(page)).toBeVisible();
    await expect(page.getByRole("complementary", { name: "Inspector" })).toBeHidden();
    await expectNoHorizontalScroll(page);

    await sendSample(page);
    const tabs = page.getByRole("tablist", { name: "Result" });
    await expect(tabs).toBeVisible();
    await expect(tabs.getByRole("tab", { name: "Estimate" })).toHaveAttribute("aria-selected", "true");
    await expectPartial(page);

    // Behind the Transcript tab the stream still answers Esc, and how it ended is announced.
    await tabs.getByRole("tab", { name: "Transcript" }).click();
    await expect(transcriptPane(page)).toBeVisible();
    await expect(estimate(page)).toBeHidden();
    await page.keyboard.press("Escape");
    await expect(runStatus(page)).toHaveText("Stopped");
    await tabs.getByRole("tab", { name: "Estimate" }).click();
    await expect(stopped(page)).toBeVisible();
    await expect(runStatus(page)).toHaveText("");

    await page.getByRole("button", { name: "Regenerate" }).click();
    await expect(page.getByRole("button", { name: "Stop", exact: true })).toBeVisible();
    await tabs.getByRole("tab", { name: "Transcript" }).click();
    await expect(runStatus(page)).toHaveText("Estimate ready", { timeout: 45_000 });
    await expect(transcriptPane(page).locator("mark[data-req]").first()).toBeVisible();
    await expectNoHorizontalScroll(page);
    await tabs.getByRole("tab", { name: "Estimate" }).click();
    await expectResult(page);
    await expect(runStatus(page)).toHaveText(""); // the estimate's own region speaks now, never both
    await expectNoHorizontalScroll(page);
    await shot(page, "mobile");

    // Evidence pins its requirement and opens the Transcript tab at its quote, which stays highlighted after hover and
    // focus have left the requirement (the last grounded one, so its quote sits low and must be scrolled into view).
    const pinned = estimate(page).getByRole("listitem").filter({ has: page.getByRole("button", { name: /^Evidence for / }) }).filter({ hasNotText: "Quote not found in the transcript" }).last();
    const evidence = pinned.getByRole("button", { name: /^Evidence for / });
    const id = (await evidence.getAttribute("aria-label"))?.replace("Evidence for ", "") ?? "";
    await evidence.click();
    await expect(tabs.getByRole("tab", { name: "Transcript" })).toHaveAttribute("aria-selected", "true");
    await expect(transcriptPane(page)).toBeFocused();
    await expectHighlighted(page, id);
    await expectNoHorizontalScroll(page);

    const trigger = page.getByRole("button", { name: "Inspector" });
    await trigger.click();
    const sheet = page.getByRole("dialog", { name: "Inspector" });
    await expect(sheet).toBeVisible();
    await settled(sheet);
    const call = await openLastCall(sheet);
    await expect(valueOf(call, "Provider")).toHaveText("Replay");
    await expectOneLine(valueOf(call, "Request ID").locator("code"), "the request ID");
    await expectNoHorizontalScroll(page);
    await expectAccessible(page, "inspector sheet");

    await page.keyboard.press("Escape");
    await expect(sheet).toHaveCount(0);
    await expect(trigger).toBeFocused();
  });
});

// The `short` threshold side by side, in px (globals.css, SHORT in split-view.tsx): up to this height the page scrolls
// as a whole; above it the split is fixed below the form.
const SHORT_MAX_HEIGHT = 772;
const pageScroll = (page: Page) => page.evaluate(() => document.documentElement.scrollHeight - window.innerHeight);

// Mid-height laptop windows, up to the threshold: after a run the panes side by side still leave the estimate a usable
// height, as the run left the page (the result is brought into view when the form would crowd it out), the inspector's
// tabs stay in view, and the form stays reachable.
for (const height of [600, SHORT_MAX_HEIGHT]) {
  test.describe(`1280x${height}`, () => {
    test.use({ viewport: { width: 1280, height } });

    test("the page scrolls and the split view keeps a usable estimate area beside the transcript after a run", async ({ page }) => {
      await page.goto("/");
      await sendSample(page);
      await expectResult(page);
      expect(await pageScroll(page), "px the page scrolls").toBeGreaterThan(0);
      await expect(page.getByRole("separator", { name: "Resize the transcript and the estimate" })).toBeVisible();
      expect(await estimate(page).evaluate(visibleHeight), "px of the estimate in view").toBeGreaterThanOrEqual(240);
      expect(await transcriptPane(page).evaluate(visibleHeight), "px of the submitted transcript in view").toBeGreaterThanOrEqual(240);
      await expect(page.getByRole("complementary", { name: "Inspector" }).getByRole("tab", { name: "Last call" })).toBeInViewport({ ratio: 1 });
      await estimateButton(page).scrollIntoViewIfNeeded();
      await expect(estimateButton(page)).toBeInViewport();
      await expectNoHorizontalScroll(page);
    });
  });
}

// Just above the threshold the split is fixed below the form and each pane scrolls on its own, the tightest fit: the
// estimate pane's content (status and actions, then the article) and the transcript keep >= 240 px each.
test.describe(`1280x${SHORT_MAX_HEIGHT + 1}`, () => {
  test.use({ viewport: { width: 1280, height: SHORT_MAX_HEIGHT + 1 } });

  test("just above the short threshold the fixed split keeps a usable estimate area beside the transcript", async ({ page }) => {
    await page.goto("/");
    await sendSample(page);
    await expectResult(page);
    expect(await pageScroll(page), "px the page scrolls").toBe(0);
    expect(await estimate(page).locator("xpath=..").evaluate(visibleHeight), "px of the estimate pane's content in view").toBeGreaterThanOrEqual(240);
    expect(await transcriptPane(page).evaluate(visibleHeight), "px of the submitted transcript in view").toBeGreaterThanOrEqual(240);
    await expect(estimateButton(page)).toBeInViewport();
    await expectNoHorizontalScroll(page);
  });
});

// A landscape phone, and 1280x1024 at 400% zoom (the WCAG 1.4.10 reference): the header and form once took the whole
// height there. Below 480 px tall (772 px side by side) the page scrolls as a whole, so the estimate keeps a usable height.
for (const viewport of [{ width: 640, height: 360 }, { width: 320, height: 256 }]) {
  test.describe(`${viewport.width}x${viewport.height}`, () => {
    test.use({ viewport });

    test("the estimate keeps a usable height and the form stays reachable", async ({ page }) => {
      await page.goto("/");
      await sendSample(page);
      await expectResult(page);
      await estimate(page).evaluate((article) => article.scrollIntoView({ block: "start" }));
      expect(await estimate(page).evaluate(visibleHeight), "px of the estimate in view").toBeGreaterThanOrEqual(120);
      await transcript(page).scrollIntoViewIfNeeded();
      await expect(transcript(page)).toBeInViewport();
      await estimateButton(page).scrollIntoViewIfNeeded();
      await expect(estimateButton(page)).toBeInViewport();
      await expectNoHorizontalScroll(page);
    });
  });
}
