"use client";

import { RadioGroup } from "radix-ui";
import { useId } from "react";
import { FieldTitle } from "@/components/ui/field";
import { toggleVariants } from "@/components/ui/toggle";
import { cn } from "@/lib/utils";

type Props<T extends string> = {
  label: string;
  hideLabel?: boolean; // named for assistive technology only, when the context already says what it is
  options: readonly T[];
  labels: Record<T, string>;
  value: T;
  onChange: (value: T) => void;
};

// Each option looks like a small toggle. The chosen one: a tinted fill and an inset primary outline (>= 3:1 on the page
// in both themes), not colour alone.
const ITEM = cn(
  toggleVariants({ size: "sm" }),
  "shrink-0 text-muted-foreground hover:text-foreground focus:z-10 focus-visible:z-10 data-[state=checked]:bg-accent data-[state=checked]:text-accent-foreground data-[state=checked]:shadow-[inset_0_0_0_1px_var(--color-primary)]",
);

// A segmented control: a Radix radio group drawn as segments, so it follows the ARIA radio pattern (Tab lands on the
// chosen option; arrow keys move to the next one and choose it; Space chooses), and one option is always chosen.
export const Segmented = <T extends string>({ label, hideLabel = false, options, labels, value, onChange }: Props<T>) => {
  const labelId = useId();
  const group = (
    <RadioGroup.Root
      value={value}
      onValueChange={(next) => {
        const picked = options.find((option) => option === next);
        if (picked) onChange(picked);
      }}
      {...(hideLabel ? { "aria-label": label } : { "aria-labelledby": labelId })}
      // four options do not fit one row on a phone: two even rows rather than one ragged wrap
      className={cn(
        "flex w-fit flex-wrap items-center gap-0.5 rounded-[min(var(--radius-md),10px)] border border-input p-0.5",
        options.length > 3 && "max-sm:grid max-sm:grid-cols-2",
      )}
    >
      {options.map((option) => (
        <RadioGroup.Item key={option} value={option} className={ITEM}>
          {labels[option]}
        </RadioGroup.Item>
      ))}
    </RadioGroup.Root>
  );
  if (hideLabel) return group;
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <FieldTitle id={labelId}>{label}</FieldTitle>
      {group}
    </div>
  );
};
