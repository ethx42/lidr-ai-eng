"use client";

import { PanelRight } from "lucide-react";
import { type ReactNode, type Ref, type RefObject, useEffect, useId, useState } from "react";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ContextTab } from "./context-tab";
import { type Call, MetricsTab } from "./metrics-tab";

type Props = { call?: Call };

const TITLE = "text-sm font-semibold";
// Matches Tailwind's `lg`, where the panel replaces the sheet.
const WIDE = "(min-width: 1024px)";
// Each tab scrolls on its own under the title and tab list; `relative` contains its sr-only descendants.
// The panel is the scroll container, so its focus ring (the global one, in --focus-ring) is drawn inset;
// `!` beats that unlayered rule's 2 px outer offset.
const PANEL = "relative min-h-0 overflow-y-auto p-4 focus-visible:-outline-offset-2!";

const InspectorBody = ({ call, title }: Props & { title: ReactNode }) => (
  <Tabs defaultValue="context" className="min-h-0 flex-1 gap-0">
    <div className="flex shrink-0 flex-col gap-3 border-b px-4 pt-4 pb-3">
      {title}
      <TabsList className="w-full">
        <TabsTrigger value="context">Context</TabsTrigger>
        <TabsTrigger value="call">Last call</TabsTrigger>
      </TabsList>
    </div>
    <TabsContent value="context" className={PANEL}>
      <ContextTab />
    </TabsContent>
    <TabsContent value="call" className={PANEL}>
      <MetricsTab call={call} />
    </TabsContent>
  </Tabs>
);

// From 1024 px: a panel beside the thread. Below that it is hidden and `InspectorSheet` opens the same content.
export const InspectorPanel = ({ call, ref }: Props & { ref?: Ref<HTMLElement> }) => {
  const titleId = useId();
  return (
    <aside ref={ref} tabIndex={-1} aria-labelledby={titleId} className="hidden w-88 shrink-0 flex-col border-l bg-surface lg:flex xl:w-96">
      <InspectorBody
        call={call}
        title={
          <h2 id={titleId} className={TITLE}>
            Inspector
          </h2>
        }
      />
    </aside>
  );
};

// The header button below 1024 px; the sheet is a modal dialog (focus trapped, Esc closes, focus returns to the button).
// Widening past 1024 px closes it and hands focus to the panel, because the button is hidden from then on.
export const InspectorSheet = ({ call, panelRef }: Props & { panelRef: RefObject<HTMLElement | null> }) => {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open) return;
    const wide = window.matchMedia(WIDE);
    const close = () => {
      if (wide.matches) setOpen(false);
    };
    wide.addEventListener("change", close);
    return () => wide.removeEventListener("change", close);
  }, [open]);

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        <Button type="button" variant="ghost" className="lg:hidden">
          <PanelRight />
          <span className="sr-only sm:not-sr-only">Inspector</span>
        </Button>
      </SheetTrigger>
      {/* No description: the title and tabs say what the sheet holds. */}
      <SheetContent
        aria-describedby={undefined}
        onCloseAutoFocus={(event) => {
          if (!window.matchMedia(WIDE).matches) return; // the button is visible: Radix returns focus to it
          event.preventDefault();
          panelRef.current?.focus();
        }}
        className="gap-0 data-[side=right]:w-full data-[side=right]:sm:max-w-md"
      >
        <InspectorBody call={call} title={<SheetTitle className={TITLE}>Inspector</SheetTitle>} />
      </SheetContent>
    </Sheet>
  );
};
