// Focusing a text field opens the on-screen keyboard on a touch screen, over the result the user is waiting for, so
// there the user taps the field when ready to type. With a mouse or trackpad focus goes back to it. Returns whether it did.
export const focusForTyping = (field: HTMLElement | null) => {
  const fine = window.matchMedia("(pointer: fine)").matches;
  if (fine) field?.focus();
  return fine;
};
