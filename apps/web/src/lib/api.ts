/**
 * Server-side data access for the FastAPI backend with a graceful demo fallback.
 *
 * Base URL resolution (first non-empty wins):
 *   API_URL              runtime, server-only (e.g. http://api:8000 inside docker-compose)
 *   NEXT_PUBLIC_API_URL  public URL of the API (set in Vercel project settings)
 *
 * If no URL is configured, NEXT_PUBLIC_DEMO_MODE=true, or the API is unreachable,
 * reads fall back to the bundled demo dataset/runs and writes are disabled.
 */
import { notFound } from "next/navigation";

import { demo } from "./demo";
import type { Dataset, DatasetDetail, EvalResult, Fetched, Run, RunDetail } from "./types";

const TIMEOUT_MS = Number(process.env.API_TIMEOUT_MS ?? 4000);

export function apiBase(): string {
  return (process.env.API_URL || process.env.NEXT_PUBLIC_API_URL || "").trim().replace(/\/+$/, "");
}

export function demoForced(): boolean {
  return ["1", "true", "yes"].includes((process.env.NEXT_PUBLIC_DEMO_MODE ?? "").toLowerCase());
}

export class ApiError extends Error {
  constructor(
    message: string,
    public status?: number,
  ) {
    super(message);
  }
}

type LiveResult<T> = { ok: true; data: T } | { ok: false; status?: number; reason: string };

async function live<T>(path: string): Promise<LiveResult<T>> {
  const base = apiBase();
  if (demoForced()) return { ok: false, reason: "Demo mode is enabled (NEXT_PUBLIC_DEMO_MODE)." };
  if (!base) return { ok: false, reason: "No API URL configured (set NEXT_PUBLIC_API_URL)." };
  try {
    const res = await fetch(`${base}${path}`, { cache: "no-store", signal: AbortSignal.timeout(TIMEOUT_MS) });
    if (!res.ok) return { ok: false, status: res.status, reason: `API responded ${res.status}` };
    return { ok: true, data: (await res.json()) as T };
  } catch (err) {
    return { ok: false, reason: `API unreachable at ${base} (${(err as Error).name}).` };
  }
}

async function read<T>(path: string, fallback: () => T | undefined): Promise<Fetched<T>> {
  const res = await live<T>(path);
  if (res.ok) return { data: res.data, source: "live" };
  if (res.status === 404) notFound();
  const data = fallback();
  if (data === undefined) notFound();
  return { data, source: "demo", reason: res.reason };
}

export const getDatasets = () => read<Dataset[]>("/api/v1/datasets", () => demo.listDatasets());
export const getDataset = (id: string) =>
  read<DatasetDetail>(`/api/v1/datasets/${encodeURIComponent(id)}`, () => demo.getDataset(id));
export const getRuns = (datasetId?: string) =>
  read<Run[]>(`/api/v1/evals/runs${datasetId ? `?datasetId=${encodeURIComponent(datasetId)}` : ""}`, () =>
    demo.listRuns(datasetId),
  );
export const getRun = (id: string, includeTraces = false) =>
  read<RunDetail>(`/api/v1/evals/runs/${encodeURIComponent(id)}?includeTraces=${includeTraces}`, () =>
    demo.getRun(id),
  );
export const getResult = (runId: string, resultId: string) =>
  read<EvalResult>(
    `/api/v1/evals/runs/${encodeURIComponent(runId)}/results/${encodeURIComponent(resultId)}`,
    () => demo.getResult(runId, resultId),
  );

/** Write helper for server actions. Throws ApiError with a readable message. */
export async function apiWrite<T>(path: string, method: "POST" | "DELETE", body?: unknown): Promise<T | null> {
  const base = apiBase();
  if (demoForced() || !base) {
    throw new ApiError("Read-only demo mode: connect the AgentVal API (NEXT_PUBLIC_API_URL) to make changes.");
  }
  let res: Response;
  try {
    res = await fetch(`${base}${path}`, {
      method,
      headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      cache: "no-store",
      signal: AbortSignal.timeout(TIMEOUT_MS * 2),
    });
  } catch {
    throw new ApiError(`API unreachable at ${base}. Changes are disabled in demo mode.`);
  }
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const j = await res.json();
      detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
    } catch {
      /* ignore */
    }
    throw new ApiError(`API error: ${detail}`, res.status);
  }
  return res.status === 204 ? null : ((await res.json()) as T);
}
