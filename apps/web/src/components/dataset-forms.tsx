"use client";

import { Loader2, Play, Plus, Trash2 } from "lucide-react";
import { useActionState, useEffect, useState, useTransition } from "react";

import {
  addTestCaseAction,
  createDatasetAction,
  deleteDatasetAction,
  deleteTestCaseAction,
  startRunAction,
  type ActionState,
} from "@/app/actions";
import { FormError } from "@/components/form-error";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

const selectCls =
  "h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30";

function Submit({ pending, children }: { pending: boolean; children: React.ReactNode }) {
  return (
    <Button type="submit" disabled={pending}>
      {pending && <Loader2 className="size-4 animate-spin" />}
      {children}
    </Button>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-1.5">
      <Label>{label}</Label>
      {children}
      {hint && <p className="text-xs text-slate-500">{hint}</p>}
    </div>
  );
}

export function NewDatasetDialog({ disabled }: { disabled?: boolean }) {
  const [state, action, pending] = useActionState<ActionState, FormData>(createDatasetAction, {});
  return (
    <Dialog>
      <DialogTrigger render={<Button disabled={disabled} />}>
        <Plus className="size-4" /> New dataset
      </DialogTrigger>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>New dataset</DialogTitle>
          <DialogDescription>Create an empty dataset, or paste a dataset/test-case JSON export.</DialogDescription>
        </DialogHeader>
        <form action={action} className="grid gap-4">
          <Field label="Name">
            <Input name="name" placeholder="Customer Service Agent Evaluation" />
          </Field>
          <Field label="Description">
            <Input name="description" placeholder="What does this dataset test?" />
          </Field>
          <Field label="Import JSON (optional)" hint='{"name", "description", "testCases": [{"input", "expected", "metadata"}]} or a bare array of test cases'>
            <Textarea name="json" rows={6} className="font-mono text-xs" placeholder='{"testCases": [{"input": {"prompt": "..."}}]}' />
          </Field>
          <FormError error={state.error} />
          <DialogFooter>
            <Submit pending={pending}>Create</Submit>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function AddTestCaseDialog({ datasetId, disabled }: { datasetId: string; disabled?: boolean }) {
  const [open, setOpen] = useState(false);
  const [state, action, pending] = useActionState<ActionState, FormData>(
    addTestCaseAction.bind(null, datasetId),
    {},
  );
  useEffect(() => {
    if (state.ok) setOpen(false);
  }, [state]);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={<Button variant="outline" disabled={disabled} />}>
        <Plus className="size-4" /> Add test case
      </DialogTrigger>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Add test case</DialogTitle>
          <DialogDescription>Inputs and expectations are free-form JSON.</DialogDescription>
        </DialogHeader>
        <form action={action} className="grid gap-4">
          <Field label="Name">
            <Input name="name" placeholder="Refund for damaged item" />
          </Field>
          <Field label="Input (JSON)" hint="prompt, context (initial environment state), tools">
            <Textarea name="input" rows={5} required className="font-mono text-xs" defaultValue={'{\n  "prompt": "",\n  "context": {}\n}'} />
          </Field>
          <Field label="Expected (JSON, optional)" hint="resolution, reply_contains, tool_calls, max_steps, schema, output">
            <Textarea name="expected" rows={5} className="font-mono text-xs" placeholder='{"resolution": "resolved", "tool_calls": [{"name": "lookup_order"}]}' />
          </Field>
          <Field label="Metadata (JSON, optional)">
            <Input name="metadata" className="font-mono text-xs" placeholder='{"category": "refund"}' />
          </Field>
          <FormError error={state.error} />
          <DialogFooter>
            <Submit pending={pending}>Add</Submit>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function RunEvalDialog({ datasetId, disabled }: { datasetId: string; disabled?: boolean }) {
  const [state, action, pending] = useActionState<ActionState, FormData>(startRunAction.bind(null, datasetId), {});
  const [agent, setAgent] = useState("mock-improved");
  return (
    <Dialog>
      <DialogTrigger render={<Button disabled={disabled} />}>
        <Play className="size-4" /> Run evaluation
      </DialogTrigger>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Run evaluation</DialogTitle>
          <DialogDescription>Runs asynchronously on the AgentVal API; progress updates live.</DialogDescription>
        </DialogHeader>
        <form action={action} className="grid gap-4">
          <Field label="Run name">
            <Input name="name" placeholder="v1.3 system prompt + mock agent" />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Agent">
              <select name="agent" className={selectCls} value={agent} onChange={(e) => setAgent(e.target.value)}>
                <option value="mock-improved">Mock agent · improved (no keys)</option>
                <option value="mock-baseline">Mock agent · baseline (no keys)</option>
                <option value="litellm">LiteLLM tool agent</option>
              </select>
            </Field>
            <Field label="Model" hint={agent === "litellm" ? "Key read from API env" : "Only used by LiteLLM"}>
              <Input name="model" placeholder="gpt-4o-mini" disabled={agent !== "litellm"} />
            </Field>
          </div>
          <Field label="Scorers">
            <div className="grid grid-cols-2 gap-2 text-sm">
              {["exact_match", "schema_match", "llm_judge", "trajectory"].map((s) => (
                <label key={s} className="flex items-center gap-2 rounded-md border border-slate-800 px-2 py-1.5">
                  <input type="checkbox" name="scorers" value={s} defaultChecked className="accent-blue-500" />
                  <span className="font-mono text-xs">{s}</span>
                </label>
              ))}
            </div>
          </Field>
          <div className="grid grid-cols-3 gap-3">
            <Field label="Judge model">
              <Input name="judgeModel" defaultValue="mock" />
            </Field>
            <Field label="Concurrency">
              <Input name="concurrency" type="number" min={1} max={64} defaultValue={4} />
            </Field>
            <Field label="Pass threshold">
              <Input name="passThreshold" type="number" min={0} max={1} step={0.05} defaultValue={0.85} />
            </Field>
          </div>
          <input type="hidden" name="maxRetries" value={2} />
          <FormError error={state.error} />
          <DialogFooter>
            <Submit pending={pending}>Start run</Submit>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function DeleteButton({
  kind,
  datasetId,
  testCaseId,
  disabled,
}: {
  kind: "dataset" | "testcase";
  datasetId: string;
  testCaseId?: string;
  disabled?: boolean;
}) {
  const [pending, start] = useTransition();
  const [error, setError] = useState<string>();
  return (
    <span className="inline-flex items-center gap-2">
      <Button
        variant={kind === "dataset" ? "destructive" : "ghost"}
        size={kind === "dataset" ? "default" : "icon-sm"}
        disabled={disabled || pending}
        aria-label={`Delete ${kind}`}
        onClick={() => {
          if (!confirm(kind === "dataset" ? "Delete this dataset and all its runs?" : "Delete this test case?")) return;
          start(async () => {
            const res =
              kind === "dataset"
                ? await deleteDatasetAction(datasetId)
                : await deleteTestCaseAction(datasetId, testCaseId!);
            if (res?.error) setError(res.error);
          });
        }}
      >
        {pending ? <Loader2 className="size-4 animate-spin" /> : <Trash2 className="size-4" />}
        {kind === "dataset" && "Delete"}
      </Button>
      {error && <span className="text-xs text-red-400">{error}</span>}
    </span>
  );
}
