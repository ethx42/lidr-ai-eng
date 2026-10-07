import { useState } from "react";

// `what` completes "Replace your draft with …?", e.g. `the “Clinic portal” sample`.
export type Replacement = { text: string; what: string };

// The composer's text. Typed or pasted text is never overwritten silently: replacing a different,
// non-empty draft waits for `confirm()`.
export const useDraft = () => {
  const [value, setValue] = useState("");
  const [pending, setPending] = useState<Replacement | null>(null);

  // true when the text was applied right away, false when it waits for confirmation
  const replace = (next: Replacement) => {
    const free = value.trim() === "" || value === next.text;
    setPending(free ? null : next);
    if (free) setValue(next.text);
    return free;
  };
  const confirm = () => {
    if (pending) setValue(pending.text);
    setPending(null);
  };
  const cancel = () => setPending(null);
  const clear = () => {
    setValue("");
    setPending(null);
  };

  return { value, setValue, pending, replace, confirm, cancel, clear };
};

export type Draft = ReturnType<typeof useDraft>;
