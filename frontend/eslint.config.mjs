import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    rules: {
      // This app has no server-side data layer -- every page fetches live
      // from the FastAPI backend client-side. The cancelable
      // fetch-on-mount-with-cleanup pattern in src/lib/useAsync.ts is the
      // React-documented correct way to do that ("You Might Not Need an
      // Effect"), and is this app's single shared data-fetching primitive,
      // not a one-off. This rule's blanket ban on any setState reachable
      // from an effect body flags that correct pattern as if it were a
      // cascading-render bug.
      "react-hooks/set-state-in-effect": "off",
    },
  },
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
  ]),
]);

export default eslintConfig;
