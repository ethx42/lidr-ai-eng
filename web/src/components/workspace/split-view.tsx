"use client";

import { type ReactNode, type Ref, useId } from "react";
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useMediaQuery } from "@/hooks/use-media-query";
import { cn } from "@/lib/utils";

export type SplitTab = "transcript" | "estimate";
// `description`: under the heading; side by side one line, cut short (whole on hover) when the pane is too narrow, and
// below 768 px wrapped, since a cut line's title is out of reach by touch and keyboard. `aside`: controls at the right.
type Pane = { label: string; description?: string; aside?: ReactNode; children: ReactNode };
type Props = { transcript: Pane; estimate: Pane; tab: SplitTab; onTabChange: (tab: SplitTab) => void; className?: string; ref?: Ref<HTMLDivElement> };

// Tailwind's `md`: from here the panes sit side by side.
export const WIDE = "(min-width: 48rem)";
// The `short` variant (globals.css, which derives its 48.25rem): the page scrolls as a whole and the split sits a
// viewport tall below the form.
export const SHORT = "(max-height: 30rem), (min-width: 48rem) and (max-height: 48.25rem)";

// Both panes stay mounted in either layout, so a stream keeps its Stop, Esc and announcements behind the other tab.
// Side by side there are no tabs: a pane is a group named by its heading, not a tab stop. Below 768 px it is a tab
// panel, and CSS hides the inactive one.
const SplitPane = ({ value, pane, wide }: { value: SplitTab; pane: Pane; wide: boolean }) => {
  const headingId = useId();
  return (
    <TabsContent
      value={value}
      forceMount
      {...(wide ? { role: "group", "aria-labelledby": headingId, tabIndex: undefined } : {})}
      className="flex h-full min-h-0 flex-col focus-visible:-outline-offset-2! max-md:data-[state=inactive]:hidden"
    >
      {/* Side by side, one fixed height for both panes' headers, which fits the heading over its description and the
          result view toggle: their rules line up, and nothing below moves when the toggle arrives with the result. */}
      <div
        className={cn(
          "flex min-h-11 shrink-0 items-center gap-3 border-b px-4 py-1 sm:px-6 md:h-11 md:py-0",
          !pane.aside && !pane.description && "max-md:hidden",
        )}
      >
        <div className="flex min-w-0 flex-1 flex-col">
          <h2 id={headingId} className="text-sm font-semibold max-md:hidden">
            {pane.label}
          </h2>
          {pane.description && (
            <p title={pane.description} className="text-xs text-muted-foreground md:truncate">
              {pane.description}
            </p>
          )}
        </div>
        {pane.aside}
      </div>
      <div className="min-h-0 flex-1">{pane.children}</div>
    </TabsContent>
  );
};

// Results beside the transcript (spec §6.5): a resizable split from 768 px, "Transcript | Estimate" tabs below it.
// One tree for both, laid out by CSS, so crossing 768 px keeps the panes' state, focus and scroll; the media query
// only switches the tab list, the panes' roles and the resizing on and off.
export const SplitView = ({ transcript, estimate, tab, onTabChange, className, ref }: Props) => {
  const wide = useMediaQuery(WIDE, true);
  return (
    <Tabs
      ref={ref}
      data-slot="split-view"
      value={tab}
      onValueChange={(value) => onTabChange(value === "transcript" ? "transcript" : "estimate")}
      className={cn("gap-0", className)}
    >
      {!wide && (
        <div className="border-b px-4 py-2">
          <TabsList aria-label="Result" className="w-full">
            <TabsTrigger value="transcript">{transcript.label}</TabsTrigger>
            <TabsTrigger value="estimate">{estimate.label}</TabsTrigger>
          </TabsList>
        </div>
      )}
      {/* Below 768 px the group drops its inline flex sizing (hence `!`) and the panes stack, one shown at a time. */}
      <ResizablePanelGroup orientation="horizontal" disabled={!wide} className="max-md:block! max-md:h-auto! max-md:overflow-visible!">
        <ResizablePanel id="transcript" defaultSize="40%" minSize="16rem">
          <SplitPane value="transcript" pane={transcript} wide={wide} />
        </ResizablePanel>
        <ResizableHandle withHandle disabled={!wide} aria-label="Resize the transcript and the estimate" className="max-md:hidden" />
        <ResizablePanel id="estimate" defaultSize="60%" minSize="20rem">
          <SplitPane value="estimate" pane={estimate} wide={wide} />
        </ResizablePanel>
      </ResizablePanelGroup>
    </Tabs>
  );
};
