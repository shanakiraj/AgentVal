import { cn } from "@/lib/utils";
import { json } from "@/lib/format";

export function JsonBlock({ value, className }: { value: unknown; className?: string }) {
  return (
    <pre
      className={cn(
        "max-h-80 overflow-auto rounded-md border border-slate-800 bg-slate-950 p-3 font-mono text-xs leading-relaxed text-slate-300",
        className,
      )}
    >
      {value === undefined || value === null ? "—" : json(value)}
    </pre>
  );
}
