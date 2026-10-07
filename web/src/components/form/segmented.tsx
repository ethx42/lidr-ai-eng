"use client";

import { useId } from "react";
import { FieldTitle } from "@/components/ui/field";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { cn } from "@/lib/utils";

type Props<T extends string> = {
  label: string;
  hideLabel?: boolean; // named for assistive technology only, when the context already says what it is
  options: readonly T[];
  labels: Record<T, string>;
  value: T;
  onChange: (value: T) => void;
};

// The chosen option: a tinted fill and an inset primary outline (>= 3:1 on the page in both themes), not colour alone.
const ITEM =
  "text-muted-foreground hover:text-foreground data-[state=on]:bg-accent data-[state=on]:text-accent-foreground data-[state=on]:shadow-[inset_0_0_0_1px_var(--color-primary)]";

// A segmented control: a radio group (Radix ToggleGroup "single") that always keeps one option chosen.
export const Segmented = <T extends string>({ label, hideLabel = false, options, labels, value, onChange }: Props<T>) => {
  const labelId = useId();
  const group = (
    <ToggleGroup
      type="single"
      size="sm"
      spacing={0.5}
      value={value}
      onValueChange={(next) => {
        const picked = options.find((option) => option === next); // "" when the chosen one is clicked again
        if (picked) onChange(picked);
      }}
      {...(hideLabel ? { "aria-label": label } : { "aria-labelledby": labelId })}
      // four options do not fit one row on a phone: two even rows rather than one ragged wrap
      className={cn("flex-wrap rounded-lg border border-input p-0.5", options.length > 3 && "max-sm:grid max-sm:grid-cols-2")}
    >
      {options.map((option) => (
        <ToggleGroupItem key={option} value={option} className={ITEM}>
          {labels[option]}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  );
  if (hideLabel) return group;
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <FieldTitle id={labelId}>{label}</FieldTitle>
      {group}
    </div>
  );
};
