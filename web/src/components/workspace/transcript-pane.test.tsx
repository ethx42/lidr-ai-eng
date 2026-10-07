import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TranscriptPane } from "./transcript-pane";

const TRANSCRIPT = "Sofía: Patients log in and book sessions.\nTomás: Invoices?\nSofía: Download invoices as PDF.";
const QUOTES = [
  { id: "R1", evidence: "Patients log in and book sessions." },
  { id: "R2", evidence: "download invoices as PDF" },
];

const marks = (container: HTMLElement) => [...container.querySelectorAll("mark")].map((mark) => [mark.dataset.req, mark.textContent]);
// jsdom has no layout: the pane is 200 px tall and the mark sits at `top`.
const layout = (pane: HTMLElement, mark: Element, top: number) => {
  Object.defineProperty(pane, "clientHeight", { value: 200, configurable: true });
  Object.defineProperties(mark, { offsetTop: { value: top, configurable: true }, offsetHeight: { value: 20, configurable: true } });
};

describe("TranscriptPane", () => {
  let scrollTo: ReturnType<typeof vi.fn>;
  let reducedMotion: boolean;

  beforeEach(() => {
    reducedMotion = false;
    scrollTo = vi.fn();
    Object.defineProperty(HTMLElement.prototype, "scrollTo", { value: scrollTo, configurable: true }); // not in jsdom
    vi.stubGlobal("matchMedia", vi.fn((query: string) => ({ matches: query === "(prefers-reduced-motion: reduce)" && reducedMotion })));
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    Reflect.deleteProperty(HTMLElement.prototype, "scrollTo");
  });

  it("shows the whole transcript in a keyboard-scrollable region with each found quote marked", () => {
    const { container } = render(<TranscriptPane transcript={TRANSCRIPT} quotes={[...QUOTES, { id: "R3", evidence: "Not in the transcript" }]} />);
    const pane = screen.getByRole("region", { name: "Submitted transcript" });
    expect(pane).toHaveAttribute("tabindex", "0");
    expect(pane.textContent).toBe(TRANSCRIPT);
    expect(marks(container)).toEqual([
      ["R1", "Patients log in and book sessions"], // the quote's edge punctuation is trimmed, as the server does
      ["R2", "Download invoices as PDF"],
    ]);
  });

  it("marks overlapping quotes once per stretch, naming every requirement that covers it", () => {
    const { container } = render(
      <TranscriptPane transcript="Patients book and cancel sessions." quotes={[{ id: "R1", evidence: "book and cancel" }, { id: "R2", evidence: "cancel sessions" }]} />,
    );
    expect(marks(container)).toEqual([
      ["R1", "book and "],
      ["R1 R2", "cancel"],
      ["R2", " sessions"],
    ]);
  });

  it("highlights every mark of the active requirement and centres its first one in the pane, smoothly", () => {
    const { container, rerender } = render(<TranscriptPane transcript={TRANSCRIPT} quotes={QUOTES} />);
    const pane = screen.getByRole("region", { name: "Submitted transcript" });
    const r2 = container.querySelector('mark[data-req="R2"]');
    if (!r2) throw new Error("no mark for R2");
    layout(pane, r2, 900);

    rerender(<TranscriptPane transcript={TRANSCRIPT} quotes={QUOTES} active="R2" />);
    expect(r2).toHaveAttribute("data-active");
    expect(container.querySelector('mark[data-req="R1"]')).not.toHaveAttribute("data-active");
    expect(scrollTo).toHaveBeenCalledTimes(1);
    expect(scrollTo.mock.contexts[0]).toBe(pane);
    expect(scrollTo).toHaveBeenCalledWith({ top: 810, behavior: "smooth" }); // 900 - (200 - 20) / 2

    rerender(<TranscriptPane transcript={TRANSCRIPT} quotes={QUOTES} />);
    expect(r2).not.toHaveAttribute("data-active");
    expect(scrollTo).toHaveBeenCalledTimes(1); // leaving a requirement does not scroll
  });

  it("jumps instead of gliding when the user prefers reduced motion", () => {
    reducedMotion = true;
    const { container, rerender } = render(<TranscriptPane transcript={TRANSCRIPT} quotes={QUOTES} />);
    layout(screen.getByRole("region", { name: "Submitted transcript" }), container.querySelector("mark[data-req=R2]") as Element, 900);
    rerender(<TranscriptPane transcript={TRANSCRIPT} quotes={QUOTES} active="R2" />);
    expect(scrollTo).toHaveBeenCalledWith({ top: 810, behavior: "auto" });
  });

  it("scrolls once the active requirement's quote streams in, and not again on later snapshots", () => {
    // The mark does not exist when the requirement becomes active, so its layout comes from the prototype here.
    const offsetTop = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "offsetTop");
    const clientHeight = Object.getOwnPropertyDescriptor(Element.prototype, "clientHeight");
    Object.defineProperty(HTMLElement.prototype, "offsetTop", { configurable: true, get(this: HTMLElement) { return this.tagName === "MARK" ? 900 : 0; } });
    Object.defineProperty(Element.prototype, "clientHeight", { configurable: true, get: () => 200 });
    try {
      const { rerender } = render(<TranscriptPane transcript={TRANSCRIPT} quotes={[QUOTES[0]]} active="R2" />);
      expect(scrollTo).not.toHaveBeenCalled(); // R2's quote has not arrived yet
      rerender(<TranscriptPane transcript={TRANSCRIPT} quotes={[QUOTES[0], { id: "R2", evidence: "download invoices" }]} active="R2" />);
      expect(scrollTo).toHaveBeenCalledTimes(1);
      rerender(<TranscriptPane transcript={TRANSCRIPT} quotes={QUOTES} active="R2" />); // the quote grows
      expect(scrollTo).toHaveBeenCalledTimes(1); // the user may have scrolled since: no second jump for the same requirement
    } finally {
      if (offsetTop) Object.defineProperty(HTMLElement.prototype, "offsetTop", offsetTop);
      if (clientHeight) Object.defineProperty(Element.prototype, "clientHeight", clientHeight);
    }
  });

  it("leaves the scroll alone when the quote is already in view, or when the requirement has no mark", () => {
    const { container, rerender } = render(<TranscriptPane transcript={TRANSCRIPT} quotes={QUOTES} />);
    layout(screen.getByRole("region", { name: "Submitted transcript" }), container.querySelector("mark[data-req=R1]") as Element, 40);
    rerender(<TranscriptPane transcript={TRANSCRIPT} quotes={QUOTES} active="R1" />);
    rerender(<TranscriptPane transcript={TRANSCRIPT} quotes={QUOTES} active="R3" />);
    expect(scrollTo).not.toHaveBeenCalled();
  });
});
