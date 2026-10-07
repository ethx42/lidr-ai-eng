// Finds requirement quotes in the transcript the way the AI service grounds them (app/services/grounding.py `normalize`
// and `is_grounded`): NFKC, typographic quotes and dashes made plain, case folded, whitespace runs collapsed, and the
// quote's edge punctuation trimmed. Every quote the server calls grounded is found here, so it always gets a mark.

export type EvidenceQuote = { id: string; evidence: string };
export type EvidenceRange = { id: string; start: number; end: number };

const TYPOGRAPHY: Record<string, string> = {
  "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'",
  "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"', "\u00ab": '"', "\u00bb": '"',
  "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-", "\u2015": "-", "\u2212": "-",
};
// Python's `\s` on str, which differs from JavaScript's (U+001C-U+001F and U+0085 in, U+FEFF out).
const WHITESPACE = /[\t\n\v\f\r\x1c-\x20\x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]/;
const QUOTE_EDGES = /^[ "'.,;:!?\-()[\]]+|[ "'.,;:!?\-()[\]]+$/g;
// NFKC composes a base with its combining marks (and Hangul jamo), so each such cluster is normalised as a unit and
// whatever it becomes maps back to the cluster's place in the original text.
const CLUSTER = /[^\p{M}\u1160-\u11ff\ud7b0-\ud7ff][\p{M}\u1160-\u11ff\ud7b0-\ud7ff]*|[\p{M}\u1160-\u11ff\ud7b0-\ud7ff]+/gu;

// Python's casefold, per character: lower, upper, lower again also folds ß/ẞ to "ss" and ς to σ. Checked against
// casefold over every code point: characters that casefold alike always fold alike here.
const fold = (char: string) => (TYPOGRAPHY[char] ?? char).toLowerCase().toUpperCase().toLowerCase();

type Normalized = { text: string; starts: number[]; ends: number[] };

// The normalised text, with the original [start, end) of the cluster each of its UTF-16 units came from.
const normalize = (original: string): Normalized => {
  let text = "";
  const starts: number[] = [];
  const ends: number[] = [];
  for (const { 0: cluster, index } of original.matchAll(CLUSTER)) {
    for (const char of cluster.normalize("NFKC")) {
      const space = WHITESPACE.test(char);
      if (space && text.endsWith(" ")) continue;
      const out = space ? " " : fold(char);
      text += out;
      for (let i = 0; i < out.length; i++) {
        starts.push(index);
        ends.push(index + cluster.length);
      }
    }
  }
  return { text, starts, ends };
};

// Normalises the transcript once; the returned function finds quotes in it (streaming calls it on every snapshot).
// Each quote's first occurrence, in the order given; quotes not found (or empty once trimmed) are left out.
export const evidenceFinder = (transcript: string) => {
  const { text, starts, ends } = normalize(transcript);
  return (quotes: EvidenceQuote[]): EvidenceRange[] =>
    quotes.flatMap(({ id, evidence }) => {
      const quote = normalize(evidence).text.replace(QUOTE_EDGES, "");
      const at = quote ? text.indexOf(quote) : -1;
      return at < 0 ? [] : [{ id, start: starts[at], end: ends[at + quote.length - 1] }];
    });
};

export const findEvidenceRanges = (transcript: string, quotes: EvidenceQuote[]) => evidenceFinder(transcript)(quotes);
