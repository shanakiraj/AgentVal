export type RunStatus = "PENDING" | "RUNNING" | "COMPLETED" | "FAILED";
export type ResultStatus = "PASS" | "PARTIAL" | "FAIL" | "ERROR";
export type DataSource = "live" | "demo";

export interface TestCase {
  id: string;
  datasetId: string;
  name?: string | null;
  input: Record<string, unknown>;
  expected?: Record<string, unknown> | null;
  metadata?: Record<string, unknown> | null;
  createdAt: string;
}

export interface Dataset {
  id: string;
  name: string;
  description?: string | null;
  createdAt: string;
  updatedAt: string;
  testCaseCount: number;
  runCount: number;
}

export interface DatasetDetail extends Dataset {
  testCases: TestCase[];
}

export interface RunMetrics {
  total: number;
  passed: number;
  partial: number;
  failed: number;
  errored: number;
  passRate: number;
  avgScore: number;
  avgLatencyMs: number;
  p50LatencyMs: number;
  p95LatencyMs: number;
  totalCostUsd: number;
  promptTokens: number;
  completionTokens: number;
  tokenCount: number;
  totalRetries: number;
  scorerAverages: Record<string, number>;
  durationMs?: number | null;
}

export interface Run {
  id: string;
  datasetId: string;
  datasetName?: string | null;
  name: string;
  status: RunStatus;
  model?: string | null;
  config: Record<string, unknown>;
  metrics?: RunMetrics | null;
  totalCases: number;
  completedCases: number;
  progress: number;
  error?: string | null;
  createdAt: string;
  startedAt?: string | null;
  finishedAt?: string | null;
}

export interface ScoreEntry {
  name: string;
  score: number;
  passed: boolean;
  rationale: string;
  details: Record<string, unknown>;
  skipped: boolean;
  weight: number;
}

export type StepType = "input" | "llm" | "tool_call" | "output" | "error";

export interface TraceStep {
  id: string;
  parentId?: string | null;
  type: StepType;
  name: string;
  input?: unknown;
  output?: unknown;
  status: "ok" | "error";
  error?: string | null;
  latencyMs: number;
  startTimeUnixNano?: string;
  endTimeUnixNano?: string;
  tokens?: { prompt: number; completion: number };
  costUsd?: number;
  attributes?: Record<string, unknown>;
}

export interface Trace {
  traceId: string;
  rootSpanId?: string;
  steps: TraceStep[];
  messages?: Array<Record<string, unknown>>;
  attempts?: number;
  retries?: Array<{ attempt: number; error: string }>;
  totals?: Record<string, number | null>;
}

export interface EvalResult {
  id: string;
  evalRunId: string;
  testCaseId: string;
  testCaseName?: string | null;
  input?: Record<string, unknown> | null;
  expected?: Record<string, unknown> | null;
  actual: unknown;
  trace?: Trace | null;
  score: number;
  passed: boolean;
  status: ResultStatus;
  scores: Record<string, ScoreEntry>;
  latencyMs: number;
  costUsd: number;
  promptTokens: number;
  completionTokens: number;
  attempts: number;
  error?: string | null;
}

export interface RunDetail extends Run {
  results: EvalResult[];
}

export interface Fetched<T> {
  data: T;
  source: DataSource;
  /** Why the demo fallback was used (unset when live). */
  reason?: string;
}
