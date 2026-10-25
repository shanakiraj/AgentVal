"use client";

import {
  Background,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { AlertTriangle, Bot, CheckCircle2, MessageSquare, Wrench } from "lucide-react";
import { useMemo, useState } from "react";

import { JsonBlock } from "@/components/json-block";
import { ms, num, usd } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { StepType, TraceStep } from "@/lib/types";

const STYLE: Record<StepType, { label: string; Icon: typeof Bot; cls: string; color: string }> = {
  input: { label: "Input", Icon: MessageSquare, cls: "border-sky-500/50 bg-sky-500/10 text-sky-200", color: "#0ea5e9" },
  llm: { label: "LLM", Icon: Bot, cls: "border-violet-500/50 bg-violet-500/10 text-violet-200", color: "#8b5cf6" },
  tool_call: { label: "Tool call", Icon: Wrench, cls: "border-amber-500/50 bg-amber-500/10 text-amber-200", color: "#f59e0b" },
  output: { label: "Output", Icon: CheckCircle2, cls: "border-emerald-500/50 bg-emerald-500/10 text-emerald-200", color: "#10b981" },
  error: { label: "Error", Icon: AlertTriangle, cls: "border-red-500/60 bg-red-500/10 text-red-200", color: "#ef4444" },
};

type StepNodeData = { step: TraceStep; index: number; selected: boolean };

function preview(step: TraceStep): string {
  if (step.status === "error") return step.error ?? "error";
  const v = step.type === "input" ? (step.input as { prompt?: string })?.prompt : step.output;
  if (v === undefined || v === null) return "";
  const s = typeof v === "string" ? v : JSON.stringify(v);
  return s.length > 90 ? `${s.slice(0, 89)}…` : s;
}

function StepNode({ data }: NodeProps<Node<StepNodeData>>) {
  const { step, index, selected } = data;
  const style = step.status === "error" ? STYLE.error : (STYLE[step.type] ?? STYLE.llm);
  const tokens = (step.tokens?.prompt ?? 0) + (step.tokens?.completion ?? 0);
  return (
    <div
      className={cn(
        "w-[300px] rounded-lg border bg-slate-950 px-3 py-2 shadow-lg transition-shadow",
        style.cls,
        selected && "ring-2 ring-blue-400",
      )}
    >
      <Handle type="target" position={Position.Top} className="!size-2 !border-slate-700 !bg-slate-500" />
      <div className="flex items-center justify-between gap-2 text-xs">
        <span className="flex items-center gap-1.5 font-medium">
          <style.Icon className="size-3.5" />
          {index + 1}. {style.label}
          {step.status === "error" && step.type !== "error" && " (failed)"}
        </span>
        <span className="tabular-nums text-slate-400">{ms(step.latencyMs)}</span>
      </div>
      <div className="mt-1 truncate font-mono text-[13px] text-slate-100">{step.name}</div>
      <div className="mt-1 line-clamp-2 text-[11px] text-slate-400">{preview(step)}</div>
      {tokens > 0 && (
        <div className="mt-1 text-[10px] text-slate-500">
          {num(tokens)} tok · {usd(step.costUsd ?? 0)}
        </div>
      )}
      <Handle type="source" position={Position.Bottom} className="!size-2 !border-slate-700 !bg-slate-500" />
    </div>
  );
}

const nodeTypes = { step: StepNode };

export function TraceGraph({ steps }: { steps: TraceStep[] }) {
  const [selectedId, setSelectedId] = useState<string | undefined>(steps.find((s) => s.status === "error")?.id ?? steps[0]?.id);
  const selected = steps.find((s) => s.id === selectedId);

  const { nodes, edges } = useMemo(() => {
    const nodes: Node<StepNodeData>[] = steps.map((step, i) => ({
      id: step.id,
      type: "step",
      position: { x: step.type === "tool_call" ? 60 : 0, y: i * 140 },
      data: { step, index: i, selected: step.id === selectedId },
    }));
    const edges: Edge[] = steps.slice(1).map((step, i) => ({
      id: `${steps[i].id}-${step.id}`,
      source: steps[i].id,
      target: step.id,
      animated: step.type === "tool_call",
      style: { stroke: step.status === "error" ? "#ef4444" : "#475569", strokeWidth: 1.5 },
      markerEnd: { type: MarkerType.ArrowClosed, color: step.status === "error" ? "#ef4444" : "#475569" },
    }));
    return { nodes, edges };
  }, [steps, selectedId]);

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_380px]">
      <div className="h-[640px] overflow-hidden rounded-xl border border-slate-800 bg-slate-950">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          onNodeClick={(_, n) => setSelectedId(n.id)}
          fitView
          fitViewOptions={{ padding: 0.2, maxZoom: 1 }}
          nodesConnectable={false}
          colorMode="dark"
          style={{ background: "transparent" }}
          minZoom={0.2}
        >
          <Background color="#1e293b" gap={20} />
          <MiniMap
            pannable
            zoomable
            className="!bg-slate-900"
            maskColor="rgba(2,6,23,0.7)"
            nodeColor={(n) => {
              const s = (n.data as StepNodeData).step;
              return s.status === "error" ? STYLE.error.color : (STYLE[s.type]?.color ?? "#64748b");
            }}
          />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
      <div className="space-y-3 rounded-xl border border-slate-800 bg-slate-900/40 p-4">
        {selected ? (
          <>
            <div>
              <div className="text-xs text-slate-500 uppercase">{STYLE[selected.type]?.label ?? selected.type}</div>
              <div className="font-mono text-sm">{selected.name}</div>
            </div>
            <dl className="grid grid-cols-3 gap-2 text-xs">
              <div>
                <dt className="text-slate-500">Latency</dt>
                <dd className="tabular-nums">{ms(selected.latencyMs)}</dd>
              </div>
              <div>
                <dt className="text-slate-500">Tokens</dt>
                <dd className="tabular-nums">
                  {num(selected.tokens?.prompt ?? 0)} / {num(selected.tokens?.completion ?? 0)}
                </dd>
              </div>
              <div>
                <dt className="text-slate-500">Status</dt>
                <dd className={selected.status === "error" ? "text-red-400" : "text-emerald-400"}>{selected.status}</dd>
              </div>
            </dl>
            {selected.error && (
              <p className="rounded-md border border-red-500/30 bg-red-500/10 px-2 py-1.5 text-xs text-red-300">{selected.error}</p>
            )}
            <div className="space-y-1">
              <div className="text-xs text-slate-500">Input</div>
              <JsonBlock value={selected.input} className="max-h-48" />
            </div>
            <div className="space-y-1">
              <div className="text-xs text-slate-500">Output</div>
              <JsonBlock value={selected.output} className="max-h-48" />
            </div>
            {selected.attributes && Object.keys(selected.attributes).length > 0 && (
              <div className="space-y-1">
                <div className="text-xs text-slate-500">Attributes</div>
                <JsonBlock value={selected.attributes} className="max-h-32" />
              </div>
            )}
          </>
        ) : (
          <p className="text-sm text-slate-400">Select a step to inspect it.</p>
        )}
      </div>
    </div>
  );
}
