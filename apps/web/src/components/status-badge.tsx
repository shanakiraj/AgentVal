import { AlertTriangle, CheckCircle2, CircleDashed, Loader2, MinusCircle, XCircle } from "lucide-react";

import { cn } from "@/lib/utils";
import type { ResultStatus, RunStatus } from "@/lib/types";

const RESULT: Record<ResultStatus, { cls: string; label: string; Icon: typeof CheckCircle2 }> = {
  PASS: { cls: "bg-emerald-500/10 text-emerald-400 ring-emerald-500/30", label: "Pass", Icon: CheckCircle2 },
  PARTIAL: { cls: "bg-amber-500/10 text-amber-300 ring-amber-500/30", label: "Partial", Icon: MinusCircle },
  FAIL: { cls: "bg-red-500/10 text-red-400 ring-red-500/30", label: "Fail", Icon: XCircle },
  ERROR: { cls: "bg-fuchsia-500/10 text-fuchsia-300 ring-fuchsia-500/30", label: "Error", Icon: AlertTriangle },
};

const RUN: Record<RunStatus, { cls: string; Icon: typeof CheckCircle2; spin?: boolean }> = {
  COMPLETED: { cls: "bg-emerald-500/10 text-emerald-400 ring-emerald-500/30", Icon: CheckCircle2 },
  RUNNING: { cls: "bg-blue-500/10 text-blue-300 ring-blue-500/30", Icon: Loader2, spin: true },
  PENDING: { cls: "bg-slate-500/10 text-slate-300 ring-slate-500/30", Icon: CircleDashed },
  FAILED: { cls: "bg-red-500/10 text-red-400 ring-red-500/30", Icon: XCircle },
};

const base = "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset whitespace-nowrap";

export function ResultBadge({ status, className }: { status?: ResultStatus | null; className?: string }) {
  if (!status) return <span className="text-xs text-slate-500">—</span>;
  const s = RESULT[status];
  return (
    <span className={cn(base, s.cls, className)}>
      <s.Icon className="size-3" />
      {s.label}
    </span>
  );
}

export function RunBadge({ status, className }: { status: RunStatus; className?: string }) {
  const s = RUN[status] ?? RUN.PENDING;
  return (
    <span className={cn(base, s.cls, className)}>
      <s.Icon className={cn("size-3", s.spin && "animate-spin")} />
      {status.charAt(0) + status.slice(1).toLowerCase()}
    </span>
  );
}
