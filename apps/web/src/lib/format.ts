export function pct(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${(v * 100).toFixed(digits)}%`;
}

export function ms(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  if (v >= 1000) return `${(v / 1000).toFixed(2)}s`;
  return `${Math.round(v)}ms`;
}

export function usd(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  if (v === 0) return "$0";
  if (v < 0.01) return `$${v.toFixed(6)}`;
  return `$${v.toFixed(4)}`;
}

export function num(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return new Intl.NumberFormat("en-US").format(v);
}

export function score(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return v.toFixed(3);
}

export function date(v: string | null | undefined): string {
  if (!v) return "—";
  const d = new Date(v.endsWith("Z") || /[+-]\d\d:\d\d$/.test(v) ? v : `${v}Z`);
  return d.toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short" });
}

export function json(v: unknown): string {
  if (typeof v === "string") return v;
  return JSON.stringify(v, null, 2);
}

export function truncate(s: string, n = 80): string {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}
