import { Info } from "lucide-react";

import type { DataSource } from "@/lib/types";

export function DataSourceBanner({ source, reason }: { source: DataSource; reason?: string }) {
  if (source === "live") return null;
  return (
    <div className="flex items-start gap-2 rounded-lg border border-blue-500/30 bg-blue-500/5 px-3 py-2 text-xs text-blue-200">
      <Info className="mt-0.5 size-3.5 shrink-0" />
      <div>
        <span className="font-medium">Demo data.</span> Showing the bundled sample dataset and runs (read-only).{" "}
        {reason && <span className="text-blue-300/70">{reason}</span>} Run the FastAPI backend and set{" "}
        <code className="rounded bg-slate-900 px-1">NEXT_PUBLIC_API_URL</code> to evaluate your own agents.
      </div>
    </div>
  );
}
