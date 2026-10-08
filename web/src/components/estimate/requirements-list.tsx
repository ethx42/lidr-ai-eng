"use client";

import { Quote, TriangleAlert } from "lucide-react";
import { useId, useState } from "react";
import { HoverCard, HoverCardContent, HoverCardTrigger } from "@/components/ui/hover-card";
import { type EstimateModel, received } from "@/lib/estimate/read";
import { EstimateSkeleton, Pending } from "./estimate-skeleton";
import { Empty, Section } from "./section";

type Requirement = NonNullable<EstimateModel["requirements"]>[number];
type FocusHandler = (id: string | null) => void;
// The action that pins a requirement, or undefined when it has no mark in the transcript to show.
type PinFor = (id: string) => (() => void) | undefined;
// The card's caption for a grounded quote that is not in the transcript shown (it came from an earlier message or an
// attachment), or undefined for the default.
type EvidenceNote = (id: string) => string | undefined;

// Radix opens a hover card on mouse hover and keyboard focus but ignores touch (and cancels the tap), so touch opens it
// explicitly. With `onPin` (a quote marked in the transcript behind the turn's disclosure) a click or a tap shows the
// quote there instead: the card closes, and stays shut until the button is hovered or focused again, because Radix can
// still fire an open timer the click left behind (stack.md), beside a button the page has scrolled away from.
const Evidence = ({ id, quote, ungrounded, note, onPin }: { id?: string; quote: string; ungrounded: boolean; note?: string; onPin?: () => void }) => {
  const [open, setOpen] = useState(false);
  const [pinned, setPinned] = useState(false);
  const descriptionId = useId();
  const show = (next: boolean) => setOpen(next && !pinned);
  const again = () => setPinned(false);
  const pin = (run: () => void) => {
    setPinned(true);
    setOpen(false);
    run();
  };
  return (
    <HoverCard open={open} onOpenChange={show} openDelay={200} closeDelay={150}>
      <HoverCardTrigger asChild>
        <button
          type="button"
          aria-label={id ? `Evidence for ${id}` : "Evidence"}
          aria-describedby={descriptionId}
          onClick={() => (onPin ? pin(onPin) : show(true))}
          onPointerEnter={again}
          onFocus={again}
          onPointerDown={(event) => event.pointerType === "touch" && !onPin && show(true)}
          className="inline-flex h-6 items-center gap-1 rounded-sm px-2 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
        >
          <Quote className="size-3.5" />
          Evidence
        </button>
      </HoverCardTrigger>
      <span id={descriptionId} className="sr-only">{`“${quote}”`}</span>
      <HoverCardContent align="end" className="flex w-80 max-w-[calc(100vw-2rem)] flex-col gap-2 wrap-anywhere">
        <p className="text-xs text-muted-foreground">{ungrounded ? "Quote given by the model, not found in the transcript" : (note ?? "Quote from the transcript")}</p>
        <blockquote className="border-l-2 border-border-strong pl-3 text-sm">{`“${quote}”`}</blockquote>
      </HoverCardContent>
    </HoverCard>
  );
};

type RowProps = { requirement: Requirement; ungrounded: boolean; active: boolean; onFocusChange?: FocusHandler; pinFor?: PinFor; evidenceNote?: EvidenceNote };

const Row = ({ requirement: { id, statement, evidence }, ungrounded, active, onFocusChange, pinFor, evidenceNote }: RowProps) => {
  const enter = () => id && onFocusChange?.(id);
  const leave = () => id && onFocusChange?.(null);
  return (
    <li
      data-active={active || undefined}
      onMouseEnter={enter}
      onMouseLeave={leave}
      onFocus={enter}
      onBlur={(event) => !event.currentTarget.contains(event.relatedTarget) && leave()}
      className="group/requirement border-b py-1"
    >
      <div className="-mx-2 grid grid-cols-[2rem_minmax(0,1fr)_auto] items-start gap-x-3 rounded-sm px-2 py-1 group-data-active/requirement:bg-accent group-data-active/requirement:text-accent-foreground">
        <span className="font-mono text-xs leading-5 text-muted-foreground">{id ?? <Pending className="mt-1 h-3 w-6" />}</span>
        <div className="flex min-w-0 flex-col gap-1 text-sm wrap-anywhere">
          {statement ? <p>{statement}</p> : <Pending className="w-4/5" />}
          {ungrounded && (
            <p className="flex items-center gap-1 text-xs text-ungrounded">
              <TriangleAlert className="size-3.5 shrink-0" />
              Quote not found in the transcript
            </p>
          )}
        </div>
        {evidence ? (
          <Evidence id={id} quote={evidence} ungrounded={ungrounded} note={id ? evidenceNote?.(id) : undefined} onPin={id ? pinFor?.(id) : undefined} />
        ) : (
          <Pending className="mt-1 w-16" />
        )}
      </div>
    </li>
  );
};

type Props = {
  items?: EstimateModel["requirements"];
  streaming: boolean;
  ungrounded: Set<string>;
  activeRequirement?: string;
  onRequirementFocus?: FocusHandler;
  pinFor?: PinFor;
  evidenceNote?: EvidenceNote;
};

export const RequirementsList = ({ items, streaming, ungrounded, activeRequirement, onRequirementFocus, pinFor, evidenceNote }: Props) => {
  const requirements = received(items, streaming);
  return (
    <Section title="Requirements">
      {!requirements ? (
        <EstimateSkeleton shape="list" />
      ) : requirements.length === 0 ? (
        <Empty>No requirements stated in the transcript.</Empty>
      ) : (
        <ul role="list" className="flex flex-col">
          {requirements.map((requirement, i) => (
            <Row
              key={i}
              requirement={requirement}
              ungrounded={requirement.id !== undefined && ungrounded.has(requirement.id)}
              active={requirement.id !== undefined && requirement.id === activeRequirement}
              onFocusChange={onRequirementFocus}
              pinFor={pinFor}
              evidenceNote={evidenceNote}
            />
          ))}
        </ul>
      )}
    </Section>
  );
};
