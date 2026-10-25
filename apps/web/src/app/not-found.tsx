import Link from "next/link";

export default function NotFound() {
  return (
    <div className="flex flex-col items-center gap-3 py-24 text-center">
      <h1 className="text-xl font-semibold">Not found</h1>
      <p className="text-sm text-slate-400">That dataset, run or trace doesn&apos;t exist.</p>
      <Link href="/runs" className="text-sm text-blue-400 hover:underline">
        Back to runs
      </Link>
    </div>
  );
}
