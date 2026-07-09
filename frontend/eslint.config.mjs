import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    rules: {
      // El patrón actual de carga de datos (setState síncrono dentro de
      // useEffect) dispara esta regla en todas las páginas. Su corrección es
      // la migración a una capa de data-fetching (CAL-5 del análisis de
      // mejoras, pospuesta); mientras tanto queda como aviso para que el lint
      // de CI siga siendo bloqueante para todo lo demás.
      "react-hooks/set-state-in-effect": "warn",
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
