import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Docker builds set NEXT_OUTPUT=standalone for a minimal runtime image.
  // Vercel uses its own output format, so leave it unset there.
  output: process.env.NEXT_OUTPUT === "standalone" ? "standalone" : undefined,
  poweredByHeader: false,
};

export default nextConfig;
