import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export const NotAvailable = () => <span className="text-muted-foreground">n/a</span>;

// One label and its value per line, the value right-aligned (numbers in tabular figures).
export const Row = ({ label, mono, children }: { label: string; mono?: boolean; children: ReactNode }) => (
  <div className="flex items-baseline justify-between gap-4 py-1.5">
    <dt className="shrink-0 text-muted-foreground">{label}</dt>
    <dd className={cn("num min-w-0 text-right", mono && "font-mono text-xs")}>{children}</dd>
  </div>
);

export const Rows = ({ children }: { children: ReactNode }) => <dl className="flex flex-col divide-y text-sm">{children}</dl>;
