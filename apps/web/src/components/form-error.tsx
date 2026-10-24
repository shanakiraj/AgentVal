export function FormError({ error }: { error?: string }) {
  if (!error) return null;
  return <p className="rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-300">{error}</p>;
}
