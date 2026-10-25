"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

/** Polls the server component tree while a run is in progress (backend also offers SSE). */
export function AutoRefresh({ active, intervalMs = 1500 }: { active: boolean; intervalMs?: number }) {
  const router = useRouter();
  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => router.refresh(), intervalMs);
    return () => clearInterval(id);
  }, [active, intervalMs, router]);
  return null;
}
