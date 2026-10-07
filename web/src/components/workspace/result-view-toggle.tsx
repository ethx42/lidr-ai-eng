"use client";

import { type ComponentProps, useCallback, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Segmented } from "@/components/form/segmented";

export type ResultView = "structured" | "document";

const VIEWS = ["structured", "document"] as const satisfies readonly ResultView[];
const LABELS: Record<ResultView, string> = { structured: "Structured", document: "Document" };

// Structured: the interactive estimate. Document: the server's markdown, laid out by the chosen output format.
export const ResultViewToggle = ({ value, onChange }: { value: ResultView; onChange: (view: ResultView) => void }) => (
  <Segmented label="Result view" hideLabel options={VIEWS} labels={LABELS} value={value} onChange={onChange} />
);

// The server's documents hold one table, the task breakdown (app/services/rendering.py), and its region is named so. A
// table wider than the pane (line items have eight columns) scrolls on its own, and only then is the region a tab stop,
// so keyboard users can scroll it; one that fits adds no stop. Watches the region and the table, whose width follows
// its text.
const ScrollTable = ({ children }: ComponentProps<"table">) => {
  const [scrolls, setScrolls] = useState(false);
  const observe = useCallback((region: HTMLDivElement) => {
    const observer = new ResizeObserver(() => setScrolls(region.scrollWidth > region.clientWidth));
    observer.observe(region);
    if (region.firstElementChild) observer.observe(region.firstElementChild);
    return () => observer.disconnect();
  }, []);
  return (
    <div
      ref={observe}
      role="region"
      aria-label="Task breakdown"
      tabIndex={scrolls ? 0 : undefined}
      className="overflow-x-auto rounded-md border focus-visible:-outline-offset-2!"
    >
      <table className="w-full min-w-max border-collapse text-sm">{children}</table>
    </div>
  );
};

// Markdown elements are styled from here, so no per-element component has to pass react-markdown's `node` along.
const DOCUMENT = [
  "flex min-w-0 flex-col gap-3 text-sm wrap-anywhere [&_p]:max-w-prose",
  "[&_h1]:text-2xl [&_h1]:font-semibold [&_h2]:text-2xl [&_h2]:font-semibold [&_h2]:text-balance [&_h3]:mt-3 [&_h3]:text-base [&_h3]:font-semibold",
  "[&_ul]:flex [&_ul]:list-disc [&_ul]:flex-col [&_ul]:gap-1 [&_ul]:pl-5 [&_ol]:list-decimal [&_ol]:pl-5",
  "[&_th]:border-b [&_th]:bg-surface [&_th]:px-3 [&_th]:py-2 [&_th]:text-left [&_th]:text-xs [&_th]:font-medium [&_th]:text-muted-foreground",
  "[&_td]:num [&_td]:border-b [&_td]:px-3 [&_td]:py-2 [&_tr:last-child>td]:border-b-0",
].join(" ");

// No raw HTML, no images and no links: the text comes from the model, which a transcript can steer, and an image
// would load its URL the moment it renders. HTML shows as text; images are dropped and links keep only their text.
export const EstimateDocument = ({ markdown }: { markdown: string }) => (
  <div className={DOCUMENT}>
    <Markdown remarkPlugins={[remarkGfm]} disallowedElements={["img", "a"]} unwrapDisallowed components={{ table: ScrollTable }}>
      {markdown}
    </Markdown>
  </div>
);
