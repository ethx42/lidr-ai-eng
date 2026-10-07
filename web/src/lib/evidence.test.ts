import { describe, expect, it } from "vitest";
import { evidenceFinder, findEvidenceRanges } from "./evidence";

describe("findEvidenceRanges", () => {
  it("finds exact quotes and skips missing ones", () => {
    const t = "We need online booking. Payments via Stripe.";
    expect(findEvidenceRanges(t, [
      { id: "R1", evidence: "online booking" },
      { id: "R2", evidence: "not there" },
    ])).toEqual([{ id: "R1", start: 8, end: 22 }]);
  });
  it("matches the first occurrence and tolerates partial (streaming) quotes", () => {
    expect(findEvidenceRanges("a b a b", [{ id: "R1", evidence: "a b" }])[0]).toMatchObject({ start: 0, end: 3 });
    expect(findEvidenceRanges("abc", [{ id: "R1", evidence: "" }])).toEqual([]);
  });
  it("matches like the server's grounding check: case, typography, whitespace, quote edges", () => {
    const t = "Client: We need a booking app for our “yoga studio”.\nPM:  Mobile   first, launch soon.";
    const [r1, r2] = findEvidenceRanges(t, [
      { id: "R1", evidence: "\"Yoga Studio\"" },
      { id: "R2", evidence: "mobile first," },
    ]);
    expect(r1).toEqual({ id: "R1", start: t.indexOf("yoga studio"), end: t.indexOf("yoga studio") + "yoga studio".length });
    expect(r2).toEqual({ id: "R2", start: t.indexOf("Mobile"), end: t.indexOf("first") + "first".length });
  });

  it("maps a match back to the original text across NFKC, combining marks, full case folding and dashes", () => {
    const t = "Ana: the cafe\u0301 needs a ﬁle export — STRASSE address,\u00a0Σ-tier pricing.";
    const ranges = findEvidenceRanges(t, [
      { id: "R1", evidence: "café needs a file export - straße" },
      { id: "R2", evidence: "(ς-TIER PRICING.)" },
    ]);
    expect(ranges).toEqual([
      { id: "R1", start: t.indexOf("cafe"), end: t.indexOf("STRASSE") + "STRASSE".length },
      { id: "R2", start: t.indexOf("Σ"), end: t.indexOf("pricing") + "pricing".length },
    ]);
  });

  it("collapses the whitespace the server collapses, not only spaces", () => {
    const t = "Booking\u2028\u3000and\x1cpayments";
    expect(findEvidenceRanges(t, [{ id: "R1", evidence: "booking and payments" }])).toEqual([{ id: "R1", start: 0, end: t.length }]);
  });

  it("skips a quote that is only punctuation once its edges are trimmed", () => {
    expect(findEvidenceRanges("Yes. No.", [{ id: "R1", evidence: " .\"" }])).toEqual([]);
  });

  it("returns the ranges in the order of the quotes, overlapping ones included", () => {
    const t = "Patients book and cancel sessions.";
    expect(findEvidenceRanges(t, [
      { id: "R2", evidence: "cancel sessions" },
      { id: "R1", evidence: "book and cancel" },
    ])).toEqual([
      { id: "R2", start: 18, end: 33 },
      { id: "R1", start: 9, end: 24 },
    ]);
  });

  it("normalises a transcript once per finder, for every snapshot of the quotes", () => {
    const find = evidenceFinder("We need online booking. Payments via Stripe.");
    expect(find([{ id: "R1", evidence: "online boo" }])).toEqual([{ id: "R1", start: 8, end: 18 }]);
    expect(find([{ id: "R1", evidence: "online booking" }])).toEqual([{ id: "R1", start: 8, end: 22 }]);
  });
});
