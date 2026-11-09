// One flat ESLint config for every app in this workspace (apps/web and apps/api).
import { defineConfig, globalIgnores } from "eslint/config";
import js from "@eslint/js";
import tseslint from "typescript-eslint";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

export default defineConfig([
  globalIgnores([
    "**/node_modules/**",
    "**/.next/**",
    "**/dist/**",
    "**/build/**",
    "**/out/**",
    "**/coverage/**",
    "**/generated/**",
    "**/next-env.d.ts",
  ]),
  js.configs.recommended,
  ...tseslint.configs.recommended,
  // Next.js rules and the Next.js TypeScript defaults, for apps/web.
  // They are harmless on apps/api, which has no React code.
  ...nextVitals,
  ...nextTs,
  // This app uses the App Router only, so there is no pages/ directory to
  // check links against.
  {
    rules: {
      "@next/next/no-html-link-for-pages": "off",
    },
  },
]);
