"use client";

import { ChevronRight, Copy } from "lucide-react";
import { useId } from "react";
import { Empty } from "@/components/estimate/section";
import { useServiceContext } from "@/components/service-context";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { copyText } from "@/lib/copy";
import { type ReferenceModel, readContext } from "@/lib/estimate/read";
import { NotAvailable, Row, Rows } from "./rows";

// Long prompt text scrolls inside its own box; focusable so keyboard users can scroll it too.
const CODE = "overflow-auto rounded-md border bg-background p-3 font-mono text-xs whitespace-pre-wrap wrap-anywhere";

const ContextSkeleton = () => (
  <div aria-busy="true" className="flex flex-col gap-4">
    <Skeleton className="h-5 w-full" />
    <Skeleton className="h-64 w-full" />
    {[0, 1, 2].map((i) => (
      <Skeleton key={i} className="h-20 w-full" />
    ))}
  </div>
);

const Reference = ({ reference: { size, meetingSummary, projectName, estimation } }: { reference: ReferenceModel }) => (
  <li className="flex flex-col gap-2 py-4">
    {(size || projectName) && (
      <div className="flex min-w-0 items-center gap-2">
        {size && (
          <Badge variant="outline" className="capitalize">
            {size}
          </Badge>
        )}
        {projectName && <h4 className="min-w-0 truncate text-sm font-medium">{projectName}</h4>}
      </div>
    )}
    <p className="text-sm whitespace-pre-line">{meetingSummary}</p>
    {estimation && (
      <details className="group">
        <summary className="flex min-h-6 w-fit cursor-pointer list-none items-center gap-1 rounded-sm text-xs font-medium text-muted-foreground hover:text-foreground [&::-webkit-details-marker]:hidden">
          <ChevronRight aria-hidden className="size-3.5 transition-transform group-open:rotate-90" />
          Estimation
        </summary>
        <pre role="region" aria-label={projectName ? `Estimation for ${projectName}` : "Estimation"} tabIndex={0} className={`mt-1 max-h-64 ${CODE}`}>
          {JSON.stringify(estimation, null, 2)}
        </pre>
      </details>
    )}
  </li>
);

// What the model sees on every call: the system prompt and the reference estimations injected into it (CAG).
export const ContextTab = () => {
  const context = useServiceContext();
  const promptId = useId();
  const referencesId = useId();
  if (context === undefined) return <ContextSkeleton />;
  const { promptVersion, systemPrompt, references } = readContext(context);
  if (!systemPrompt) return <Empty>The prompt and references could not be loaded from the AI service. Reload the page to try again.</Empty>;
  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-col gap-3">
        <Rows>
          <Row label="Prompt version" mono>
            {promptVersion ?? <NotAvailable />}
          </Row>
        </Rows>
        <div className="flex items-center justify-between gap-2">
          <h3 id={promptId} className="text-sm font-semibold">
            System prompt
          </h3>
          <Button type="button" variant="outline" size="xs" aria-label="Copy system prompt" onClick={() => void copyText(systemPrompt, "System prompt copied")}>
            <Copy />
            Copy
          </Button>
        </div>
        <pre role="region" aria-labelledby={promptId} tabIndex={0} className={`max-h-80 ${CODE}`}>
          {systemPrompt}
        </pre>
      </div>
      <div className="flex flex-col gap-1">
        <h3 id={referencesId} className="text-sm font-semibold">
          Reference estimations
        </h3>
        <p className="text-xs text-muted-foreground">Worked examples injected into the system prompt.</p>
        <ul role="list" aria-labelledby={referencesId} className="flex flex-col divide-y">
          {references.map((reference, i) => (
            <Reference key={i} reference={reference} />
          ))}
        </ul>
      </div>
    </div>
  );
};
