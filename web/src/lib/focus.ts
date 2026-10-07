export const finePointer = () => window.matchMedia("(pointer: fine)").matches;

// Focusing a text field opens the on-screen keyboard on a touch screen, over the result the user is waiting for, so
// there the user taps the field when ready to type. With a mouse or trackpad focus goes back to it. Returns whether it did.
export const focusForTyping = (field: HTMLElement | null) => {
  const fine = finePointer();
  if (fine) field?.focus();
  return fine;
};

// Programmatic scrolls glide unless the user prefers reduced motion (spec §8).
export const scrollBehavior = (): ScrollBehavior => (window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth");
