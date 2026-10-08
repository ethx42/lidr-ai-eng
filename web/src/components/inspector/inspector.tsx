"use client";

import { PanelRight } from "lucide-react";
import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ContextTab } from "./context-tab";
import { type Call, MetricsTab } from "./metrics-tab";
import type { PromptContext } from "./use-prompt-context";

// `context` comes from `usePromptContext` in the workspace.
type Props = { call?: Call; context: PromptContext };

const TITLE = "text-sm font-semibold";
// Each tab scrolls on its own under the title and tab list; `relative` contains its sr-only descendants.
// The panel is the scroll container, so its focus ring (the global one, in --focus-ring) is drawn inset;
// `!` beats that unlayered rule's 2 px outer offset.
const PANEL = "relative min-h-0 overflow-y-auto p-4 focus-visible:-outline-offset-2!";

const InspectorBody = ({ call, context, title }: Props & { title: ReactNode }) => (
  <Tabs defaultValue="context" className="min-h-0 flex-1 gap-0">
    <div className="flex shrink-0 flex-col gap-3 border-b px-4 pt-4 pb-3">
      {title}
      <TabsList className="w-full">
        <TabsTrigger value="context">Context</TabsTrigger>
        <TabsTrigger value="call">Last call</TabsTrigger>
      </TabsList>
    </div>
    <TabsContent value="context" className={PANEL}>
      <ContextTab context={context} />
    </TabsContent>
    <TabsContent value="call" className={PANEL}>
      <MetricsTab call={call} />
    </TabsContent>
  </Tabs>
);

// The inspector (spec §8 transparency: the prompt, its references and the last call's metrics) opens from a header
// button as a sheet at every width; the workspace's right column holds the project memory. The sheet is a modal dialog:
// focus is trapped, Esc closes it, and focus returns to the button.
export const InspectorSheet = ({ call, context }: Props) => (
  <Sheet>
    <SheetTrigger asChild>
      <Button type="button" variant="ghost">
        <PanelRight />
        <span className="sr-only sm:not-sr-only">Inspector</span>
      </Button>
    </SheetTrigger>
    {/* No description: the title and tabs say what the sheet holds. */}
    <SheetContent aria-describedby={undefined} className="gap-0 data-[side=right]:w-full data-[side=right]:sm:max-w-md">
      <InspectorBody call={call} context={context} title={<SheetTitle className={TITLE}>Inspector</SheetTitle>} />
    </SheetContent>
  </Sheet>
);
