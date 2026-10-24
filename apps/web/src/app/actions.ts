"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { apiWrite } from "@/lib/api";
import type { DatasetDetail, Run, TestCase } from "@/lib/types";

export interface ActionState {
  error?: string;
  ok?: boolean;
}

function parseJson(label: string, value: FormDataEntryValue | null, required = false): unknown {
  const text = typeof value === "string" ? value.trim() : "";
  if (!text) {
    if (required) throw new Error(`${label} is required`);
    return undefined;
  }
  try {
    return JSON.parse(text);
  } catch {
    throw new Error(`${label} must be valid JSON`);
  }
}

function message(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export async function createDatasetAction(_: ActionState, form: FormData): Promise<ActionState> {
  let created: DatasetDetail | null;
  try {
    const imported = parseJson("Dataset JSON", form.get("json")) as Record<string, unknown> | unknown[] | undefined;
    const name = String(form.get("name") ?? "").trim();
    const description = String(form.get("description") ?? "").trim() || undefined;
    let body: Record<string, unknown>;
    if (Array.isArray(imported)) body = { name, description, testCases: imported };
    else if (imported) body = { ...imported, ...(name ? { name } : {}), ...(description ? { description } : {}) };
    else body = { name, description, testCases: [] };
    if (!body.name) throw new Error("Name is required");
    created = await apiWrite<DatasetDetail>("/api/v1/datasets", "POST", body);
  } catch (err) {
    return { error: message(err) };
  }
  revalidatePath("/datasets");
  redirect(`/datasets/${created!.id}`);
}

export async function addTestCaseAction(datasetId: string, _: ActionState, form: FormData): Promise<ActionState> {
  try {
    const body = {
      name: String(form.get("name") ?? "").trim() || undefined,
      input: parseJson("Input", form.get("input"), true),
      expected: parseJson("Expected", form.get("expected")),
      metadata: parseJson("Metadata", form.get("metadata")),
    };
    await apiWrite<TestCase[]>(`/api/v1/datasets/${datasetId}/testcases`, "POST", body);
  } catch (err) {
    return { error: message(err) };
  }
  revalidatePath(`/datasets/${datasetId}`);
  return { ok: true };
}

export async function deleteTestCaseAction(datasetId: string, testCaseId: string): Promise<ActionState> {
  try {
    await apiWrite(`/api/v1/datasets/${datasetId}/testcases/${testCaseId}`, "DELETE");
  } catch (err) {
    return { error: message(err) };
  }
  revalidatePath(`/datasets/${datasetId}`);
  return { ok: true };
}

export async function deleteDatasetAction(datasetId: string): Promise<ActionState> {
  try {
    await apiWrite(`/api/v1/datasets/${datasetId}`, "DELETE");
  } catch (err) {
    return { error: message(err) };
  }
  revalidatePath("/datasets");
  redirect("/datasets");
}

const AGENT_PRESETS: Record<string, Record<string, unknown>> = {
  "mock-improved": { type: "mock", variant: "improved", model: "mock/cs-agent-v2", flaky: true },
  "mock-baseline": { type: "mock", variant: "baseline", model: "mock/cs-agent-v1" },
};

export async function startRunAction(datasetId: string, _: ActionState, form: FormData): Promise<ActionState> {
  let run: Run | null;
  try {
    const preset = String(form.get("agent") ?? "mock-improved");
    const model = String(form.get("model") ?? "").trim();
    const agent = preset === "litellm" ? { type: "litellm", model: model || "gpt-4o-mini" } : AGENT_PRESETS[preset];
    if (!agent) throw new Error("Unknown agent preset");
    const judgeModel = String(form.get("judgeModel") ?? "mock").trim() || "mock";
    const selected = form.getAll("scorers").map(String);
    const scorers = [
      { type: "exact_match", params: { field: "resolution" } },
      { type: "schema_match" },
      { type: "llm_judge", weight: 2, params: { model: judgeModel } },
      { type: "trajectory" },
    ].filter((s) => selected.includes(s.type));
    if (!scorers.length) throw new Error("Select at least one scorer");
    const config = {
      agent,
      scorers,
      concurrency: Number(form.get("concurrency") ?? 4),
      max_retries: Number(form.get("maxRetries") ?? 2),
      pass_threshold: Number(form.get("passThreshold") ?? 0.85),
    };
    const name = String(form.get("name") ?? "").trim() || `${agent.model ?? preset} · ${new Date().toISOString().slice(0, 16)}`;
    run = await apiWrite<Run>("/api/v1/evals/run", "POST", { datasetId, name, config });
  } catch (err) {
    return { error: message(err) };
  }
  revalidatePath("/runs");
  redirect(`/runs/${run!.id}`);
}
