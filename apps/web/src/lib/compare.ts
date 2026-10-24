import type { ResultStatus, RunDetail, RunMetrics } from "./types";

export interface MetricDelta {
  key: string;
  label: string;
  a?: number;
  b?: number;
  delta?: number;
  better?: "a" | "b" | "same";
  format: "pct" | "score" | "ms" | "usd" | "num";
}

export interface CaseRow {
  testCaseId: string;
  name: string;
  statusA?: ResultStatus;
  statusB?: ResultStatus;
  scoreA?: number;
  scoreB?: number;
  delta?: number;
  change: "improved" | "regressed" | "unchanged" | "missing";
}

const METRICS: Array<{ metric: keyof RunMetrics; label: string; format: MetricDelta["format"]; lowerIsBetter?: boolean }> = [
  { metric: "passRate", label: "Pass rate", format: "pct" },
  { metric: "avgScore", label: "Avg score", format: "score" },
  { metric: "passed", label: "Passed", format: "num" },
  { metric: "partial", label: "Partial", format: "num" },
  { metric: "failed", label: "Failed", format: "num", lowerIsBetter: true },
  { metric: "errored", label: "Errored", format: "num", lowerIsBetter: true },
  { metric: "avgLatencyMs", label: "Avg latency", format: "ms", lowerIsBetter: true },
  { metric: "p95LatencyMs", label: "p95 latency", format: "ms", lowerIsBetter: true },
  { metric: "totalCostUsd", label: "Total cost", format: "usd", lowerIsBetter: true },
  { metric: "tokenCount", label: "Tokens", format: "num", lowerIsBetter: true },
  { metric: "totalRetries", label: "Retries", format: "num", lowerIsBetter: true },
];

function judge(a: number | undefined, b: number | undefined, lowerIsBetter = false): MetricDelta["better"] {
  if (a === undefined || b === undefined) return undefined;
  const d = b - a;
  if (Math.abs(d) < 1e-9) return "same";
  if (lowerIsBetter) return d < 0 ? "b" : "a";
  return d > 0 ? "b" : "a";
}

export function compareRuns(a: RunDetail, b: RunDetail) {
  const ma = a.metrics ?? undefined;
  const mb = b.metrics ?? undefined;
  const metrics: MetricDelta[] = METRICS.map((m) => {
    const va = ma ? (ma[m.metric] as number) : undefined;
    const vb = mb ? (mb[m.metric] as number) : undefined;
    return {
      key: m.metric,
      label: m.label,
      a: va,
      b: vb,
      delta: va !== undefined && vb !== undefined ? vb - va : undefined,
      better: judge(va, vb, m.lowerIsBetter),
      format: m.format,
    };
  });

  const names = new Set([...Object.keys(ma?.scorerAverages ?? {}), ...Object.keys(mb?.scorerAverages ?? {})]);
  const scorers: MetricDelta[] = [...names].sort().map((n) => {
    const va = ma?.scorerAverages?.[n];
    const vb = mb?.scorerAverages?.[n];
    return {
      key: n,
      label: n,
      a: va,
      b: vb,
      delta: va !== undefined && vb !== undefined ? vb - va : undefined,
      better: judge(va, vb),
      format: "score",
    };
  });

  const byA = new Map(a.results.map((r) => [r.testCaseId, r]));
  const byB = new Map(b.results.map((r) => [r.testCaseId, r]));
  const ids = [...new Set([...byA.keys(), ...byB.keys()])];
  const cases: CaseRow[] = ids.map((id) => {
    const ra = byA.get(id);
    const rb = byB.get(id);
    const delta = ra && rb ? rb.score - ra.score : undefined;
    const change: CaseRow["change"] =
      delta === undefined ? "missing" : delta > 1e-9 ? "improved" : delta < -1e-9 ? "regressed" : "unchanged";
    return {
      testCaseId: id,
      name: ra?.testCaseName ?? rb?.testCaseName ?? id,
      statusA: ra?.status,
      statusB: rb?.status,
      scoreA: ra?.score,
      scoreB: rb?.score,
      delta,
      change,
    };
  });
  return { metrics, scorers, cases, sameDataset: a.datasetId === b.datasetId };
}
