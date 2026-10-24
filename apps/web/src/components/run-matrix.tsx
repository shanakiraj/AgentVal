import Link from "next/link";

import { ResultBadge } from "@/components/status-badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ms, num, pct, score, usd } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { RunDetail } from "@/lib/types";

function shortModel(model?: string | null) {
  if (!model) return "—";
  return model.replace(/^openrouter\//, "");
}

function heat(v: number | undefined) {
  if (v === undefined) return "text-slate-600";
  return v >= 0.85 ? "text-emerald-400" : v >= 0.4 ? "text-amber-300" : "text-red-400";
}

/** Leaderboard + per-test-case matrix across any number of runs on the same dataset. */
export function RunMatrix({ runs, pairHref }: { runs: RunDetail[]; pairHref: (aId: string, bId: string) => string }) {
  const ranked = [...runs].sort(
    (x, y) => (y.metrics?.avgScore ?? -1) - (x.metrics?.avgScore ?? -1) || (y.metrics?.passRate ?? 0) - (x.metrics?.passRate ?? 0),
  );
  const best = ranked[0];
  const scorerNames = [...new Set(ranked.flatMap((r) => Object.keys(r.metrics?.scorerAverages ?? {})))].sort();
  const cases: Array<{ id: string; name: string }> = [];
  for (const r of ranked)
    for (const res of r.results)
      if (!cases.some((c) => c.id === res.testCaseId)) cases.push({ id: res.testCaseId, name: res.testCaseName ?? res.testCaseId });

  return (
    <>
      <Card className="bg-slate-900/30">
        <CardHeader>
          <CardTitle>Leaderboard ({ranked.length} runs)</CardTitle>
          <CardDescription>Ranked by average score. Δ columns are relative to the leader.</CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow className="border-slate-800">
                <TableHead className="w-8">#</TableHead>
                <TableHead>Run / model</TableHead>
                <TableHead className="text-right">Pass rate</TableHead>
                <TableHead className="text-right">Avg score</TableHead>
                <TableHead className="text-right">Δ score</TableHead>
                {scorerNames.map((s) => (
                  <TableHead key={s} className="text-right font-mono text-[11px]">
                    {s}
                  </TableHead>
                ))}
                <TableHead className="text-right">Avg latency</TableHead>
                <TableHead className="text-right">Tokens</TableHead>
                <TableHead className="text-right">Cost</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {ranked.map((r, i) => {
                const m = r.metrics;
                const d = m && best?.metrics ? m.avgScore - best.metrics.avgScore : undefined;
                return (
                  <TableRow key={r.id} className={cn("border-slate-800", i === 0 && "bg-emerald-500/5")}>
                    <TableCell className="text-slate-500 tabular-nums">{i + 1}</TableCell>
                    <TableCell className="max-w-72">
                      <Link href={`/runs/${r.id}`} className="block truncate font-medium hover:text-blue-400">
                        {r.name}
                      </Link>
                      <span className="font-mono text-[11px] text-slate-500">{shortModel(r.model)}</span>
                    </TableCell>
                    <TableCell className={cn("text-right tabular-nums", heat(m?.passRate))}>{pct(m?.passRate)}</TableCell>
                    <TableCell className={cn("text-right font-semibold tabular-nums", heat(m?.avgScore))}>{score(m?.avgScore)}</TableCell>
                    <TableCell className="text-right text-xs tabular-nums text-slate-400">
                      {d === undefined || i === 0 ? "—" : d.toFixed(3)}
                    </TableCell>
                    {scorerNames.map((s) => {
                      const v = m?.scorerAverages?.[s];
                      return (
                        <TableCell key={s} className={cn("text-right tabular-nums", heat(v))}>
                          {v === undefined ? "—" : v.toFixed(2)}
                        </TableCell>
                      );
                    })}
                    <TableCell className="text-right tabular-nums">{ms(m?.avgLatencyMs)}</TableCell>
                    <TableCell className="text-right tabular-nums">{num(m?.tokenCount)}</TableCell>
                    <TableCell className="text-right tabular-nums">{usd(m?.totalCostUsd)}</TableCell>
                    <TableCell className="text-right">
                      {i > 0 && best && (
                        <Link href={pairHref(r.id, best.id)} className="text-xs whitespace-nowrap text-blue-400 hover:underline">
                          vs leader
                        </Link>
                      )}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Card className="bg-slate-900/30">
        <CardHeader>
          <CardTitle>Per test case × run</CardTitle>
          <CardDescription>Status and weighted score for every case in every selected run. Click a cell for its trace.</CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow className="border-slate-800">
                <TableHead>Test case</TableHead>
                {ranked.map((r) => (
                  <TableHead key={r.id} className="max-w-36 text-center">
                    <span className="block truncate font-mono text-[11px]" title={r.name}>
                      {shortModel(r.model)}
                    </span>
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {cases.map((c) => (
                <TableRow key={c.id} className="border-slate-800">
                  <TableCell className="font-medium whitespace-nowrap">{c.name}</TableCell>
                  {ranked.map((r) => {
                    const res = r.results.find((x) => x.testCaseId === c.id);
                    return (
                      <TableCell key={r.id} className="text-center">
                        {res ? (
                          <Link
                            href={`/runs/${r.id}/trace/${res.id}`}
                            className="inline-flex flex-col items-center gap-0.5 rounded-md px-1 py-0.5 hover:bg-slate-800"
                          >
                            <ResultBadge status={res.status} />
                            <span className={cn("text-[11px] tabular-nums", heat(res.score))}>{res.score.toFixed(2)}</span>
                          </Link>
                        ) : (
                          <span className="text-slate-600">—</span>
                        )}
                      </TableCell>
                    );
                  })}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </>
  );
}
