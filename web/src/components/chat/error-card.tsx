"use client";

import { CircleAlert } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { copyText } from "@/lib/copy";
import { toUserMessage } from "@/lib/errors";
import type { StreamError } from "@/lib/estimate/types";

// `onRetry` absent: this attempt can no longer run again (a later turn of the conversation exists).
type Props = { error: StreamError; keptPrevious?: boolean; onRetry?: () => void; onEditTranscript: () => void };
type Action = { label: string; run: () => void };

// What the user can do next, mapped from the error taxonomy; `role="alert"` announces it once.
export const ErrorCard = ({ error, keptPrevious = false, onRetry, onEditTranscript }: Props) => {
  const { title, action } = toUserMessage(error);
  const { requestId } = error;
  const retry: Action[] = onRetry ? [{ label: "Try again", run: onRetry }] : [];
  const actions: Action[] =
    action === "shorten"
      ? [{ label: "Edit transcript", run: onEditTranscript }]
      : action === "attachments" // the same files would be refused again
        ? [{ label: "Edit attachments", run: onEditTranscript }]
        : action === "contact" && requestId
          ? [{ label: "Copy request ID", run: () => void copyText(requestId, "Request ID copied") }, ...retry]
          : retry;
  const [primary, secondary] = actions;
  return (
    <Alert className="border-destructive/40 bg-danger-subtle">
      <CircleAlert className="text-destructive" />
      <AlertTitle className="text-foreground">{title}</AlertTitle>
      <AlertDescription className="flex flex-col items-start gap-3 text-foreground">
        {keptPrevious && <div>The previous estimate is kept below.</div>}
        {requestId && (
          <div className="text-xs text-muted-foreground">
            Request ID <code className="font-mono text-foreground">{requestId}</code>
          </div>
        )}
        {primary && (
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="outline" size="sm" onClick={primary.run}>
              {primary.label}
            </Button>
            {secondary && (
              <Button type="button" variant="ghost" size="sm" onClick={secondary.run}>
                {secondary.label}
              </Button>
            )}
          </div>
        )}
      </AlertDescription>
    </Alert>
  );
};
