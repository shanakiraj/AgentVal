"use client";

import { Activity, Database, FlaskConical, GitCompareArrows, ExternalLink } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

const LINKS = [
  { href: "/runs", label: "Runs", icon: Activity },
  { href: "/datasets", label: "Datasets", icon: Database },
  { href: "/compare", label: "Compare", icon: GitCompareArrows },
];

export function Sidebar() {
  const pathname = usePathname();
  return (
    <aside className="flex w-full shrink-0 flex-col border-b border-slate-800 bg-slate-950/80 md:h-screen md:w-56 md:border-r md:border-b-0 md:sticky md:top-0">
      <Link href="/runs" className="flex items-center gap-2 px-5 py-4 font-semibold tracking-tight">
        <span className="flex size-7 items-center justify-center rounded-md bg-blue-500/15 text-blue-400 ring-1 ring-blue-500/30">
          <FlaskConical className="size-4" />
        </span>
        AgentVal
      </Link>
      <nav className="flex gap-1 px-3 pb-3 md:flex-col md:pb-0">
        {LINKS.map(({ href, label, icon: Icon }) => {
          const active = pathname === href || pathname.startsWith(`${href}/`);
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "flex items-center gap-2 rounded-md px-3 py-2 text-sm text-slate-400 transition-colors hover:bg-slate-900 hover:text-slate-100",
                active && "bg-slate-900 text-slate-50 ring-1 ring-slate-800",
              )}
            >
              <Icon className="size-4" />
              {label}
            </Link>
          );
        })}
      </nav>
      <div className="mt-auto hidden px-5 py-4 text-xs text-slate-500 md:block">
        <a
          href="https://github.com/shanakiraj/AgentVal"
          target="_blank"
          rel="noreferrer"
          className="flex items-center gap-1.5 hover:text-slate-300"
        >
          <ExternalLink className="size-3.5" /> Open source
        </a>
      </div>
    </aside>
  );
}
