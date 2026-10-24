import Link from "next/link";

import { DataSourceBanner } from "@/components/data-source-banner";
import { JsonBlock } from "@/components/json-block";
import { PageHeader } from "@/components/page-header";
import { ResultBadge } from "@/components/status-badge";
import { TraceGraph } from "@/components/trace-graph";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getResult } from "@/lib/api";
import { ms, num, score, usd } from "@/lib/format";
import { cn } from "@/lib/utils";

export const dynamic = "force-dynamic";
export const metadata = { title: "Trace" };

export default async function TracePage({ params }: { params: Promise<{ id: string; resultId: string }> }) {
  const { id, resultId } = await params;
  const { data: r, source, reason } = await getResult(id, resultId);
  const steps = r.trace?.steps ?? [];
  const toolCalls = steps.filter((s) => s.type === "tool_call");

  return (
    <>
      <PageHeader
        breadcrumb={
          <>
            <Link href="/runs" className="hover:text-slate-300">
              Runs
            </Link>{" "}
            /{" "}
            <Link href={`/runs/${id}`} className="hover:text-slate-300">
              {id.slice(0, 8)}
            </Link>{" "}
            / trace
          </>
        }
        title={r.testCaseName ?? "Trace"}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <ResultBadge status={r.status} /> score {score(r.score)} · {steps.length} steps · {toolCalls.length} tool calls ·{" "}
            {ms(r.latencyMs)} · {num(r.promptTokens + r.completionTokens)} tokens · {usd(r.costUsd)}
            {r.attempts > 1 && <span className="text-amber-300">· {r.attempts} attempts</span>}
          </span>
        }
      />
      <DataSourceBanner source={source} reason={reason} />
      {r.error && <p className="rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">{r.error}</p>}
      {r.trace?.retries?.length ? (
        <p className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
          Retried with exponential backoff after: {r.trace.retries.map((x) => `#${x.attempt} ${x.error}`).join("; ")}
        </p>
      ) : null}

      {steps.length ? <TraceGraph steps={steps} /> : <p className="text-sm text-slate-400">No trace steps recorded.</p>}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="bg-slate-900/30">
          <CardHeader>
            <CardTitle>Scores</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {Object.values(r.scores).map((s) => (
              <div key={s.name} className="rounded-lg border border-slate-800 p-3">
                <div className="flex items-center justify-between">
                  <span className="font-mono text-xs">
                    {s.name} <span className="text-slate-500">×{s.weight}</span>
                  </span>
                  <span
                    className={cn(
                      "text-sm font-semibold tabular-nums",
                      s.skipped ? "text-slate-500" : s.passed ? "text-emerald-400" : s.score >= 0.4 ? "text-amber-300" : "text-red-400",
                    )}
                  >
                    {s.skipped ? "skipped" : score(s.score)}
                  </span>
                </div>
                <p className="mt-1 text-xs text-slate-400">{s.rationale}</p>
              </div>
            ))}
            {Object.keys(r.scores).length === 0 && <p className="text-sm text-slate-500">Not scored.</p>}
          </CardContent>
        </Card>
        <Card className="bg-slate-900/30">
          <CardHeader>
            <CardTitle>Actual vs expected</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="space-y-1">
              <div className="text-xs text-slate-500">Actual output</div>
              <JsonBlock value={r.actual} />
            </div>
            <div className="space-y-1">
              <div className="text-xs text-slate-500">Expected</div>
              <JsonBlock value={r.expected} className="max-h-64" />
            </div>
          </CardContent>
        </Card>
      </div>
    </>
  );
}
