// Client-side redaction engine that mirrors the deterministic regex path
// used by Redax server-side. Used to power the live demo on the marketing
// site — runs entirely in the browser, never touches the network.

export type Span = { start: number; end: number; type: string };

type Rule = { name: string; pattern: RegExp };

const RULES: Rule[] = [
  { name: "CREDIT_CARD", pattern: /\b(?:\d[ -]*?){13,19}\b/g },
  { name: "EMAIL",       pattern: /\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b/g },
  { name: "URL",         pattern: /\bhttps?:\/\/[^\s<>"']+/g },
  { name: "IP",          pattern: /\b(?:\d{1,3}\.){3}\d{1,3}\b/g },
  { name: "IBAN",        pattern: /\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b/g },
  { name: "SSN",         pattern: /\b\d{3}-\d{2}-\d{4}\b/g },
  { name: "PHONE_E164",  pattern: /(?:\+?\d{1,3}[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b/g },
];

function luhn(digits: string): boolean {
  let sum = 0;
  let alt = false;
  for (let i = digits.length - 1; i >= 0; i--) {
    let n = Number(digits[i]);
    if (Number.isNaN(n)) return false;
    if (alt) {
      n *= 2;
      if (n > 9) n -= 9;
    }
    sum += n;
    alt = !alt;
  }
  return sum % 10 === 0;
}

function detect(text: string): Span[] {
  const spans: Span[] = [];
  for (const r of RULES) {
    r.pattern.lastIndex = 0;
    let m: RegExpExecArray | null;
    while ((m = r.pattern.exec(text)) !== null) {
      const start = m.index;
      const end = start + m[0].length;
      const raw = m[0];

      if (r.name === "CREDIT_CARD") {
        const digits = raw.replace(/\D/g, "");
        if (digits.length < 13 || digits.length > 19 || !luhn(digits)) continue;
      }
      if (r.name === "PHONE_E164") {
        const digits = raw.replace(/\D/g, "");
        if (digits.length < 10 || digits.length > 15) continue;
      }
      if (r.name === "IP") {
        const parts = raw.split(".").map((p) => Number(p));
        if (parts.some((p) => p < 0 || p > 255)) continue;
      }

      spans.push({ start, end, type: r.name });
    }
  }
  // Sort + dedupe by overlap; keep earliest start, then longest.
  spans.sort((a, b) => a.start - b.start || (b.end - b.start) - (a.end - a.start));
  const out: Span[] = [];
  let lastEnd = -1;
  for (const s of spans) {
    if (s.start >= lastEnd) {
      out.push(s);
      lastEnd = s.end;
    }
  }
  return out;
}

export function redact(text: string): { text: string; spans: Span[] } {
  const spans = detect(text);
  const counters: Record<string, number> = {};
  let out = "";
  let cursor = 0;
  for (const s of spans) {
    out += text.slice(cursor, s.start);
    counters[s.type] = (counters[s.type] ?? 0) + 1;
    const id = String(counters[s.type]).padStart(4, "0");
    out += `[${s.type}_${id}]`;
    cursor = s.end;
  }
  out += text.slice(cursor);
  return { text: out, spans };
}
