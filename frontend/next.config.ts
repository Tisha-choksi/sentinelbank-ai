import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* This dashboard is entirely driven by live data fetched client-side
     from the FastAPI backend -- nothing here benefits from build-time
     static prerendering, and the experimental Cache Components mode
     conflicts with the client hooks (usePathname, useParams) the sidebar
     and alert-detail route rely on. */
  // Produces a self-contained .next/standalone output (a minimal server.js
  // plus only the node_modules it actually needs) so the production Docker
  // image doesn't have to ship the full node_modules tree.
  output: "standalone",
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
