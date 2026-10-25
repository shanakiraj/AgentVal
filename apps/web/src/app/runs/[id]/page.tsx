import { CheckCircle2, Coins, Gauge, RefreshCw, Timer, Zap } from "lucide-react";
import Link from "next/link";

import { AutoRefresh } from "@/components/auto-refresh";
import { DataSourceBanner } from "@/components/data-source-banner";
import { JsonBlock } from "@/components/json-block";
import { MetricCard } from "@/components/metric-card";
import { PageHeader } from "@/components/page-header";
import { ResultBadge, RunBadge } from "@/components/status-badge";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { getRun } from "@/lib/api";
import { date, ms, num, pct, score, usd } from "@/lib/format";
import { cn } from "@/lib/utils";

export const dynamic = "force-dynamic";

function scoreColor(v: number) {
  return v >= 0.85 ? "text-emerald-400" : v >= 0.4 ? "text-amber-300" : "text-red-400";
}

export default async function RunPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const { data: run, source, reason } = await getRun(id);
  const m = run.metrics;
  const active = run.status === "RUNNING" || run.status === "PENDING";
  const scorerNames = [...new Set(run.results.flatMap((r) => Object.keys(r.scores)))].sort();

  return (
    <>
      <AutoRefresh active={active} />
      <PageHeader
        breadcrumb={
          <>
            <Link href="/runs" className="hover:text-slate-300">
              Runs
            </Link>{" "}
            / {run.id.slice(0, 8)}
          </>
        }
        title={run.name}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <RunBadge status={run.status} />
            <span className="font-mono text-xs">{run.model}</span>·
            <Link href={`/datasets/${run.datasetId}`} className="hover:text-blue-400">
              {run.datasetName}
            </Link>
            · {date(run.createdAt)}
          </span>
        }
        actions={
          <Link href={`/compare?b=${run.id}`} className={buttonVariants({ variant: "outline" })}>
            Compare with…
          </Link>
        }
      />
      <DataSourceBanner source={source} reason={reason} />

      {active && (
        <Card className="bg-slate-900/30">
          <CardContent className="space-y-2">
            <div className="flex items-center justify-between text-sm">
              <span className="flex items-center gap-2 text-blue-300">
                <RefreshCw className="size-4 animate-spin" /> Evaluating… live updates every 1.5s
              </span>
              <span className="tabular-nums text-slate-400">
                {run.completedCases}/{run.totalCases} cases
              </span>
            </div>
            <Progress value={run.progress * 100} />
          </CardContent>
        </Card>
      )}
      {run.error && (
        <p className="rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">{run.error}</p>
      )}

      {m && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <MetricCard
            label="Pass rate"
            value={pct(m.passRate)}
            hint={`${m.passed} pass · ${m.partial} partial · ${m.failed} fail · ${m.errored} error`}
            icon={CheckCircle2}
            tone={m.passRate >= 0.8 ? "good" : m.passRate >= 0.5 ? "warn" : "bad"}
          />
          <MetricCard label="Avg score" value={score(m.avgScore)} hint="weighted across scorers" icon={Gauge} />
          <MetricCard label="Avg latency" value={ms(m.avgLatencyMs)} hint={`p50 ${ms(m.p50LatencyMs)} · p95 ${ms(m.p95LatencyMs)}`} icon={Timer} />
          <MetricCard label="Total cost" value={usd(m.totalCostUsd)} hint={`${num(m.tokenCount)} tokens`} icon={Coins} />
          <MetricCard label="Retries" value={num(m.totalRetries)} hint={`wall time ${ms(m.durationMs ?? undefined)}`} icon={Zap} />
        </div>
      )}

      {m && Object.keys(m.scorerAverages).length > 0 && (
        <Card className="bg-slate-900/30">
          <CardHeader>
            <CardTitle>Scorer breakdown</CardTitle>
            <CardDescription>Mean score per scorer (skipped scorers excluded).</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {Object.entries(m.scorerAverages).map(([name, v]) => (
              <div key={name} className="space-y-1.5 rounded-lg border border-slate-800 p-3">
                <div className="flex items-center justify-between">
                  <span className="font-mono text-xs text-slate-300">{name}</span>
                  <span className={cn("text-sm font-semibold tabular-nums", scoreColor(v))}>{score(v)}</span>
                </div>
                <div className="h-1.5 overflow-hidden rounded-full bg-slate-800">
                  <div className="h-full rounded-full bg-blue-500" style={{ width: `${v * 100}%` }} />
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      <Card className="bg-slate-900/30">
        <CardHeader>
          <CardTitle>Test case results</CardTitle>
          <CardDescription>Open a trace to see the agent&apos;s step-by-step trajectory.</CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow className="border-slate-800">
                <TableHead>Test case</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Score</TableHead>
                {scorerNames.map((s) => (
                  <TableHead key={s} className="text-right font-mono text-[11px]">
                    {s}
                  </TableHead>
                ))}
                <TableHead className="text-right">Latency</TableHead>
                <TableHead className="text-right">Cost</TableHead>
                <TableHead className="text-right">Tries</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {run.results.map((r) => (
                <TableRow key={r.id} className="border-slate-800 align-top">
                  <TableCell className="max-w-64">
                    <div className="truncate font-medium">{r.testCaseName ?? r.testCaseId.slice(0, 8)}</div>
                    <div className="truncate text-xs text-slate-500">
                      {String((r.input as { prompt?: string } | null)?.prompt ?? "")}
                    </div>
                  </TableCell>
                  <TableCell>
                    <ResultBadge status={r.status} />
                  </TableCell>
                  <TableCell className={cn("text-right font-semibold tabular-nums", scoreColor(r.score))}>
                    {score(r.score)}
                  </TableCell>
                  {scorerNames.map((s) => {
                    const e = r.scores[s];
                    return (
                      <TableCell key={s} className="text-right tabular-nums" title={e?.rationale}>
                        {!e ? "—" : e.skipped ? <span className="text-slate-600">skip</span> : (
                          <span className={scoreColor(e.score)}>{e.score.toFixed(2)}</span>
                        )}
                      </TableCell>
                    );
                  })}
                  <TableCell className="text-right tabular-nums">{ms(r.latencyMs)}</TableCell>
                  <TableCell className="text-right tabular-nums">{usd(r.costUsd)}</TableCell>
                  <TableCell className="text-right tabular-nums">{r.attempts}</TableCell>
                  <TableCell className="text-right">
                    <Link href={`/runs/${run.id}/trace/${r.id}`} className={buttonVariants({ variant: "outline", size: "sm" })}>
                      Trace
                    </Link>
                  </TableCell>
                </TableRow>
              ))}
              {run.results.length === 0 && (
                <TableRow>
                  <TableCell colSpan={7 + scorerNames.length} className="py-8 text-center text-slate-500">
                    {active ? "Waiting for the first result…" : "No results."}
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <details className="rounded-xl border border-slate-800 bg-slate-900/30 p-4 text-sm">
        <summary className="cursor-pointer text-slate-300">Run configuration</summary>
        <JsonBlock value={run.config} className="mt-3" />
      </details>
    </>
  );
}
