import { ArrowRightLeft, Copy } from "lucide-react";
import { Empty } from "@/components/estimate/section";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { copyText } from "@/lib/copy";
import { formatMs, formatProvider, formatUsd } from "@/lib/estimate/format";
import { readCallMetrics, readText } from "@/lib/estimate/read";
import type { StreamState } from "@/lib/estimate/types";
import { formatCount } from "@/lib/transcript";
import { NotAvailable, Row, Rows } from "./rows";

export type Call = Extract<StreamState, { status: "done" }>;

const show = <T,>(value: T | undefined, format: (value: T) => string) => (value === undefined ? <NotAvailable /> : format(value));

export const MetricsTab = ({ call }: { call?: Call }) => {
  if (!call) return <Empty>Run an estimate to see its metrics.</Empty>;
  const metrics = readCallMetrics(call.result);
  const requestId = readText(call.requestId);
  return (
    <div className="flex flex-col gap-6">
      {metrics.projectName && <p className="text-sm font-medium">{metrics.projectName}</p>}
      <Rows>
        <Row label="Provider">
          <span className="inline-flex flex-wrap items-center justify-end gap-2">
            {show(metrics.provider, formatProvider)}
            {metrics.fallbackUsed && (
              <Badge variant="outline" className="text-info">
                <ArrowRightLeft />
                Fallback used
              </Badge>
            )}
          </span>
        </Row>
        <Row label="Model" mono>
          {show(metrics.model, String)}
        </Row>
        <Row label="Prompt version" mono>
          {show(metrics.promptVersion, String)}
        </Row>
      </Rows>
      <Rows>
        <Row label="Input tokens">{show(metrics.inputTokens, formatCount)}</Row>
        <Row label="Cached input tokens">{show(metrics.cachedTokens, formatCount)}</Row>
        <Row label="Output tokens">{show(metrics.outputTokens, formatCount)}</Row>
      </Rows>
      <Rows>
        <Row label="Latency">{show(metrics.latencyMs, formatMs)}</Row>
        <Row label="Time to first token">{show(metrics.ttftMs, formatMs)}</Row>
        <Row label="Cost">{show(metrics.costUsd, formatUsd)}</Row>
        <Row label="Cache hit">{show(metrics.cacheHit, (hit) => (hit ? "Yes" : "No"))}</Row>
      </Rows>
      <Rows>
        <Row label="Request ID" stacked>
          {requestId ? (
            // A UUID fills a line of the panel; Copy wraps under it when both do not fit.
            <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <code className="min-w-0 font-mono text-xs wrap-anywhere">{requestId}</code>
              <Button type="button" variant="outline" size="xs" aria-label="Copy request ID" onClick={() => void copyText(requestId, "Request ID copied")}>
                <Copy />
                Copy
              </Button>
            </span>
          ) : (
            <NotAvailable />
          )}
        </Row>
      </Rows>
    </div>
  );
};
