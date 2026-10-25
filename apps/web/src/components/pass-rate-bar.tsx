import { cn } from "@/lib/utils";

export function PassRateBar({ value, className }: { value?: number | null; className?: string }) {
  const v = Math.max(0, Math.min(1, value ?? 0));
  const color = v >= 0.8 ? "bg-emerald-500" : v >= 0.5 ? "bg-amber-400" : "bg-red-500";
  return (
    <div className={cn("flex items-center gap-2", className)}>
      <div className="h-1.5 w-20 overflow-hidden rounded-full bg-slate-800">
        <div className={cn("h-full rounded-full", color)} style={{ width: `${v * 100}%` }} />
      </div>
      <span className="w-10 text-right text-xs tabular-nums text-slate-300">
        {value === null || value === undefined ? "—" : `${Math.round(v * 100)}%`}
      </span>
    </div>
  );
}
