import { globalIgnores } from "eslint/config";
import nextCoreWebVitals from "eslint-config-next/core-web-vitals";
import nextTypeScript from "eslint-config-next/typescript";

const eslintConfig = [
  globalIgnores([".next/**", "node_modules/**", "next-env.d.ts", "playwright-report/**", "test-results/**"]),
  ...nextCoreWebVitals,
  ...nextTypeScript,
  {
    // Existing data-fetching effects intentionally update local loading/error
    // state; keep the Next 15 behavior while migrating to Next 16's stricter
    // React hooks diagnostics.
    rules: { "react-hooks/set-state-in-effect": "off" },
  },
];

export default eslintConfig;
