# @agentval/web

Next.js 15 (App Router) studio for AgentVal: datasets, runs dashboard, run details,
React Flow trace graphs and run-vs-run comparison. Dark mode by default, Tailwind CSS v4,
shadcn/ui components and lucide icons.

```bash
cp .env.example .env.local      # optional
npm install
npm run dev                     # http://localhost:3000
npm run typecheck && npm run lint && npm run build
```

Data comes from the FastAPI backend (`NEXT_PUBLIC_API_URL` or server-only `API_URL`). All API calls
happen server-side (server components + server actions), so the browser never needs CORS access.
Without a reachable API the app falls back to the bundled demo data in `src/lib/demo-data.json`
(regenerate it with `agentval seed && agentval export-demo -o apps/web/src/lib/demo-data.json`).

See the repository root README for Vercel deployment steps.
