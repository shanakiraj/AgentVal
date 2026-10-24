import { ArrowDownRight, ArrowRight, ArrowUpRight, Minus } from "lucide-react";
import Link from "next/link";

import { DataSourceBanner } from "@/components/data-source-banner";
import { PageHeader } from "@/components/page-header";
import { RunMatrix } from "@/components/run-matrix";
import { ResultBadge, RunBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { getRun, getRuns } from "@/lib/api";
import { compareRuns, type MetricDelta } from "@/lib/compare";
import { ms, num, pct, score, usd } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { Run } from "@/lib/types";

export const dynamic = "force-dynamic";
export const metadata = { title: "Compare runs" };

const selectCls =
  "h-8 w-full rounded-lg border border-input bg-slate-950 px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50";

function fmt(v: number | undefined, f: MetricDelta["format"]) {
  if (v === undefined) return "—";
  return { pct: pct(v, 1), score: score(v), ms: ms(v), usd: usd(v), num: num(v) }[f];
}

function fmtDelta(d: number | undefined, f: MetricDelta["format"]) {
  if (d === undefined) return "—";
  const sign = d > 0 ? "+" : d < 0 ? "−" : "±";
  const a = Math.abs(d);
  const body = { pct: `${(a * 100).toFixed(1)} pp`, score: a.toFixed(3), ms: ms(a), usd: usd(a), num: num(a) }[f];
  return `${sign}${body}`;
}

function DeltaCell({ m }: { m: MetricDelta }) {
  const cls = m.better === "b" ? "text-emerald-400" : m.better === "a" ? "text-red-400" : "text-slate-500";
  const Icon = m.better === "same" || m.better === undefined ? Minus : (m.delta ?? 0) > 0 ? ArrowUpRight : ArrowDownRight;
  return (
    <span className={cn("inline-flex items-center justify-end gap-1 tabular-nums", cls)}>
      <Icon className="size-3.5" />
      {fmtDelta(m.delta, m.format)}
    </span>
  );
}

function RunPicker({ name, runs, value, label }: { name: string; runs: Run[]; value?: string; label: string }) {
  return (
    <label className="grid flex-1 gap-1 text-xs text-slate-400">
      {label}
      <select name={name} defaultValue={value} className={selectCls}>
        {runs.map((r) => (
          <option key={r.id} value={r.id}>
            {r.name} ({r.metrics ? pct(r.metrics.passRate) : r.status.toLowerCase()})
          </option>
        ))}
      </select>
    </label>
  );
}

function defaultPair(runs: Run[]): [string | undefined, string | undefined] {
  const done = runs.filter((r) => r.metrics);
  const real = done.filter((r) => !(r.model ?? "").startsWith("mock"));
  const pool = (real.length >= 2 ? real : done).slice().sort((x, y) => y.metrics!.avgScore - x.metrics!.avgScore);
  if (pool.length >= 2) return [pool[1].id, pool[0].id]; // A = runner-up, B = leader
  return [runs[1]?.id, runs[0]?.id];
}

type SP = { a?: string; b?: string; runs?: string | string[] };

export default async function ComparePage({ searchParams }: { searchParams: Promise<SP> }) {
  const sp = await searchParams;
  const { data: runs, source, reason } = await getRuns();
  const [defA, defB] = defaultPair(runs);
  const bId = sp.b ?? (sp.a ? runs.find((r) => r.id !== sp.a)?.id : defB);
  const aId = sp.a ?? (sp.b ? runs.find((r) => r.id !== bId)?.id : defA);
  const [a, b] = await Promise.all([aId ? getRun(aId) : null, bId ? getRun(bId) : null]);
  const cmp = a && b ? compareRuns(a.data, b.data) : null;

  // Multi-run matrix: explicit ?runs=… selection, else every completed run on the same dataset as B.
  const datasetId = b?.data.datasetId ?? runs[0]?.datasetId;
  const sameDataset = runs.filter((r) => r.datasetId === datasetId && r.status === "COMPLETED");
  const picked = sp.runs ? (Array.isArray(sp.runs) ? sp.runs : sp.runs.split(",")) : sameDataset.map((r) => r.id);
  const matrixRuns = (
    await Promise.all(sameDataset.filter((r) => picked.includes(r.id)).map((r) => getRun(r.id)))
  ).map((x) => x.data);
  const pairHref = (x: string, y: string) => `/compare?a=${x}&b=${y}#pair`;

  return (
    <>
      <PageHeader
        title="Compare runs"
        description="Leaderboard and per-case matrix across many runs, plus a detailed A/B diff of any two runs."
        actions={
          <div className="flex gap-3 text-sm">
            <a href="#matrix" className="text-blue-400 hover:underline">
              Multi-run
            </a>
            <a href="#pair" className="text-blue-400 hover:underline">
              A/B diff
            </a>
          </div>
        }
      />
      <DataSourceBanner source={source} reason={reason} />

      {sameDataset.length >= 2 && (
        <section id="matrix" className="scroll-mt-6 space-y-4">
          <Card className="bg-slate-900/30">
            <CardContent>
              <form className="space-y-3">
                <input type="hidden" name="a" value={aId} />
                <input type="hidden" name="b" value={bId} />
                <div className="text-xs text-slate-400">Runs in the matrix ({sameDataset[0]?.datasetName})</div>
                <div className="flex flex-wrap gap-2">
                  {sameDataset.map((r) => (
                    <label
                      key={r.id}
                      className="flex items-center gap-2 rounded-md border border-slate-800 px-2 py-1 text-xs hover:border-slate-600"
                    >
                      <input type="checkbox" name="runs" value={r.id} defaultChecked={picked.includes(r.id)} className="accent-blue-500" />
                      <span className="max-w-64 truncate">{r.name}</span>
                      <span className="text-slate-500">{r.metrics ? pct(r.metrics.passRate) : ""}</span>
                    </label>
                  ))}
                </div>
                <Button type="submit" variant="outline" size="sm">
                  Update matrix
                </Button>
              </form>
            </CardContent>
          </Card>
          {matrixRuns.length > 0 && <RunMatrix runs={matrixRuns} pairHref={pairHref} />}
        </section>
      )}

      <section id="pair" className="scroll-mt-6 space-y-4">
      <h2 className="pt-2 text-lg font-semibold tracking-tight">A/B diff</h2>
      <Card className="bg-slate-900/30">
        <CardContent>
          <form className="flex flex-col gap-3 md:flex-row md:items-end" action="/compare#pair">
            <RunPicker name="a" label="Run A (baseline)" runs={runs} value={aId} />
            <ArrowRight className="mb-2 hidden size-4 text-slate-500 md:block" />
            <RunPicker name="b" label="Run B (candidate)" runs={runs} value={bId} />
            <Button type="submit">Compare</Button>
          </form>
        </CardContent>
      </Card>

      {runs.length < 2 && <p className="text-sm text-slate-400">You need at least two runs to compare.</p>}

      {cmp && a && b && (
        <>
          <div className="grid gap-4 md:grid-cols-2">
            {[
              { label: "A", run: a.data },
              { label: "B", run: b.data },
            ].map(({ label, run }) => (
              <Card key={label} size="sm" className="bg-slate-900/30">
                <CardHeader>
                  <CardDescription>Run {label}</CardDescription>
                  <CardTitle className="flex items-center justify-between gap-2">
                    <Link href={`/runs/${run.id}`} className="truncate hover:text-blue-400">
                      {run.name}
                    </Link>
                    <RunBadge status={run.status} />
                  </CardTitle>
                </CardHeader>
                <CardContent className="text-xs text-slate-400">
                  <span className="font-mono">{run.model}</span> · {run.datasetName}
                </CardContent>
              </Card>
            ))}
          </div>
          {!cmp.sameDataset && (
            <p className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
              These runs use different datasets; per-case comparison is not meaningful.
            </p>
          )}

          <div className="grid gap-4 lg:grid-cols-2">
            <Card className="bg-slate-900/30">
              <CardHeader>
                <CardTitle>Metrics</CardTitle>
              </CardHeader>
              <CardContent>
                <Table>
                  <TableHeader>
                    <TableRow className="border-slate-800">
                      <TableHead>Metric</TableHead>
                      <TableHead className="text-right">Run A</TableHead>
                      <TableHead className="text-right">Run B</TableHead>
                      <TableHead className="text-right">Δ (B − A)</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {cmp.metrics.map((m) => (
                      <TableRow key={m.key} className="border-slate-800">
                        <TableCell>{m.label}</TableCell>
                        <TableCell className="text-right tabular-nums">{fmt(m.a, m.format)}</TableCell>
                        <TableCell className="text-right tabular-nums">{fmt(m.b, m.format)}</TableCell>
                        <TableCell className="text-right">
                          <DeltaCell m={m} />
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
            <Card className="bg-slate-900/30">
              <CardHeader>
                <CardTitle>Scorers</CardTitle>
                <CardDescription>Mean score per scorer.</CardDescription>
              </CardHeader>
              <CardContent>
                <Table>
                  <TableHeader>
                    <TableRow className="border-slate-800">
                      <TableHead>Scorer</TableHead>
                      <TableHead className="text-right">Run A</TableHead>
                      <TableHead className="text-right">Run B</TableHead>
                      <TableHead className="text-right">Δ</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {cmp.scorers.map((m) => (
                      <TableRow key={m.key} className="border-slate-800">
                        <TableCell className="font-mono text-xs">{m.label}</TableCell>
                        <TableCell className="text-right tabular-nums">{fmt(m.a, m.format)}</TableCell>
                        <TableCell className="text-right tabular-nums">{fmt(m.b, m.format)}</TableCell>
                        <TableCell className="text-right">
                          <DeltaCell m={m} />
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          </div>

          <Card className="bg-slate-900/30">
            <CardHeader>
              <CardTitle>Per test case</CardTitle>
              <CardDescription>
                {cmp.cases.filter((c) => c.change === "improved").length} improved ·{" "}
                {cmp.cases.filter((c) => c.change === "regressed").length} regressed ·{" "}
                {cmp.cases.filter((c) => c.change === "unchanged").length} unchanged
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow className="border-slate-800">
                    <TableHead>Test case</TableHead>
                    <TableHead>Run A</TableHead>
                    <TableHead>Run B</TableHead>
                    <TableHead className="text-right">Score A</TableHead>
                    <TableHead className="text-right">Score B</TableHead>
                    <TableHead className="text-right">Δ</TableHead>
                    <TableHead className="text-right">Change</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {cmp.cases.map((c) => (
                    <TableRow
                      key={c.testCaseId}
                      className={cn(
                        "border-slate-800",
                        c.change === "regressed" && "bg-red-500/5",
                        c.change === "improved" && "bg-emerald-500/5",
                      )}
                    >
                      <TableCell className="font-medium">{c.name}</TableCell>
                      <TableCell>
                        <ResultBadge status={c.statusA} />
                      </TableCell>
                      <TableCell>
                        <ResultBadge status={c.statusB} />
                      </TableCell>
                      <TableCell className="text-right tabular-nums">{score(c.scoreA)}</TableCell>
                      <TableCell className="text-right tabular-nums">{score(c.scoreB)}</TableCell>
                      <TableCell
                        className={cn(
                          "text-right tabular-nums",
                          c.change === "improved" ? "text-emerald-400" : c.change === "regressed" ? "text-red-400" : "text-slate-500",
                        )}
                      >
                        {c.delta === undefined ? "—" : `${c.delta > 0 ? "+" : ""}${c.delta.toFixed(3)}`}
                      </TableCell>
                      <TableCell className="text-right text-xs capitalize text-slate-400">{c.change}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </>
      )}
      </section>
    </>
  );
}
