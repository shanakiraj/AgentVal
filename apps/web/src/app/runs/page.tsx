import { Activity, Coins, Gauge, GitCompareArrows, Timer } from "lucide-react";
import Link from "next/link";

import { DataSourceBanner } from "@/components/data-source-banner";
import { MetricCard } from "@/components/metric-card";
import { PageHeader } from "@/components/page-header";
import { PassRateBar } from "@/components/pass-rate-bar";
import { RunBadge } from "@/components/status-badge";
import { AutoRefresh } from "@/components/auto-refresh";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { getRuns } from "@/lib/api";
import { date, ms, num, pct, score, usd } from "@/lib/format";
import type { Run } from "@/lib/types";

export const dynamic = "force-dynamic";
export const metadata = { title: "Runs" };

function byModel(runs: Run[]) {
  const groups = new Map<string, { runs: number; passRate: number; latency: number; cost: number }>();
  for (const r of runs) {
    if (!r.metrics) continue;
    const key = r.model ?? "unknown";
    const g = groups.get(key) ?? { runs: 0, passRate: 0, latency: 0, cost: 0 };
    g.runs += 1;
    g.passRate += r.metrics.passRate;
    g.latency += r.metrics.avgLatencyMs;
    g.cost += r.metrics.totalCostUsd;
    groups.set(key, g);
  }
  return [...groups.entries()]
    .map(([model, g]) => ({ model, runs: g.runs, passRate: g.passRate / g.runs, latency: g.latency / g.runs, cost: g.cost / g.runs }))
    .sort((a, b) => b.passRate - a.passRate);
}

export default async function RunsPage() {
  const { data: runs, source, reason } = await getRuns();
  const done = runs.filter((r) => r.metrics);
  const best = done.reduce<Run | undefined>((b, r) => (!b || r.metrics!.passRate > b.metrics!.passRate ? r : b), undefined);
  const avgLatency = done.length ? done.reduce((s, r) => s + r.metrics!.avgLatencyMs, 0) / done.length : undefined;
  const totalCost = done.reduce((s, r) => s + r.metrics!.totalCostUsd, 0);
  const models = byModel(runs);
  const inFlight = runs.some((r) => r.status === "RUNNING" || r.status === "PENDING");

  return (
    <>
      <AutoRefresh active={inFlight} />
      <PageHeader
        title="Evaluation runs"
        description="Every evaluation run with pass rates, latency, cost and model comparisons."
        actions={
          runs.length >= 2 && (
            <Link href={`/compare?a=${runs[1].id}&b=${runs[0].id}`} className={buttonVariants({ variant: "outline" })}>
              <GitCompareArrows className="size-4" /> Compare latest two
            </Link>
          )
        }
      />
      <DataSourceBanner source={source} reason={reason} />

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <MetricCard label="Runs" value={num(runs.length)} hint={`${done.length} completed`} icon={Activity} />
        <MetricCard
          label="Best pass rate"
          value={pct(best?.metrics?.passRate)}
          hint={best ? best.name : "—"}
          icon={Gauge}
          tone={best && best.metrics!.passRate >= 0.8 ? "good" : "warn"}
        />
        <MetricCard label="Avg latency / case" value={ms(avgLatency)} hint="mean across runs" icon={Timer} />
        <MetricCard label="Total cost" value={usd(totalCost)} hint="all runs" icon={Coins} />
      </div>

      <Card className="bg-slate-900/30">
        <CardHeader>
          <CardTitle>All runs</CardTitle>
          <CardDescription>Newest first. Click a run for per-test-case results and traces.</CardDescription>
        </CardHeader>
        <CardContent>
          {runs.length === 0 ? (
            <p className="py-8 text-center text-sm text-slate-400">
              No runs yet. Open a <Link href="/datasets" className="text-blue-400 hover:underline">dataset</Link> and start an
              evaluation, or run <code className="rounded bg-slate-900 px-1">agentval run --dataset sample</code>.
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow className="border-slate-800">
                  <TableHead>Run</TableHead>
                  <TableHead>Model</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Pass rate</TableHead>
                  <TableHead className="text-right">Avg score</TableHead>
                  <TableHead className="text-right">Avg latency</TableHead>
                  <TableHead className="text-right">Cost</TableHead>
                  <TableHead className="text-right">Tokens</TableHead>
                  <TableHead className="text-right">Created</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {runs.map((r) => (
                  <TableRow key={r.id} className="border-slate-800">
                    <TableCell className="max-w-72">
                      <Link href={`/runs/${r.id}`} className="block truncate font-medium hover:text-blue-400">
                        {r.name}
                      </Link>
                      <span className="text-xs text-slate-500">{r.datasetName}</span>
                    </TableCell>
                    <TableCell className="font-mono text-xs text-slate-300">{r.model}</TableCell>
                    <TableCell>
                      <RunBadge status={r.status} />
                      {r.status === "RUNNING" && (
                        <span className="ml-2 text-xs text-slate-500">
                          {r.completedCases}/{r.totalCases}
                        </span>
                      )}
                    </TableCell>
                    <TableCell>
                      <PassRateBar value={r.metrics?.passRate} />
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{score(r.metrics?.avgScore)}</TableCell>
                    <TableCell className="text-right tabular-nums">{ms(r.metrics?.avgLatencyMs)}</TableCell>
                    <TableCell className="text-right tabular-nums">{usd(r.metrics?.totalCostUsd)}</TableCell>
                    <TableCell className="text-right tabular-nums">{num(r.metrics?.tokenCount)}</TableCell>
                    <TableCell className="text-right text-xs text-slate-400">{date(r.createdAt)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {models.length > 0 && (
        <Card className="bg-slate-900/30">
          <CardHeader>
            <CardTitle>Model comparison</CardTitle>
            <CardDescription>Average across completed runs, grouped by model.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {models.map((m) => (
              <div key={m.model} className="grid grid-cols-[minmax(0,200px)_1fr_auto] items-center gap-4 text-sm">
                <span className="truncate font-mono text-xs text-slate-300">{m.model}</span>
                <div className="h-2 overflow-hidden rounded-full bg-slate-800">
                  <div
                    className={m.passRate >= 0.8 ? "h-full bg-emerald-500" : m.passRate >= 0.5 ? "h-full bg-amber-400" : "h-full bg-red-500"}
                    style={{ width: `${m.passRate * 100}%` }}
                  />
                </div>
                <span className="text-xs whitespace-nowrap text-slate-400 tabular-nums">
                  {pct(m.passRate)} · {ms(m.latency)} · {usd(m.cost)} · {m.runs} run{m.runs > 1 ? "s" : ""}
                </span>
              </div>
            ))}
          </CardContent>
        </Card>
      )}
    </>
  );
}
