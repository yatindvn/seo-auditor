export interface Segment { text: string; owner?: string }

/** Split an answer at the server's highlight ranges, for rendering as text inside <mark>, never as HTML. */
export function segments(text: string, highlights: { start: number; end: number; owner: string }[]): Segment[] {
  const out: Segment[] = [];
  let at = 0;
  for (const h of [...highlights].sort((a, b) => a.start - b.start)) {
    if (h.start < at || h.end > text.length || h.end <= h.start) continue;
    if (h.start > at) out.push({ text: text.slice(at, h.start) });
    out.push({ text: text.slice(h.start, h.end), owner: h.owner });
    at = h.end;
  }
  if (at < text.length) out.push({ text: text.slice(at) });
  return out;
}

export function ordinal(n: number): string {
  const rem100 = n % 100;
  if (rem100 >= 11 && rem100 <= 13) return `${n}th`;
  return `${n}${({ 1: "st", 2: "nd", 3: "rd" } as Record<number, string>)[n % 10] ?? "th"}`;
}

export const pct = (rate: number | null | undefined) => (rate == null ? "—" : `${Math.round(rate * 100)}%`);

/** Rough cost of one run: about $0.03 per prompt per model with web search. */
export const estimate = (prompts: number, providers: number) => `≈ $${(prompts * providers * 0.03).toFixed(2)}`;

export const safeUrl = (url: string) => /^https?:\/\//i.test(url) ? url : null;
