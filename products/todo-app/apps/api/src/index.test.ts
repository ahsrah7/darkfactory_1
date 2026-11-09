import { spawn, spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { createServer } from "node:net";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

// The real entry point, compiled by `npm run build -w apps/api`. `npm run verify`
// builds before it runs the tests.
const here = dirname(fileURLToPath(import.meta.url));
const entryPoint = resolve(here, "../dist/index.js");

// A placeholder with no credentials. The API does not connect at startup.
const PLACEHOLDER_DATABASE_URL = "postgresql://localhost:5432/placeholder";

function sleep(ms: number): Promise<void> {
  return new Promise((done) => setTimeout(done, ms));
}

/** Asks the OS for a port that is free right now. */
function freePort(): Promise<number> {
  return new Promise((done, fail) => {
    const probe = createServer();
    probe.on("error", fail);
    probe.listen(0, "127.0.0.1", () => {
      const address = probe.address();
      probe.close(() => {
        if (address === null || typeof address === "string") {
          fail(new Error("could not read a free port"));
          return;
        }
        done(address.port);
      });
    });
  });
}

/** True while a process with this PID exists. */
function isAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    // EPERM means the process exists but belongs to another user.
    return (error as NodeJS.ErrnoException).code === "EPERM";
  }
}

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

  // AC5: the API logs its port, is still running 10 seconds later, and its PID
  // is gone after it is stopped.
  it("AC5: logs its port, stays alive for 10 seconds, and its PID is gone after kill", async () => {
    expect(
      existsSync(entryPoint),
      `missing ${entryPoint}; run "npm run build -w apps/api" first`,
    ).toBe(true);

    const port = await freePort();
    const child = spawn(process.execPath, [entryPoint], {
      env: {
        ...process.env,
        PORT: String(port),
        DATABASE_URL: PLACEHOLDER_DATABASE_URL,
      },
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    child.stdout?.setEncoding("utf8");
    child.stdout?.on("data", (chunk: string) => {
      stdout += chunk;
    });
    child.stderr?.setEncoding("utf8");
    child.stderr?.on("data", (chunk: string) => {
      stderr += chunk;
    });
    const exited = new Promise<void>((done) =>
      child.once("exit", () => done()),
    );
    const pid = child.pid;
    expect(pid, "spawn did not return a PID").toBeTypeOf("number");

    try {
      const listening = new RegExp(`^API listening on port ${port}\\r?$`, "m");
      const deadline = Date.now() + 15_000;
      while (!listening.test(stdout) && Date.now() < deadline) {
        if (child.exitCode !== null || child.signalCode !== null) break;
        await sleep(100);
      }
      expect(
        listening.test(stdout),
        `no "API listening on port ${port}" line. stdout: ${stdout} stderr: ${stderr}`,
      ).toBe(true);

      await sleep(10_000);
      expect(
        child.exitCode,
        `API exited within 10 seconds. stderr: ${stderr}`,
      ).toBeNull();
      expect(child.signalCode).toBeNull();

      child.kill();
      await exited;
      expect(pid !== undefined && isAlive(pid)).toBe(false);
    } finally {
      if (child.exitCode === null && child.signalCode === null) {
        child.kill("SIGKILL");
      }
    }
  }, 30_000);
});
