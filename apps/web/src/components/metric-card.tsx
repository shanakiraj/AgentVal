import type { LucideIcon } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export function MetricCard({
  label,
  value,
  hint,
  icon: Icon,
  tone = "default",
}: {
  label: string;
  value: React.ReactNode;
  hint?: React.ReactNode;
  icon?: LucideIcon;
  tone?: "default" | "good" | "warn" | "bad";
}) {
  const toneCls = {
    default: "text-slate-50",
    good: "text-emerald-400",
    warn: "text-amber-300",
    bad: "text-red-400",
  }[tone];
  return (
    <Card size="sm" className="bg-slate-900/40">
      <CardContent className="flex flex-col gap-1">
        <div className="flex items-center justify-between text-xs font-medium tracking-wide text-slate-400 uppercase">
          {label}
          {Icon && <Icon className="size-4 text-slate-500" />}
        </div>
        <div className={cn("text-2xl font-semibold tabular-nums", toneCls)}>{value}</div>
        {hint && <div className="text-xs text-slate-500">{hint}</div>}
      </CardContent>
    </Card>
  );
}
