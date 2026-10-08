import { spawnSync } from "node:child_process";
import { copyFileSync, mkdirSync } from "node:fs";
import path from "node:path";
import AxeBuilder from "@axe-core/playwright";
import { type Locator, type Page, expect, test } from "@playwright/test";

// Screenshots and the GIF are written only with MEDIA=1 (`MEDIA=1 make e2e`), so a plain run never dirties tracked files.
const MEDIA = process.env.MEDIA === "1";
const MEDIA_DIR = path.join(__dirname, "..", "..", "docs", "media", "session-05");
if (MEDIA) mkdirSync(MEDIA_DIR, { recursive: true });

const SPEC_PDF = path.join(__dirname, "..", "..", "tests", "fixtures", "attachments", "spec.pdf");

// Session turns render prompt v3 with the project memory, so no recorded cassette matches them: the replay provider
// streams a canned reference estimate (app/context/examples.py) picked by a hash of the prompt (the memory and the
// attachment's text included; their content is never read). Each transcript below was chosen for the reference it picks
// after the turns before it (the AI service turns the CRLF line ends of a multipart field into LF first): when the
// prompt changes, change the text, never the assertions. Freight marketplace streams for about 6 s, Dental clinic
// website for about 3 s.
const FREIGHT_MEETING = [
  "CEO: We want to build a marketplace where shippers post freight loads and carriers bid on them.",
  "CTO: Carriers' drivers need a mobile app, iOS and Android, that shares live GPS location during a delivery.",
  "CEO: Shippers should see the truck on a map and get an ETA.",
  "CFO: Payments go through the platform: the shipper pays upfront, we hold the money and release it to the carrier after proof of delivery.",
  "Ops: Proof of delivery is a photo and a signature captured in the driver app.",
  "CTO: Our two biggest shippers want loads created automatically from their SAP system.",
  "CEO: We also need an admin backoffice to verify carriers' documents and resolve disputes.",
  "CEO: Launch in Spain and Portugal, so Spanish and Portuguese from day one.",
];
// A new session: Freight marketplace, the reference's own meeting, so every quote is marked in the turn's transcript.
const FREIGHT_KICKOFF = [...FREIGHT_MEETING, "Ops: We expect around 800 loads a week at launch."].join("\n");
// After a Freight marketplace turn, with spec.pdf attached: Dental clinic website (technologies: email), whose quotes are
// in no message.
const PAYMENTS_FOLLOW_UP = [
  "CFO: Following up on payments: the attached spec covers checkout, card payments and refunds.",
  "CTO: Settlement runs nightly, and we want refunds of up to 100 euros approved from the backoffice.",
].join("\n");
const SCOPE = "CEO: To close the scope: the marketplace, the driver app and the admin backoffice stay as agreed.";
// After those two turns: Freight marketplace again, whose quotes are now only in the first message.
const SCOPE_CLOSE = [SCOPE, "CTO: The SAP integration covers our two biggest shippers first, about 210 loads a week."].join("\n");
// After one Freight marketplace turn: Freight marketplace again.
const SCOPE_FOLLOW_UP = [SCOPE, "CTO: The SAP integration covers our two biggest shippers first, about 310 loads a week."].join("\n");
// In a new session: Inventario Panaderías, or Freight marketplace with spec.pdf; neither quotes the sample.
const SAMPLE = "Clinic portal";

const FREIGHT = { name: "Freight marketplace", technologies: ["iOS", "Android", "GPS", "SAP"] };
const DENTAL = { name: "Dental clinic website", technologies: ["email"] };
// The longest technology names the AI service keeps (80 characters, app/sessions.py), with spaces and without.
const LONG_TECHNOLOGIES = [
  "Microsoft Dynamics 365 Finance and Operations (on-premises) with Azure Data Lake",
  "SalesforceToSAPS4HANABidirectionalSyncConnectorForEnterpriseResourcePlanning2026",
];

// WCAG 2.2 AA plus axe's best practices; only serious and critical findings fail the run.
const AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"];
const PHASES = ["Discovery", "UX/UI", "Backend", "Frontend", "Integrations", "QA", "DevOps", "Project management"];
const TURN_PATH = /^\/api\/sessions\/[^/]+\/estimate\/stream$/;
const STORAGE_KEY = "estimator.sessionId";

const shot = async (page: Page, name: string) => {
  // "disabled" finishes transitions (a sheet mid-slide) and stops the skeleton pulse
  if (MEDIA) await page.screenshot({ path: path.join(MEDIA_DIR, `${name}.png`), animations: "disabled" });
};

// Playwright video → GIF with ffmpeg; without ffmpeg the .webm itself is kept.
const saveGif = (webm: string) => {
  const ffmpeg = spawnSync("ffmpeg", [
    "-y", "-loglevel", "error", "-i", webm,
    "-vf", "fps=8,scale=800:-1:flags=lanczos,split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=5",
    path.join(MEDIA_DIR, "session.gif"),
  ]);
  if (ffmpeg.error) return copyFileSync(webm, path.join(MEDIA_DIR, "session.webm"));
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
  expect(overflow, "horizontal overflow of the page and the conversation column, in px").toEqual(overflow.map(() => 0));
};

// Waits for open and close animations (the sheet's and the dialog's 150 ms fade and slide) before axe or focus checks.
const settled = (locator: Locator) =>
  locator.evaluate((element) => Promise.all(element.getAnimations({ subtree: true }).map((animation) => animation.finished)));

// The px of an element in view: its box clipped by every scrolling or clipping ancestor, by the viewport, and by the
// sticky header the page scrolls under.
const visibleHeight = (element: Element) => {
  let { top, bottom } = element.getBoundingClientRect();
  for (let parent = element.parentElement; parent; parent = parent.parentElement) {
    if (getComputedStyle(parent).overflowY === "visible") continue;
    const box = parent.getBoundingClientRect();
    [top, bottom] = [Math.max(top, box.top), Math.min(bottom, box.bottom)];
  }
  const header = document.querySelector("header")?.getBoundingClientRect().bottom ?? 0;
  return Math.max(0, Math.min(bottom, window.innerHeight) - Math.max(top, header));
};

const transcript = (page: Page) => page.getByRole("textbox", { name: "Transcript for this turn" });
const estimateButton = (page: Page) => page.getByRole("button", { name: "Estimate", exact: true });
const stopButton = (page: Page) => page.getByRole("button", { name: "Stop", exact: true });
const newConversation = (page: Page) => page.getByRole("button", { name: "New conversation" });
const memory = (page: Page) => page.getByRole("complementary", { name: "Project memory" });
const thread = (page: Page) => page.getByRole("list", { name: "Conversation" });
const turn = (page: Page, n: number) => thread(page).getByRole("listitem", { name: `Turn ${n}`, exact: true });
const estimate = (scope: Locator) => scope.getByRole("article");
// Inside a turn, whose "Turn n" label is the h2, the estimate's title is an h3.
const projectName = (scope: Locator) => estimate(scope).getByRole("heading", { level: 3 });
const totals = (scope: Locator) => estimate(scope).locator("header dl");
const turnTranscript = (page: Page, n: number) => page.getByRole("region", { name: `Transcript of turn ${n}`, exact: true });
const stopped = (page: Page) => page.getByRole("status").filter({ hasText: /^Stopped/ });
const valueOf = (scope: Locator, label: string) => scope.locator(`dt:text-is("${label}") + dd`);
// A memory fact's term holds its label and, when the latest turn changed it, an "Updated" badge.
const factTerm = (page: Page, label: string) => memory(page).locator(`dt:has(> span:text-is("${label}"))`);
const fact = (page: Page, label: string) => memory(page).locator(`dt:has(> span:text-is("${label}")) + dd`);
const requirements = (scope: Locator) => estimate(scope).getByRole("listitem").filter({ has: scope.page().getByRole("button", { name: /^Evidence for / }) });
const flagged = (scope: Locator) => requirements(scope).filter({ hasText: "Quote not found in the transcript" });
const evidenceCard = (page: Page) => page.locator("[data-slot=hover-card-content]");
const idOf = async (evidence: Locator) => (await evidence.getAttribute("aria-label"))?.replace("Evidence for ", "") ?? "";
// A Range over the text has one client rect per line it spans. The element's own rects do not count lines: a flex item
// (the request ID's <code>) is a single box however its text wraps.
const lineCount = (element: Element) => {
  const range = document.createRange();
  range.selectNodeContents(element);
  return range.getClientRects().length;
};
const expectOneLine = async (locator: Locator, what: string) => expect(await locator.evaluate(lineCount), `${what} on one line`).toBe(1);
const storedSession = (page: Page) => page.evaluate((key) => sessionStorage.getItem(key), STORAGE_KEY);

const choose = async (page: Page, group: string, option: string) => {
  const radio = page.getByRole("radiogroup", { name: group }).getByRole("radio", { name: option, exact: true });
  await radio.click();
  await expect(radio).toBeChecked();
};

// Ready once the session is known: the meter shows its history window.
const ready = async (page: Page, turns = 0) => {
  await page.goto("/");
  await expectMeter(page, turns);
};

const expectMeter = async (page: Page, turns: number) => {
  await expect(page.getByText(`History ${turns} / 6 turns`)).toBeVisible();
  await expect(page.getByRole("meter")).toHaveAttribute("aria-valuetext", `${turns} of 6 turns`);
};

const pickSample = async (page: Page) => {
  await page.getByRole("button", { name: "Load sample" }).click();
  await expect(page.getByRole("menuitem")).toHaveCount(3);
  await page.getByRole("menuitem", { name: new RegExp(`^${SAMPLE}`) }).click();
  await expect(transcript(page)).toHaveValue(/physiotherapy/i);
  await expect(page.getByRole("menu")).toHaveCount(0);
};

const clickEstimate = async (page: Page) => {
  await estimateButton(page).click();
  // The pointer leaves the content: a turn scrolling under it would highlight a requirement or open an Evidence card.
  await page.mouse.move(0, 0);
};

// Sends the composer's turn; resolves with the request ID the BFF answered with (the stream's headers arrive first).
const send = async (page: Page, submit = () => clickEstimate(page)) => {
  const response = page.waitForResponse((res) => TURN_PATH.test(new URL(res.url()).pathname) && res.request().method() === "POST");
  await submit();
  const requestId = (await response).headers()["x-request-id"];
  expect(requestId).toBeTruthy();
  return requestId;
};

const sendSample = async (page: Page) => {
  await pickSample(page);
  return send(page);
};

const sendText = async (page: Page, text: string) => {
  await transcript(page).fill(text);
  return send(page);
};

// A partial render: the project name has streamed in while the totals, computed server-side and sent only with the
// result, are still skeletons. Checked in one pass in the page, so both hold at the same moment.
const expectPartial = (page: Page) =>
  expect
    .poll(
      () =>
        page.evaluate(() => {
          const article = document.querySelector("article[aria-busy=true]");
          return Boolean(article?.querySelector("h3:not(.sr-only)")?.textContent && article.querySelector("header dl [data-slot=skeleton]"));
        }),
      { message: "partial render: project name streamed in, totals still skeletons" },
    )
    .toBe(true);

const expectResult = async (scope: Locator, { timeout }: { timeout?: number } = {}) => {
  await expect(estimate(scope).getByRole("status")).toHaveText("Estimate ready", { timeout });
  await expect(estimate(scope)).toHaveAttribute("aria-busy", "false");
  await expect(totals(scope).locator("[data-slot=skeleton]")).toHaveCount(0);
  await expect(totals(scope)).toContainText(/Expected\s*[\d,.]+ h/);
};

const expectTechnologies = (page: Page, names: string[]) => expect(fact(page, "Technologies").getByRole("listitem")).toHaveText(names);

// px from the turn's top to its estimate: the same while it streams and once the result arrives, because the rows above
// it (the result bar, the progress steps, and the actions row with Stop, then the copy actions) keep their size.
const estimateOffset = (scope: Locator) =>
  estimate(scope).evaluate((article) => article.getBoundingClientRect().top - (article.closest("li")?.getBoundingClientRect().top ?? 0));

const openInspector = async (page: Page, tab: "Context" | "Last call") => {
  await page.getByRole("button", { name: "Inspector" }).click();
  const sheet = page.getByRole("dialog", { name: "Inspector" });
  await expect(sheet).toBeVisible();
  await settled(sheet);
  await sheet.getByRole("tab", { name: tab }).click();
  return { sheet, panel: sheet.getByRole("tabpanel", { name: tab }) };
};

// Esc closes the sheet; focus returns to its trigger once the exit animation has unmounted it.
const closeInspector = async (page: Page) => {
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog", { name: "Inspector" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Inspector" })).toBeFocused();
};

// The turn's transcript, behind its disclosure; open, it marks every grounded quote of this turn's text.
const openTranscript = async (page: Page, n: number) => {
  const toggle = turn(page, n).getByRole("button", { name: /^Transcript/ });
  if ((await toggle.getAttribute("aria-expanded")) !== "true") await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  return turnTranscript(page, n);
};

// The transcript's marks for the active requirement: only that requirement's, and the first in view in its region (the
// region scrolls on its own, so the page and the estimate never move).
const expectHighlighted = async (region: Locator, id: string) => {
  const active = region.locator("mark[data-active]");
  await expect(active.first()).toBeVisible();
  const linked = await active.evaluateAll((marks) => marks.map((mark) => (mark as HTMLElement).dataset.req ?? ""));
  expect(linked.every((ids) => ids.split(" ").includes(id)), `highlighted marks (${linked.join(" | ")}) belong to ${id}`).toBe(true);
  const inRegion = () =>
    active.first().evaluate((mark) => {
      const pane = mark.closest("[role=region]");
      if (!pane) return false;
      const [box, view] = [mark.getBoundingClientRect(), pane.getBoundingClientRect()];
      return box.top >= view.top && box.bottom <= view.bottom;
    });
  // The region glides to the quote (smooth scrolling).
  await expect.poll(inRegion, { message: "the highlighted quote is in view in its transcript region" }).toBe(true);
};

test.describe("session", () => {
  test.use({ permissions: ["clipboard-read", "clipboard-write"] });

  test("three turns in one session: a typed turn streams, the second attaches a PDF, and the memory and the history meter follow", async ({ page }, testInfo) => {
    await ready(page);
    await expect(page.getByText("Start the conversation")).toBeVisible();
    await expect(fact(page, "Project name")).toHaveText("Not mentioned yet");
    await expect(memory(page).getByText("Not mentioned yet")).toHaveCount(4);
    const { panel: context } = await openInspector(page, "Context");
    await expect(context.getByRole("region", { name: "System prompt" })).toContainText("<role>");
    await closeInspector(page);
    await shot(page, "empty");
    const video = testInfo.outputPath("session.webm");
    if (MEDIA) await page.screencast.start({ path: video, size: { width: 1280, height: 800 } });

    // Turn 1, typed: progress, then a partial estimate, then the result.
    const one = turn(page, 1);
    await sendText(page, FREIGHT_KICKOFF);
    await expect(one).toContainText("Web SaaS, medium detail, phases table");
    await expect(transcript(page)).toHaveValue(""); // the composer empties for the next turn
    const progress = one.getByRole("list", { name: "Progress" });
    await expect(progress.getByRole("listitem")).toHaveText(["Contacting the model", "Drafting the estimate", "Checking the estimate"].map((step) => new RegExp(step)));
    await expect(stopButton(page)).toBeVisible();
    await expect(one.getByRole("heading", { level: 2 })).toHaveText("Turn 1");
    await expectPartial(page);
    // The view toggle and the copy actions arrive with the result in rows held at their size while the turn streams.
    const streamingOffset = await estimateOffset(one);
    await expectResult(one);
    await expect(one.getByRole("radiogroup", { name: "Result view" })).toBeVisible();
    await expect(one.getByRole("button", { name: "Copy as markdown" })).toBeVisible();
    expect(await estimateOffset(one), "px from the turn's top to its estimate, once the result arrived").toBe(streamingOffset);
    await expect(projectName(one)).toHaveText(FREIGHT.name);
    // Tasks grouped by phase: one row group per phase, each with its tasks.
    const tasks = estimate(one).getByRole("table");
    await expect(tasks.getByRole("columnheader")).toHaveText(["Task", "Range", "Expected"]);
    const phases = await tasks.locator("th[scope=rowgroup]").allTextContents();
    expect(phases.length, "phase groups").toBeGreaterThan(1);
    expect(phases.every((phase) => PHASES.includes(phase)), `phase labels: ${phases.join(", ")}`).toBe(true);
    expect(new Set(phases).size, "each phase is one group").toBe(phases.length);
    for (const group of await tasks.locator("tbody").all()) await expect(group.locator("th[scope=row]").first()).toBeVisible();

    // The memory holds the first answer's facts, each marked as updated; the meter counts one turn.
    await expect(fact(page, "Project name")).toHaveText(FREIGHT.name);
    await expectTechnologies(page, FREIGHT.technologies);
    for (const label of ["Project name", "Team size", "Technologies", "Agreed scope"]) await expect(factTerm(page, label)).toContainText("Updated in turn 1");
    await expectMeter(page, 1);

    // Hovering a grounded requirement highlights its quote in the turn's transcript; so does reaching it with Tab.
    const pane = await openTranscript(page, 1);
    await expect(pane).toContainText("freight loads");
    await expect(pane.locator("mark[data-req]").first()).toBeVisible();
    await expect(flagged(one)).toHaveCount(0); // every quote is the meeting's own
    const requirement = requirements(one).first();
    const evidenceButton = requirement.getByRole("button", { name: /^Evidence for / });
    const id = await idOf(evidenceButton);
    expect(id).toMatch(/^R\d+$/);
    await expect(pane.locator("mark[data-active]")).toHaveCount(0);
    await requirement.locator("p").first().hover();
    await expectHighlighted(pane, id);
    if (MEDIA) await page.waitForTimeout(1500); // the GIF holds on the highlighted quote
    await page.mouse.move(0, 0);
    await expect(pane.locator("mark[data-active]")).toHaveCount(0);
    await evidenceButton.focus();
    await page.keyboard.press("Shift+Tab");
    await expect(evidenceButton).not.toBeFocused();
    await expect(pane.locator("mark[data-active]")).toHaveCount(0);
    await page.keyboard.press("Tab");
    await expect(evidenceButton).toBeFocused();
    await expectHighlighted(pane, id);
    await evidenceButton.blur();

    await evidenceButton.hover();
    await expect(evidenceCard(page)).toBeVisible();
    await expect(evidenceCard(page)).toContainText("Quote from the transcript");
    await expect(evidenceCard(page).locator("blockquote")).toHaveText(/“.+”/);
    await page.mouse.move(0, 0);
    await expect(evidenceCard(page)).toBeHidden();

    await one.getByRole("button", { name: "Copy as markdown" }).click();
    await expect(page.getByText("Estimate copied as markdown")).toBeVisible();
    const markdown = await page.evaluate(() => navigator.clipboard.readText());
    expect(markdown.split("\n")[0]).toBe(`## Estimation: ${FREIGHT.name}`);
    expect(markdown).toContain("| Phase | Tasks | Expected h | Range h |");
    // Sonner's own CSS animates toasts for 400 ms in 13 px system-ui; they follow the motion and type tokens instead.
    const toast = await page.locator("[data-sonner-toast]").filter({ hasText: "Estimate copied as markdown" }).evaluate((element) => {
      const style = getComputedStyle(element);
      return { durations: style.transitionDuration.split(",").map(parseFloat), fontSize: style.fontSize, fontFamily: style.fontFamily, body: getComputedStyle(document.body).fontFamily };
    });
    expect(Math.max(...toast.durations), "toast transition duration, in s").toBeLessThanOrEqual(0.15);
    expect(toast.fontSize).toBe("14px");
    expect(toast.fontFamily).toBe(toast.body);

    // Turn 2 attaches the PDF: a chip in the composer, then on the turn that sent it.
    await page.getByLabel("Attach documents").setInputFiles(SPEC_PDF);
    const attached = page.getByRole("list", { name: "Attached documents" });
    await expect(attached.getByRole("listitem")).toHaveCount(1);
    await expect(attached).toContainText("spec.pdf");
    const two = turn(page, 2);
    await sendText(page, PAYMENTS_FOLLOW_UP);
    await expect(attached).toHaveCount(0); // the composer starts the next turn without files
    await expect(two.getByRole("list", { name: "Attachments" }).getByRole("listitem")).toContainText("spec.pdf");
    await expectResult(two);
    await expect(projectName(two)).toHaveText(DENTAL.name);
    await expect(two.getByText(/ vs previous turn$/)).toBeVisible();
    // Technologies merge: the new answer's are added to the known ones, and the fact is marked as updated.
    await expectTechnologies(page, [...FREIGHT.technologies, ...DENTAL.technologies]);
    await expect(factTerm(page, "Technologies")).toContainText("Updated in turn 2");
    await expectMeter(page, 2);
    await two.scrollIntoViewIfNeeded();
    await shot(page, "turn-with-attachment");
    if (MEDIA) await page.waitForTimeout(1500);

    // Turn 3: the answer's quotes are grounded in the first message, not in this turn's text, and say so.
    const three = turn(page, 3);
    const lastRequestId = await sendText(page, SCOPE_CLOSE);
    await expectResult(three);
    await expect(projectName(three)).toHaveText(FREIGHT.name);
    await expectMeter(page, 3);
    await expect(fact(page, "Project name")).toHaveText(FREIGHT.name);
    await expect(factTerm(page, "Project name")).toContainText("Updated in turn 3");
    await expectTechnologies(page, [...FREIGHT.technologies, ...DENTAL.technologies]);
    await expect(factTerm(page, "Technologies")).not.toContainText("Updated"); // nothing new to add
    await expect(flagged(three)).toHaveCount(0);
    await requirements(three).first().getByRole("button", { name: /^Evidence for / }).hover();
    await expect(evidenceCard(page)).toContainText("Quote from an earlier message");
    await page.mouse.move(0, 0);
    await expect(evidenceCard(page)).toBeHidden();
    await shot(page, "memory-after-turn-3");
    if (MEDIA) {
      await page.waitForTimeout(2000); // the GIF holds on the memory after the third turn
      await page.screencast.stop();
      saveGif(video);
    }

    // The inspector's Last call is the latest completed turn's, with the request ID the BFF answered with.
    const { panel: call } = await openInspector(page, "Last call");
    await expect(valueOf(call, "Provider")).toHaveText("Replay");
    await expect(valueOf(call, "Model")).toHaveText("replay");
    await expect(valueOf(call, "Prompt version")).toHaveText("v3");
    await expect(valueOf(call, "Request ID").locator("code")).toHaveText(lastRequestId);
    await expectOneLine(valueOf(call, "Request ID").locator("code"), "the request ID");
    await closeInspector(page);
  });

  test("a reload keeps the session; New conversation asks first while a turn streams, then resets the memory and the thread", async ({ page }) => {
    await ready(page);
    await sendText(page, FREIGHT_KICKOFF);
    await expectResult(turn(page, 1));
    await expect(fact(page, "Project name")).toHaveText(FREIGHT.name);
    await expectMeter(page, 1);
    const session = await storedSession(page);
    expect(session).toMatch(/^[0-9a-f-]{36}$/);

    // A reload keeps the conversation (its history and memory), not the answers this page showed.
    await page.reload();
    await expectMeter(page, 1);
    await expect(page.getByText("This conversation continues")).toBeVisible();
    await expect(page.getByText(/^1 earlier turn is kept in its history, with the project memory/)).toBeVisible();
    await expect(thread(page)).toHaveCount(0);
    await expect(fact(page, "Project name")).toHaveText(FREIGHT.name);
    await expectTechnologies(page, FREIGHT.technologies);
    expect(await storedSession(page)).toBe(session);

    // The next turn continues the session's numbering. Mid-answer, New conversation asks first.
    await sendText(page, SCOPE_FOLLOW_UP);
    await expect(turn(page, 2)).toBeVisible();
    await expect(stopButton(page)).toBeVisible();
    await newConversation(page).click();
    const dialog = page.getByRole("alertdialog", { name: "Start a new conversation?" });
    await expect(dialog).toBeVisible();
    await settled(dialog);
    await expectAccessible(page, "new conversation dialog");
    await dialog.getByRole("button", { name: "Cancel" }).click();
    await expect(dialog).toHaveCount(0);
    await expect(newConversation(page)).toBeFocused(); // back where it was opened from
    await expect(stopButton(page)).toBeVisible(); // the answer goes on

    await newConversation(page).click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Start new" }).click();
    await expect(page.getByRole("alertdialog")).toHaveCount(0);
    await expect(page.getByText("Started a new conversation.")).toBeVisible();
    await expect(page.getByText("Start the conversation")).toBeVisible();
    await expect(thread(page)).toHaveCount(0);
    await expectMeter(page, 0);
    await expect(memory(page).getByText("Not mentioned yet")).toHaveCount(4);
    await expect(transcript(page)).toBeFocused(); // with a mouse, ready for the new conversation's first turn
    const fresh = await storedSession(page);
    expect(fresh).toMatch(/^[0-9a-f-]{36}$/);
    expect(fresh).not.toBe(session);
  });

  test("a stored session the AI service does not know (expired or evicted) is replaced by a new one", async ({ page }) => {
    const unknown = "00000000-0000-4000-8000-000000000000";
    await page.addInitScript(([key, id]) => sessionStorage.setItem(key, id), [STORAGE_KEY, unknown]);
    const checked = page.waitForResponse((res) => new URL(res.url()).pathname === `/api/sessions/${unknown}`);
    await ready(page);
    expect((await checked).status()).toBe(404);
    await expect(page.getByText("Start the conversation")).toBeVisible();
    await expect(memory(page).getByText("Not mentioned yet")).toHaveCount(4);
    const created = await storedSession(page);
    expect(created).toMatch(/^[0-9a-f-]{36}$/);
    expect(created).not.toBe(unknown);

    const response = page.waitForResponse((res) => TURN_PATH.test(new URL(res.url()).pathname));
    await sendSample(page);
    expect(new URL((await response).url()).pathname).toBe(`/api/sessions/${created}/estimate/stream`);
    await expectResult(turn(page, 1));
    await expectMeter(page, 1);
  });

  test("the Document view follows each turn's output format: a phases table, then narrative prose", async ({ page }) => {
    await ready(page);
    await sendSample(page);
    const one = turn(page, 1);
    await expectResult(one);
    const showDocument = async (scope: Locator) => {
      const document = scope.getByRole("radiogroup", { name: "Result view" }).getByRole("radio", { name: "Document" });
      await document.click();
      await expect(document).toBeChecked();
      await expect(scope.getByRole("heading", { level: 3, name: /^Estimation: / })).toBeVisible(); // one level below "Turn n"
    };
    await showDocument(one);
    // The table's region is named by the server's heading above it.
    const table = one.getByRole("region").filter({ has: page.getByRole("table") });
    await expect(table).toHaveCount(1);
    const [tag, heading, labelledByIt] = await table.evaluate((region) => {
      const above = region.previousElementSibling;
      return [above?.tagName, above?.textContent?.trim(), Boolean(above?.id) && region.getAttribute("aria-labelledby") === above?.id];
    });
    expect(tag, "the element above the table").toMatch(/^H[1-6]$/);
    expect(labelledByIt, "the region is aria-labelledby the heading above it").toBe(true);
    await expect(table).toHaveAccessibleName(String(heading));
    await expect(table.getByRole("columnheader")).toHaveText(["Phase", "Tasks", "Expected h", "Range h"]);
    await expect(table.getByRole("row")).not.toHaveCount(1);
    // A tab stop only while it scrolls sideways: the table fits the turn at 1280 px, not in a 320 px window.
    const scrolls = (region: Element) => region.scrollWidth > region.clientWidth;
    expect(await table.evaluate(scrolls)).toBe(false);
    await expect(table).not.toHaveAttribute("tabindex");
    await page.setViewportSize({ width: 320, height: 800 });
    const narrow = one.getByRole("region", { name: heading, exact: true });
    await expect(narrow).toHaveAttribute("tabindex", "0");
    expect(await narrow.evaluate(scrolls)).toBe(true);
    await page.setViewportSize({ width: 1280, height: 800 });
    await expect(table).not.toHaveAttribute("tabindex");

    await choose(page, "Output format", "Narrative");
    await sendSample(page);
    const two = turn(page, 2);
    await expect(two).toContainText("Web SaaS, medium detail, narrative");
    await expectResult(two, { timeout: 45_000 });
    await expect(two.getByRole("radiogroup", { name: "Result view" }).getByRole("radio", { name: "Structured" })).toBeChecked(); // each turn starts structured
    await expect(one.getByRole("radiogroup", { name: "Result view" }).getByRole("radio", { name: "Document" })).toBeChecked(); // and keeps its own view
    await showDocument(two);
    // One paragraph per phase: "**Backend** — 3 tasks, 40 h expected (30–55 h). T3 …", and no table.
    const paragraphs = two.locator("p").filter({ hasText: /— \d+ tasks?, [\d.,]+ h expected \(/ });
    await expect(paragraphs.first()).toBeVisible();
    for (const phase of await paragraphs.locator("strong").allTextContents()) expect(PHASES).toContain(phase);
    await expect(two.getByRole("region").filter({ has: page.getByRole("table") })).toHaveCount(0);
    await expect(two.getByRole("table")).toHaveCount(0);
  });

  test("Stop keeps the partial estimate and the stopped turn offers Retry; a completed turn offers no way to run it again", async ({ page }) => {
    await ready(page);
    await sendSample(page);
    const one = turn(page, 1);
    await expectPartial(page);
    await stopButton(page).click();

    await expect(stopped(page)).toBeVisible();
    await expect(estimate(one)).toHaveAttribute("aria-busy", "false");
    await expect(projectName(one)).toHaveText(/\S/);
    await expect(totals(one).locator("[data-slot=skeleton]").first()).toBeVisible();
    const retry = one.getByRole("button", { name: "Retry" });
    await expect(retry).toBeFocused(); // Stop is gone, so focus moves to the turn's next action
    await expectMeter(page, 0); // a stopped turn never reaches the history

    await retry.click();
    await expect(stopButton(page)).toBeVisible();
    await expect(stopped(page)).toHaveCount(0);
    await expectResult(one, { timeout: 45_000 });
    await expect(one.getByRole("button", { name: "Copy as markdown" })).toBeVisible();
    await expect(one.getByRole("button", { name: /^(Retry|Regenerate|Try again)$/ })).toHaveCount(0); // S5-R3
    await expectMeter(page, 1);

    // The sample's answer quotes another meeting: each quote is flagged, and its Evidence shows the model's quote.
    await expect(flagged(one).first()).toBeVisible();
    await flagged(one).first().getByRole("button", { name: /^Evidence for / }).hover();
    await expect(evidenceCard(page)).toContainText("Quote given by the model, not found in the transcript");
  });

  test("keyboard only: Tab reaches the transcript, the sample menu opens by keyboard, Ctrl/Cmd+Enter sends and Esc stops", async ({ page }) => {
    await ready(page);
    const input = transcript(page);
    const focused = (locator: Locator) => locator.evaluate((element) => element === document.activeElement);
    for (let presses = 0; presses < 20 && !(await focused(input)); presses++) await page.keyboard.press("Tab");
    await expect(input).toBeFocused();

    // The sample menu sits in the transcript's label row, before the textarea: Load sample, Upload .txt, then the text.
    await page.keyboard.press("Shift+Tab");
    await expect(page.getByRole("button", { name: "Upload .txt" })).toBeFocused();
    await page.keyboard.press("Shift+Tab");
    await expect(page.getByRole("button", { name: "Load sample" })).toBeFocused();
    await page.keyboard.press("Enter");
    const items = page.getByRole("menuitem");
    await expect(items.first()).toBeFocused();
    // One press per item, each waited for: the menu moves focus after the key, so a check right after it can lag.
    const index = (await items.allTextContents()).findIndex((text) => text.startsWith(SAMPLE));
    for (let i = 1; i <= index; i++) {
      await page.keyboard.press("ArrowDown");
      await expect(items.nth(i)).toBeFocused();
    }
    await page.keyboard.press("Enter");
    await expect(input).toBeFocused();
    await expect(input).toHaveValue(/physiotherapy/i);

    await send(page, () => page.keyboard.press("ControlOrMeta+Enter"));
    await expect(stopButton(page)).toBeVisible();
    await expect(input).toBeFocused(); // with a mouse or keyboard, focus stays in the composer
    await expectPartial(page);
    await page.keyboard.press("Escape");
    await expect(stopped(page)).toBeVisible();
    await expect(stopButton(page)).toHaveCount(0);
  });

  // The transcript sits in the turn's header, far above most requirements: Evidence brings the quote to the reader.
  test("Evidence (a click, or Enter) opens the turn's transcript at its quote; hovering a requirement never scrolls the page", async ({ page }) => {
    await ready(page);
    const one = turn(page, 1);
    await sendText(page, FREIGHT_KICKOFF);
    await expectResult(one);
    const toggle = one.getByRole("button", { name: /^Transcript/ });
    await expect(toggle).toHaveAttribute("aria-expanded", "false");

    const last = requirements(one).last();
    const evidence = last.getByRole("button", { name: /^Evidence for / });
    const id = await idOf(evidence);
    await evidence.click();
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    const pane = turnTranscript(page, 1);
    await expect(pane).toBeFocused();
    await expectHighlighted(pane, id);
    await expect(pane.locator("mark[data-active]").first()).toBeInViewport();
    await expect(evidenceCard(page)).toHaveCount(0);

    // Hovering a requirement highlights its quote inside the transcript region only: the page stays where it is.
    const first = requirements(one).first();
    await first.scrollIntoViewIfNeeded();
    const scrollTop = await page.evaluate(() => document.scrollingElement?.scrollTop);
    await first.locator("p").first().hover();
    await expectHighlighted(pane, await idOf(first.getByRole("button", { name: /^Evidence for / })));
    expect(await page.evaluate(() => document.scrollingElement?.scrollTop), "the page's scroll after hovering a requirement").toBe(scrollTop);
    await page.mouse.move(0, 0);

    const second = requirements(one).nth(1).getByRole("button", { name: /^Evidence for / });
    await second.focus();
    await page.keyboard.press("Enter");
    await expect(pane).toBeFocused();
    await expectHighlighted(pane, await idOf(second));
    await expect(pane.locator("mark[data-active]").first()).toBeInViewport();
  });
});

for (const colorScheme of ["light", "dark"] as const) {
  test.describe(`${colorScheme} theme`, () => {
    test.use({ colorScheme });

    test(`no serious or critical axe violations: empty, transcript entered, attachment added, streaming, result, memory, Last call (${colorScheme})`, async ({ page }) => {
      await ready(page);
      await expect(page.locator("html")).toHaveClass(new RegExp(`\\b${colorScheme}\\b`));
      await expectAccessible(page, "empty");

      // The enabled Estimate button fades in from its disabled opacity; axe mid-transition reports a false contrast failure.
      await pickSample(page);
      await settled(page.getByRole("form", { name: "Estimate request" }));
      await expectAccessible(page, "transcript entered");
      // axe checks contrast in the state it finds: hovered, the primary button must keep 4.5:1 too
      await estimateButton(page).hover();
      await settled(estimateButton(page));
      await expectAccessible(page, "Estimate hovered");
      await page.getByLabel("Attach documents").setInputFiles(SPEC_PDF);
      await expect(page.getByRole("list", { name: "Attached documents" })).toContainText("spec.pdf");
      await expectAccessible(page, "attachment added");

      await send(page);
      await expectPartial(page);
      await expectAccessible(page, "streaming");

      await expectResult(turn(page, 1));
      await expect(factTerm(page, "Technologies")).toContainText("Updated");
      await expectAccessible(page, "result, memory updated");
      // The history meter's explanation opens on focus.
      await page.getByRole("button", { name: "About the history window" }).focus();
      await expect(page.getByRole("tooltip")).toContainText("Older turns are dropped first");
      await expectAccessible(page, "memory, history tooltip open");
      await page.keyboard.press("Escape");

      await openInspector(page, "Last call");
      await expectAccessible(page, "Last call tab");
      await closeInspector(page);
      if (colorScheme === "dark") await shot(page, "dark-theme");
    });
  });
}

test.describe("375 px wide", () => {
  test.use({ viewport: { width: 375, height: 812 } });

  test("the memory sits above the conversation, Evidence pins only a quote marked in its turn, the inspector is a sheet, and nothing scrolls horizontally", async ({ page }) => {
    await ready(page);
    await expect(memory(page)).toBeVisible();
    await expect(page.getByRole("complementary", { name: "Inspector" })).toHaveCount(0); // a sheet at every width
    expect(
      await memory(page).evaluate((aside) => {
        const main = document.querySelector("main");
        return Boolean(main && aside.compareDocumentPosition(main) & Node.DOCUMENT_POSITION_FOLLOWING);
      }),
      "the memory comes before the conversation",
    ).toBe(true);
    await expectNoHorizontalScroll(page);

    const one = turn(page, 1);
    await sendText(page, FREIGHT_KICKOFF);
    await expectPartial(page);
    await expectNoHorizontalScroll(page);
    const streamingOffset = await estimateOffset(one);
    await expectResult(one);
    await expect(one.getByRole("button", { name: "Copy as markdown" })).toBeVisible();
    expect(await estimateOffset(one), "px from the turn's top to its estimate, once the result arrived").toBe(streamingOffset);
    await expectNoHorizontalScroll(page);
    await shot(page, "mobile");

    // Evidence on a quote marked in this turn's transcript pins its requirement: the disclosure opens at the quote, which
    // stays highlighted after hover and focus have left (the last one, so its quote sits low and must be brought into view).
    const evidence = requirements(one).last().getByRole("button", { name: /^Evidence for / });
    const id = await idOf(evidence);
    await evidence.click();
    const pane = turnTranscript(page, 1);
    await expect(one.getByRole("button", { name: /^Transcript/ })).toHaveAttribute("aria-expanded", "true");
    await expect(pane).toBeFocused();
    await expectHighlighted(pane, id);
    await expect(pane.locator("mark[data-active]").first()).toBeInViewport();
    await expect(evidenceCard(page)).toHaveCount(0);
    await expectNoHorizontalScroll(page);

    const two = turn(page, 2);
    await sendText(page, SCOPE_FOLLOW_UP);
    await expectResult(two);
    await expectNoHorizontalScroll(page);

    const { sheet, panel: call } = await openInspector(page, "Last call");
    await expect(sheet.getByRole("tablist")).toBeInViewport({ ratio: 1 });
    await expect(valueOf(call, "Provider")).toHaveText("Replay");
    await expectOneLine(valueOf(call, "Request ID").locator("code"), "the request ID");
    await expectNoHorizontalScroll(page);
    await expectAccessible(page, "inspector sheet");
    await closeInspector(page);

    // A quote with no mark in its turn (here grounded in the first message) cannot be pinned: Evidence shows its card,
    // and the turn's transcript stays closed. Last: a clicked card can reopen from Radix's leaked open timer (stack.md).
    await expect(flagged(two)).toHaveCount(0);
    await requirements(two).first().getByRole("button", { name: /^Evidence for / }).click();
    await expect(evidenceCard(page)).toContainText("Quote from an earlier message");
    await expect(two.getByRole("button", { name: /^Transcript/ })).toHaveAttribute("aria-expanded", "false");
  });
});

test.describe("360 px wide", () => {
  test.use({ viewport: { width: 360, height: 780 } });

  test("an 80-character technology wraps in the memory: nothing scrolls sideways, nor does the memory column from 1024 px", async ({ page }) => {
    for (const name of LONG_TECHNOLOGIES) expect(name).toHaveLength(80);
    // The session's view as if earlier turns had named them: the memory shows it before any turn.
    await page.route("**/api/sessions/*", async (route) => {
      if (route.request().method() !== "GET") return route.continue();
      const response = await route.fetch();
      const view = await response.json();
      await route.fulfill({ response, json: { ...view, project_metadata: { ...view.project_metadata, mentioned_technologies: ["SAP", ...LONG_TECHNOLOGIES] } } });
    });
    await ready(page);
    await expectTechnologies(page, ["SAP", ...LONG_TECHNOLOGIES]);
    await expectNoHorizontalScroll(page);
    // From 1024 px the memory is a sticky column that scrolls on its own.
    await page.setViewportSize({ width: 1024, height: 768 });
    await expect(memory(page)).toHaveCSS("position", "sticky");
    expect(await memory(page).evaluate((aside) => aside.scrollWidth - aside.clientWidth), "horizontal overflow of the memory column, in px").toBe(0);
    await expectNoHorizontalScroll(page);
  });
});

// Mid widths, where the header shows both models of the chain and every action's label: a long chain truncates in its
// chip (the whole chain stays in its title), so the actions keep their width and the page never scrolls sideways.
test.describe("700 px wide", () => {
  test.use({ viewport: { width: 700, height: 900 } });

  test("a long model chain truncates in the header: the actions stay in the window and nothing scrolls sideways", async ({ page }) => {
    await page.route(/\/api\/context(\?|$)/, async (route) => {
      const response = await route.fetch();
      await route.fulfill({ response, json: { ...(await response.json()), chain: ["openai:gpt-4o-mini", "anthropic:claude-haiku-4-5"] } });
    });
    await ready(page);
    const chain = page.getByText("Model:").locator("..");
    await expect(chain).toHaveAttribute("title", "OpenAI gpt-4o-mini → Anthropic claude-haiku-4-5");
    for (const width of [700, 640, 768]) {
      await page.setViewportSize({ width, height: 900 });
      await expect(page.getByRole("button", { name: "Theme" }), `the theme menu at ${width} px`).toBeInViewport({ ratio: 1 });
      await expectNoHorizontalScroll(page);
    }
  });
});

// A large window: the conversation and the memory take its width and the page scrolls as a whole. A text that fits the
// window is never boxed in a pane that scrolls on its own (the composer's transcript was capped at 384 px, a turn's at
// 320 px, whatever the window's height).
test.describe("1920x1080", () => {
  test.use({ viewport: { width: 1920, height: 1080 } });

  const scrollsInside = (element: Element) => element.scrollHeight > element.clientHeight;
  const innerScrollers = () =>
    [...document.querySelectorAll("body *")]
      .filter((element) => /auto|scroll/.test(getComputedStyle(element).overflowY) && element.scrollHeight - element.clientHeight > 1)
      .map((element) => element.getAttribute("aria-label") ?? element.tagName.toLowerCase());

  test("the workspace fills the window, the page is what scrolls, and a transcript that fits the window shows in full", async ({ page }) => {
    await ready(page);
    const widths = await page.evaluate(() => ["main", "aside"].map((tag) => document.querySelector(tag)?.getBoundingClientRect().width ?? 0));
    expect(widths[0] + widths[1], "px wide the conversation and the memory take together").toBeGreaterThanOrEqual(1920 * 0.95);

    // 24 short lines: about 500 px of text, more than the old caps and less than this window.
    const meeting = Array.from({ length: 24 }, (_, i) => `${["CEO", "CTO", "Ops"][i % 3]}: point ${i + 1} of the freight marketplace meeting.`).join("\n");
    await transcript(page).fill(meeting);
    expect(await transcript(page).evaluate(scrollsInside), "the composer's transcript scrolls inside its box").toBe(false);

    const one = turn(page, 1);
    await send(page);
    await expectResult(one);
    expect(await page.locator("html").evaluate(scrollsInside), "the page scrolls").toBe(true);
    expect(await page.evaluate(innerScrollers), "elements that scroll on their own").toEqual([]);
    await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
    await expect(memory(page).getByRole("heading", { name: "Project memory" })).toBeInViewport(); // sticky beside the turns

    const pane = await openTranscript(page, 1);
    await expect(pane).toBeVisible();
    expect(await pane.evaluate(scrollsInside), "the turn's transcript scrolls inside its box").toBe(false);
    await expectNoHorizontalScroll(page);
  });
});

// Short windows (the session layout has no height breakpoint): the page scrolls as a whole under a 48 px sticky header,
// and the memory column is sticky beside the conversation from 1024 px. A mid-height laptop window, a landscape phone,
// and 1280x1024 at 400% zoom (the WCAG 1.4.10 reference): a sent turn is brought into view below the header, its
// estimate keeps a usable height, and the memory, the inspector's tabs and the composer stay reachable.
for (const { width, height, bar } of [
  { width: 1280, height: 600, bar: 240 },
  { width: 640, height: 360, bar: 120 },
  { width: 320, height: 256, bar: 120 },
]) {
  test.describe(`${width}x${height}`, () => {
    test.use({ viewport: { width, height } });

    test("a sent turn comes into view below the header, its estimate keeps a usable height, and the memory and the composer stay reachable", async ({ page }) => {
      await ready(page);
      await sendSample(page);
      const one = turn(page, 1);
      // The app header is the page's first <header> (each estimate has its own).
      const header = await page.locator("header").first().evaluate((element) => element.getBoundingClientRect().bottom);
      expect(header, "px the sticky header takes").toBeLessThanOrEqual(48);
      // The turn glides into view (smooth scrolling) and stops below the header.
      await expect
        .poll(() => one.evaluate((card) => card.getBoundingClientRect().top), { message: "the turn's top, below the header and in the window" })
        .toBeGreaterThanOrEqual(header);
      expect(await one.evaluate((card) => card.getBoundingClientRect().top), "the turn's top, in the window").toBeLessThan(height);
      await expectResult(one);
      await estimate(one).evaluate((article) => article.scrollIntoView({ block: "start" }));
      expect(await estimate(one).evaluate(visibleHeight), "px of the estimate in view below the header").toBeGreaterThanOrEqual(bar);
      if (width >= 1024) await expect(memory(page).getByRole("heading", { name: "Project memory" })).toBeInViewport(); // sticky beside the turn
      await memory(page).getByRole("heading", { name: "Project memory" }).scrollIntoViewIfNeeded();
      await expect(memory(page).getByRole("heading", { name: "Project memory" })).toBeInViewport();
      const { sheet } = await openInspector(page, "Last call");
      await expect(sheet.getByRole("tab", { name: "Last call" })).toBeInViewport({ ratio: 1 });
      await closeInspector(page);
      await transcript(page).scrollIntoViewIfNeeded();
      await expect(transcript(page)).toBeInViewport();
      await estimateButton(page).scrollIntoViewIfNeeded();
      await expect(estimateButton(page)).toBeInViewport();
      await expectNoHorizontalScroll(page);
    });
  });
}
