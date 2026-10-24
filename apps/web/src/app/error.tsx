"use client";

export default function Error({ error, reset }: { error: Error; reset: () => void }) {
  return (
    <div className="space-y-3 py-24 text-center">
      <h1 className="text-xl font-semibold">Something went wrong</h1>
      <p className="text-sm text-slate-400">{error.message}</p>
      <button onClick={reset} className="text-sm text-blue-400 hover:underline">
        Try again
      </button>
    </div>
  );
}
