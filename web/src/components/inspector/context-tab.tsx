"use client";

import { ChevronRight, CircleAlert, Copy, RotateCcw } from "lucide-react";
import { useId } from "react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { copyText } from "@/lib/copy";
import { type ReferenceModel, readContext } from "@/lib/estimate/read";
import { NotAvailable, Row, Rows } from "./rows";
import type { PromptContext } from "./use-prompt-context";

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

// Where the version will show once the prompt for new choices arrives: a skeleton-style tag that dims nothing.
const Updating = () => (
  <span className="inline-flex items-center gap-1.5 font-sans">
    <span aria-hidden data-slot="skeleton" className="h-3 w-6 rounded-sm bg-muted motion-safe:animate-pulse" />
    Updating…
  </span>
);

type ContextErrorProps = { title: string; description?: string; busy?: boolean; onRetry: () => void };

// Never "reload the page": the run on screen lives only in memory. Retry asks again for the same choices, and shows it
// is busy while it does; focus moves to the tab panel first, because the error may go away. No live region: an
// assertive alert remounted with each failed refetch would interrupt every choice in the form (spec §8).
const ContextError = ({ title, description, busy = false, onRetry }: ContextErrorProps) => (
  <Alert role={undefined} aria-busy={busy} className="border-destructive/40 bg-danger-subtle">
    <CircleAlert className="text-destructive" />
    <AlertTitle className="text-foreground">{title}</AlertTitle>
    <AlertDescription className="flex flex-col items-start gap-2 text-foreground">
      {description && <p>{description}</p>}
      <Button
        type="button"
        variant="outline"
        size="xs"
        onClick={(event) => {
          if (busy) return;
          event.currentTarget.closest<HTMLElement>('[role="tabpanel"]')?.focus({ preventScroll: true });
          onRetry();
        }}
      >
        {busy ? (
          <Updating />
        ) : (
          <>
            <RotateCcw />
            Retry
          </>
        )}
      </Button>
    </AlertDescription>
  </Alert>
);

const UNAVAILABLE = "The prompt and references could not be loaded from the AI service.";

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
    <p className="text-xs whitespace-pre-line text-muted-foreground">{meetingSummary}</p>
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

// What the model sees for the form's current choices: the system prompt and the reference estimations injected into it
// (CAG). While the prompt for new choices loads, the previous one stays, marked busy, at full contrast; if it cannot be
// loaded, the previous one stays under an error that offers to try again.
export const ContextTab = ({ context: { context, loading, failed, retry } }: { context: PromptContext }) => {
  const promptId = useId();
  const referencesId = useId();
  if (context === undefined && !failed) return <ContextSkeleton />;
  const { promptVersion, systemPrompt, references } = readContext(context);
  if (!systemPrompt) return <ContextError title={UNAVAILABLE} busy={loading} onRetry={retry} />;
  return (
    <div aria-busy={loading} className="flex flex-col gap-8">
      {failed && <ContextError title="Could not load the prompt for these choices." description="The prompt below is for your previous choices." onRetry={retry} />}
      <div className="flex flex-col gap-3">
        <Rows>
          <Row label="Prompt version" mono>
            {loading ? <Updating /> : (promptVersion ?? <NotAvailable />)}
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
