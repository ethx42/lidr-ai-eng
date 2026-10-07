"use client";

import { useEffect, useMemo, useRef } from "react";
import { type EvidenceQuote, type EvidenceRange, evidenceFinder } from "@/lib/evidence";
import { scrollBehavior } from "@/lib/focus";

type Props = { transcript: string; quotes: EvidenceQuote[]; active?: string | null };
type Segment = { text: string; ids: string[] };

// The transcript cut at every quote edge; a stretch several quotes cover names them all ("R1 R2").
const segment = (transcript: string, ranges: EvidenceRange[]): Segment[] => {
  const edges = [...new Set([0, transcript.length, ...ranges.flatMap(({ start, end }) => [start, end])])].sort((a, b) => a - b);
  return edges.slice(0, -1).map((start, i) => {
    const end = edges[i + 1];
    return { text: transcript.slice(start, end), ids: ranges.filter((range) => range.start <= start && range.end >= end).map(({ id }) => id) };
  });
};

// The submitted transcript with each quote behind a requirement marked. The active requirement's quote is highlighted
// and, when it is out of view, centred in this pane (its own scroll only: the page and the estimate never move): once
// per activation, as soon as its mark exists (while streaming, the quote may arrive after the requirement).
export const TranscriptPane = ({ transcript, quotes, active }: Props) => {
  const ref = useRef<HTMLDivElement>(null);
  const scrolledFor = useRef<string | null>(null);
  const find = useMemo(() => evidenceFinder(transcript), [transcript]);
  const segments = useMemo(() => segment(transcript, find(quotes)), [transcript, find, quotes]);

  useEffect(() => {
    const pane = ref.current;
    if (!active) scrolledFor.current = null;
    if (!active || !pane || scrolledFor.current === active) return;
    // Ids are model output, so they are compared, never put in a selector.
    const mark = [...pane.querySelectorAll("mark")].find((element) => element.dataset.req?.split(" ").includes(active));
    if (!mark) return;
    scrolledFor.current = active;
    const top = mark.offsetTop;
    if (top >= pane.scrollTop && top + mark.offsetHeight <= pane.scrollTop + pane.clientHeight) return;
    pane.scrollTo({ top: top - (pane.clientHeight - mark.offsetHeight) / 2, behavior: scrollBehavior() });
  }, [active, segments]);

  return (
    // `relative` makes the pane the marks' offsetParent and contains sr-only descendants; the focus ring is inset
    // because the pane fills its panel.
    <div
      ref={ref}
      role="region"
      aria-label="Submitted transcript"
      tabIndex={0}
      className="relative h-full overflow-y-auto px-4 py-4 focus-visible:-outline-offset-2! sm:px-6"
    >
      <p className="max-w-prose text-sm/6 whitespace-pre-wrap wrap-anywhere">
        {segments.map(({ text, ids }, i) =>
          ids.length === 0 ? (
            text
          ) : (
            <mark
              key={i}
              data-req={ids.join(" ")}
              data-active={(active && ids.includes(active)) || undefined}
              className="rounded-xs bg-accent text-foreground transition-colors box-decoration-clone data-active:bg-primary data-active:text-primary-foreground"
            >
              {text}
            </mark>
          ),
        )}
      </p>
    </div>
  );
};
