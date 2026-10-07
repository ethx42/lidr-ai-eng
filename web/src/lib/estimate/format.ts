const number = new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 });
const integer = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const dollars = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
// Sub-dollar amounts (LLM call costs) keep their significant digits.
const cents = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 4 });

const PROVIDERS: Record<string, string> = { openai: "OpenAI", anthropic: "Anthropic", replay: "Replay" };

export const formatHours = (hours: number) => `${number.format(hours)} h`;

// `unit` is plural ("weeks"); a range that collapses to exactly 1 drops its trailing "s".
export const formatRange = (lo: number, hi: number, unit = "h") => {
  const [from, to] = [number.format(lo), number.format(hi)];
  if (from !== to) return `${from}–${to} ${unit}`;
  return `${from} ${from === "1" ? unit.replace(/s$/, "") : unit}`;
};

export const formatMs = (ms: number) => `${integer.format(ms)} ms`;

export const formatUsd = (usd: number) => (Math.abs(usd) < 1 ? cents : dollars).format(usd);

export const formatProvider = (provider: string) => PROVIDERS[provider] ?? provider.charAt(0).toUpperCase() + provider.slice(1);
