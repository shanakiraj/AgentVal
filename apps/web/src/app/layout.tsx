import type { Metadata } from "next";

import { Sidebar } from "@/components/nav";
import { TooltipProvider } from "@/components/ui/tooltip";

import "./globals.css";

export const metadata: Metadata = {
  title: { default: "AgentVal", template: "%s · AgentVal" },
  description: "Agent Validation & Evaluation Studio: benchmark and stress-test multi-step AI agents.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className="dark" style={{ colorScheme: "dark" }}>
      <body className="min-h-screen bg-slate-950 text-slate-100 antialiased">
        <TooltipProvider>
          <div className="flex min-h-screen flex-col md:flex-row">
            <Sidebar />
            <main className="min-w-0 flex-1 px-4 py-6 md:px-8">
              <div className="mx-auto max-w-7xl space-y-6">{children}</div>
            </main>
          </div>
        </TooltipProvider>
      </body>
    </html>
  );
}
