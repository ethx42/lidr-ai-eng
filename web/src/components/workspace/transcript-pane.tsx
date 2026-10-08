"use client";

import { type RefObject, useEffect, useMemo, useRef } from "react";
import { type EvidenceQuote, type EvidenceRange, evidenceFinder } from "@/lib/evidence";
import { scrollBehavior } from "@/lib/focus";
import { cn } from "@/lib/utils";

// A requirement pinned from its Evidence button: a new object per pin, so pinning it again brings its quote back into view.
export type Pin = { id: string };
// `label` names the region (one per turn in a conversation); `className` sizes it where the parent does not.
type Props = {
  transcript: string;
  quotes: EvidenceQuote[];
  active?: string | null;
  pinned?: Pin | null;
  label?: string;
  className?: string;
  ref?: RefObject<HTMLDivElement | null>;
};
type Segment = { text: string; ids: string[] };

// The transcript cut at every quote edge; a stretch several quotes cover names them all ("R1 R2").
const segment = (transcript: string, ranges: EvidenceRange[]): Segment[] => {
  const edges = [...new Set([0, transcript.length, ...ranges.flatMap(({ start, end }) => [start, end])])].sort((a, b) => a - b);
  return edges.slice(0, -1).map((start, i) => {
    const end = edges[i + 1];
    return { text: transcript.slice(start, end), ids: ranges.filter((range) => range.start <= start && range.end >= end).map(({ id }) => id) };
  });
};

// Ids are model output, so they are compared, never put in a selector.
const markOf = (pane: HTMLElement, id: string) => [...pane.querySelectorAll("mark")].find((element) => element.dataset.req?.split(" ").includes(id));

// The submitted transcript with each quote behind a requirement marked. The active requirement's quote (hovered or
// focused, else pinned) is highlighted. An active one out of view is centred in this pane (its own scroll only: the page
// and the estimate never move); a pinned one is brought into view through every scrolling ancestor, the page included,
// because the pane sits in its turn's header, usually far above the requirement. Each happens once per activation or
// pin, as soon as the mark exists (while streaming, the quote may arrive after the requirement).
export const TranscriptPane = ({ transcript, quotes, active, pinned, label = "Submitted transcript", className, ref }: Props) => {
  const own = useRef<HTMLDivElement>(null);
  const pane = ref ?? own;
  const scrolledFor = useRef<string | null>(null);
  const revealed = useRef<Pin | null>(null);
  const find = useMemo(() => evidenceFinder(transcript), [transcript]);
  const segments = useMemo(() => segment(transcript, find(quotes)), [transcript, find, quotes]);
  const highlighted = active ?? pinned?.id;

  useEffect(() => {
    const element = pane.current;
    if (!active) scrolledFor.current = null;
    if (!active || !element || scrolledFor.current === active) return;
    const mark = markOf(element, active);
    if (!mark) return;
    scrolledFor.current = active;
    const top = mark.offsetTop;
    if (top >= element.scrollTop && top + mark.offsetHeight <= element.scrollTop + element.clientHeight) return;
    element.scrollTo({ top: top - (element.clientHeight - mark.offsetHeight) / 2, behavior: scrollBehavior() });
  }, [pane, active, segments]);

  useEffect(() => {
    const element = pane.current;
    if (!pinned || !element || revealed.current === pinned) return;
    const mark = markOf(element, pinned.id);
    if (!mark) return;
    revealed.current = pinned;
    mark.scrollIntoView({ block: "center", behavior: scrollBehavior() });
  }, [pane, pinned, segments]);

  return (
    // `relative` makes the pane the marks' offsetParent and contains sr-only descendants; the focus ring is inset
    // because the pane fills its panel.
    <div
      ref={pane}
      role="region"
      aria-label={label}
      tabIndex={0}
      className={cn("relative h-full overflow-y-auto px-4 py-4 focus-visible:-outline-offset-2! sm:px-6", className)}
    >
      <p className="max-w-prose text-sm/6 whitespace-pre-wrap wrap-anywhere">
        {segments.map(({ text, ids }, i) =>
          ids.length === 0 ? (
            text
          ) : (
            <mark
              key={i}
              data-req={ids.join(" ")}
              data-active={(highlighted && ids.includes(highlighted)) || undefined}
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
