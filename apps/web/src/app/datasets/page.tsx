import { Database } from "lucide-react";
import Link from "next/link";

import { DataSourceBanner } from "@/components/data-source-banner";
import { NewDatasetDialog } from "@/components/dataset-forms";
import { PageHeader } from "@/components/page-header";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { getDatasets } from "@/lib/api";
import { date } from "@/lib/format";

export const dynamic = "force-dynamic";
export const metadata = { title: "Datasets" };

export default async function DatasetsPage() {
  const { data: datasets, source, reason } = await getDatasets();
  return (
    <>
      <PageHeader
        title="Datasets"
        description="Collections of test cases: inputs, environment state, golden outputs and expected tool calls."
        actions={<NewDatasetDialog disabled={source === "demo"} />}
      />
      <DataSourceBanner source={source} reason={reason} />
      {datasets.length === 0 ? (
        <Card className="bg-slate-900/30">
          <CardContent className="py-12 text-center text-sm text-slate-400">
            No datasets yet. Create one, or load the sample with <code className="rounded bg-slate-900 px-1">agentval seed</code>.
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {datasets.map((d) => (
            <Link key={d.id} href={`/datasets/${d.id}`} className="group">
              <Card className="h-full bg-slate-900/30 transition-colors group-hover:border-slate-600">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <Database className="size-4 text-blue-400" /> {d.name}
                  </CardTitle>
                  <CardDescription className="line-clamp-2">{d.description || "No description"}</CardDescription>
                </CardHeader>
                <CardContent className="flex items-center justify-between text-xs text-slate-400">
                  <span>
                    <span className="font-semibold text-slate-200">{d.testCaseCount}</span> test cases ·{" "}
                    <span className="font-semibold text-slate-200">{d.runCount}</span> runs
                  </span>
                  <span>updated {date(d.updatedAt)}</span>
                </CardContent>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </>
  );
}
