import { useState } from "react";

// `what` completes "Replace your draft with …?", e.g. `the “Clinic portal” sample`.
export type Replacement = { text: string; what: string };

// Typed or pasted text is never overwritten silently: replacing a different, non-empty draft waits for `confirm()`.
// `read` and `write` reach the text where it lives (the form's transcript field).
export const useDraft = (read: () => string, write: (text: string) => void) => {
  const [pending, setPending] = useState<Replacement | null>(null);

  // true when the text was applied right away, false when it waits for confirmation
  const replace = (next: Replacement) => {
    const value = read();
    const free = value.trim() === "" || value === next.text;
    setPending(free ? null : next);
    if (free) write(next.text);
    return free;
  };
  const confirm = () => {
    if (pending) write(pending.text);
    setPending(null);
  };
  const cancel = () => setPending(null);

  return { pending, replace, confirm, cancel };
};
