"use client";

import { ArrowRight } from "lucide-react";
import type { ReactNode } from "react";
import { useServiceContext } from "@/components/service-context";
import { formatProvider } from "@/lib/estimate/format";
import { ThemeToggle } from "./theme-toggle";

// Chain entries are "provider:model", primary first, then fallbacks in order.
const parseEntry = (entry: string) => {
  const at = entry.indexOf(":");
  return at < 0 ? { provider: entry, model: "" } : { provider: entry.slice(0, at), model: entry.slice(at + 1) };
};

// The model is omitted when it only repeats the provider (replay reports "replay:replay").
const Model = ({ entry }: { entry: string }) => {
  const { provider, model } = parseEntry(entry);
  return (
    <span className="truncate">
      {formatProvider(provider)}
      {model && model !== provider && (
        <>
          {" "}
          <span className="font-mono text-foreground">{model}</span>
        </>
      )}
    </span>
  );
};

const ModelChain = () => {
  const context = useServiceContext();
  if (context === undefined) return <span data-slot="skeleton" className="h-5 w-36 rounded-4xl bg-muted motion-safe:animate-pulse" />;
  if (!context?.chain.length) return null;
  const [primary, ...fallbacks] = context.chain;
  return (
    <p className="flex h-6 min-w-0 items-center gap-1.5 rounded-4xl border px-2.5 text-xs text-muted-foreground">
      <span className="sr-only">Model:</span>
      <Model entry={primary} />
      {fallbacks.map((entry) => (
        <span key={entry} className="hidden min-w-0 items-center gap-1.5 sm:flex">
          <ArrowRight className="size-3 shrink-0" />
          <span className="sr-only">falls back to</span>
          <Model entry={entry} />
        </span>
      ))}
    </p>
  );
};

export const AppHeader = ({ actions }: { actions?: ReactNode }) => (
  <header className="flex h-12 shrink-0 items-center gap-3 border-b px-4 sm:px-6">
    <h1 className="text-sm font-semibold">Estimator</h1>
    <ModelChain />
    <div className="ml-auto flex items-center gap-1">
      {actions}
      <ThemeToggle />
    </div>
  </header>
);
