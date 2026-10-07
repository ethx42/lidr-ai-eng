import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export const NotAvailable = () => <span className="text-muted-foreground">n/a</span>;

// One label and its value per line, the value right-aligned (numbers in tabular figures); `stacked` puts a long value
// under its label, full width.
export const Row = ({ label, mono, stacked, children }: { label: string; mono?: boolean; stacked?: boolean; children: ReactNode }) => (
  <div className={cn("flex py-1.5", stacked ? "flex-col gap-1" : "items-baseline justify-between gap-4")}>
    <dt className="shrink-0 text-muted-foreground">{label}</dt>
    <dd className={cn("num min-w-0", !stacked && "text-right", mono && "font-mono text-xs")}>{children}</dd>
  </div>
);

export const Rows = ({ children }: { children: ReactNode }) => <dl className="flex flex-col divide-y text-sm">{children}</dl>;
