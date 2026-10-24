import Link from "next/link";

import { DataSourceBanner } from "@/components/data-source-banner";
import { AddTestCaseDialog, DeleteButton, RunEvalDialog } from "@/components/dataset-forms";
import { JsonBlock } from "@/components/json-block";
import { PageHeader } from "@/components/page-header";
import { PassRateBar } from "@/components/pass-rate-bar";
import { RunBadge } from "@/components/status-badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { getDataset, getRuns } from "@/lib/api";
import { date, truncate } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function DatasetPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const [{ data: ds, source, reason }, { data: runs }] = await Promise.all([getDataset(id), getRuns(id)]);
  const readOnly = source === "demo";

  return (
    <>
      <PageHeader
        breadcrumb={
          <>
            <Link href="/datasets" className="hover:text-slate-300">
              Datasets
            </Link>{" "}
            / {ds.id.slice(0, 8)}
          </>
        }
        title={ds.name}
        description={ds.description}
        actions={
          <>
            <AddTestCaseDialog datasetId={ds.id} disabled={readOnly} />
            <RunEvalDialog datasetId={ds.id} disabled={readOnly || ds.testCases.length === 0} />
            <DeleteButton kind="dataset" datasetId={ds.id} disabled={readOnly} />
          </>
        }
      />
      <DataSourceBanner source={source} reason={reason} />

      <div className="grid gap-6 xl:grid-cols-[1fr_340px]">
        <Card className="bg-slate-900/30">
          <CardHeader>
            <CardTitle>Test cases ({ds.testCases.length})</CardTitle>
            <CardDescription>Expand a case to see its full input, expectations and metadata.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            {ds.testCases.length === 0 && <p className="py-6 text-center text-sm text-slate-500">No test cases yet.</p>}
            {ds.testCases.map((tc, i) => {
              const prompt = String((tc.input as { prompt?: string }).prompt ?? JSON.stringify(tc.input));
              const meta = tc.metadata ?? {};
              return (
                <details key={tc.id} className="group rounded-lg border border-slate-800 bg-slate-950/40">
                  <summary className="flex cursor-pointer list-none items-center gap-3 px-3 py-2.5">
                    <span className="w-6 text-xs text-slate-500 tabular-nums">{i + 1}</span>
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-medium">{tc.name ?? `Case ${i + 1}`}</div>
                      <div className="truncate text-xs text-slate-500">{truncate(prompt, 120)}</div>
                    </div>
                    <div className="hidden gap-1 sm:flex">
                      {Object.entries(meta)
                        .filter(([, v]) => typeof v === "string" && v.length < 24)
                        .slice(0, 2)
                        .map(([k, v]) => (
                          <span key={k} className="rounded-full border border-slate-800 px-2 py-0.5 text-[11px] text-slate-400">
                            {String(v)}
                          </span>
                        ))}
                    </div>
                    <DeleteButton kind="testcase" datasetId={ds.id} testCaseId={tc.id} disabled={readOnly} />
                  </summary>
                  <div className="grid gap-3 border-t border-slate-800 p-3 lg:grid-cols-2">
                    <div className="space-y-1">
                      <div className="text-xs text-slate-500">Input</div>
                      <JsonBlock value={tc.input} />
                    </div>
                    <div className="space-y-1">
                      <div className="text-xs text-slate-500">Expected</div>
                      <JsonBlock value={tc.expected} />
                      {tc.metadata && (
                        <>
                          <div className="pt-2 text-xs text-slate-500">Metadata</div>
                          <JsonBlock value={tc.metadata} />
                        </>
                      )}
                    </div>
                  </div>
                </details>
              );
            })}
          </CardContent>
        </Card>

        <Card className="h-fit bg-slate-900/30">
          <CardHeader>
            <CardTitle>Runs on this dataset</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {runs.length === 0 && <p className="text-sm text-slate-500">No runs yet.</p>}
            {runs.map((r) => (
              <Link
                key={r.id}
                href={`/runs/${r.id}`}
                className="block space-y-1.5 rounded-lg border border-slate-800 p-3 hover:border-slate-600"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate text-sm font-medium">{r.name}</span>
                  <RunBadge status={r.status} />
                </div>
                <div className="flex items-center justify-between text-xs text-slate-500">
                  <PassRateBar value={r.metrics?.passRate} />
                  {date(r.createdAt)}
                </div>
              </Link>
            ))}
          </CardContent>
        </Card>
      </div>
    </>
  );
}
