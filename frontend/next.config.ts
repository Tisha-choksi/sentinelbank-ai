import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* This dashboard is entirely driven by live data fetched client-side
     from the FastAPI backend -- nothing here benefits from build-time
     static prerendering, and the experimental Cache Components mode
     conflicts with the client hooks (usePathname, useParams) the sidebar
     and alert-detail route rely on. */
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
