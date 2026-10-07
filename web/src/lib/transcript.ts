const integer = new Intl.NumberFormat("en-US");

// The AI service strips surrounding whitespace and counts code points (Python `len`), so the UI does too.
export const countChars = (text: string) => [...text.trim()].length;
export const formatCount = (n: number) => integer.format(n);
export const formatChars = (n: number) => `${formatCount(n)} ${n === 1 ? "character" : "characters"}`;
