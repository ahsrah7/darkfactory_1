import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

// The real entry point, compiled by `npm run build -w apps/api`. `npm run verify`
// builds before it runs the tests.
const here = dirname(fileURLToPath(import.meta.url));
const entryPoint = resolve(here, "../dist/index.js");

describe("API entry point", () => {
  // AC7: with DATABASE_URL unset, startup exits non-zero, names DATABASE_URL,
  // and prints no value.
  it("AC7: exits 1, names DATABASE_URL, and prints no value when DATABASE_URL is unset", () => {
    expect(
      existsSync(entryPoint),
      `missing ${entryPoint}; run "npm run build -w apps/api" first`,
    ).toBe(true);

    // Remove PORT as well, so an invalid PORT in the parent shell cannot make the
    // child fail for a different reason.
    const env: NodeJS.ProcessEnv = { ...process.env };
    delete env["DATABASE_URL"];
    delete env["PORT"];

    const result = spawnSync(process.execPath, [entryPoint], {
      env,
      encoding: "utf8",
      timeout: 10_000,
    });

    // A timeout sets result.error (ETIMEDOUT), so this also catches a hang.
    expect(result.error).toBeUndefined();
    expect(result.status).toBe(1);
    expect(result.stderr).toContain("DATABASE_URL is not set");
    // The message never includes a URL, so no connection string can leak.
    expect(result.stdout).not.toContain("://");
    expect(result.stderr).not.toContain("://");
  }, 15_000);
});
