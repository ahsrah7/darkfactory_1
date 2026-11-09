import { spawn, type ChildProcess } from "node:child_process";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { createServer } from "node:net";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

// The web app is built by `npm run build -w apps/web`. `npm run verify` builds
// before it runs the tests. These tests read the build output and start the
// production server with `next start`.
const here = dirname(fileURLToPath(import.meta.url));
const webDir = resolve(here, "../../web");
const buildDir = join(webDir, ".next");
const pagePath = join(webDir, "app", "page.tsx");

const requireFromWeb = createRequire(join(webDir, "package.json"));
const nextPackageDir = dirname(requireFromWeb.resolve("next/package.json"));
const nextBin = join(nextPackageDir, "dist", "bin", "next");

const STARTUP_TIMEOUT_MS = 90_000;

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

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * Returns the names in `classes` that have a CSS rule. A rule means the class
 * selector `.name` appears before any `{` with no `}` or `;` in between, as in
 * `.flex{display:flex}`. Comments are ignored.
 */
export function classesWithRules(
  css: string,
  classes: readonly string[],
): string[] {
  const body = css.replace(/\/\*[\s\S]*?\*\//g, "");
  return classes.filter((name) =>
    new RegExp(`\\.${escapeRegExp(name)}(?![\\w-])(?=[^{};]*\\{)`).test(body),
  );
}

/** Every class name in the className="..." attributes of a TSX source. */
function classNamesIn(source: string): string[] {
  return [...source.matchAll(/className="([^"]*)"/g)]
    .flatMap((match) => (match[1] ?? "").split(/\s+/))
    .filter((name) => name !== "");
}

/** Every .css file under dir. The build cache is skipped. */
function cssFilesUnder(dir: string): string[] {
  const found: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name !== "cache") found.push(...cssFilesUnder(path));
    } else if (entry.isFile() && entry.name.endsWith(".css")) {
      found.push(path);
    }
  }
  return found;
}

describe("web app (AC2)", () => {
  let server: ChildProcess | undefined;
  let output = "";
  let baseUrl = "";

  beforeAll(async () => {
    if (!existsSync(buildDir)) {
      throw new Error(
        `missing ${buildDir}; run "npm run build -w apps/web" first`,
      );
    }
    const port = await freePort();
    baseUrl = `http://127.0.0.1:${port}`;
    const child = spawn(
      process.execPath,
      [nextBin, "start", "-p", String(port), "-H", "127.0.0.1"],
      {
        cwd: webDir,
        env: {
          ...process.env,
          NODE_ENV: "production",
          NEXT_TELEMETRY_DISABLED: "1",
        },
        stdio: ["ignore", "pipe", "pipe"],
      },
    );
    server = child;
    const collect = (chunk: Buffer | string): void => {
      output = (output + String(chunk)).slice(-4_000);
    };
    child.stdout?.on("data", collect);
    child.stderr?.on("data", collect);

    const deadline = Date.now() + STARTUP_TIMEOUT_MS;
    let lastError = "no response yet";
    while (Date.now() < deadline) {
      if (child.exitCode !== null || child.signalCode !== null) {
        throw new Error(`next start exited before responding:\n${output}`);
      }
      try {
        const response = await fetch(`${baseUrl}/`);
        await response.arrayBuffer();
        if (response.status === 200) return;
        lastError = `status ${response.status}`;
      } catch (error) {
        lastError = String(error);
      }
      await sleep(250);
    }
    throw new Error(
      `next start did not return 200 within ${STARTUP_TIMEOUT_MS} ms (${lastError}):\n${output}`,
    );
  }, STARTUP_TIMEOUT_MS + 15_000);

  afterAll(async () => {
    const child = server;
    if (child === undefined) return;
    if (child.exitCode !== null || child.signalCode !== null) return;
    const exited = new Promise<void>((done) =>
      child.once("exit", () => done()),
    );
    child.kill();
    const forceKill = setTimeout(() => child.kill("SIGKILL"), 10_000);
    await exited;
    clearTimeout(forceKill);
  }, 30_000);

  // AC2: the root page returns 200 from the production server.
  it("AC2: GET / returns HTTP 200 from next start", async () => {
    const response = await fetch(`${baseUrl}/`);
    await response.arrayBuffer();
    expect(response.status).toBe(200);
  }, 30_000);
});

describe("web app build (AC3)", () => {
  // AC3: the build CSS has rules for the Tailwind utility classes that the root
  // page uses.
  it("AC3: the emitted CSS has a rule for at least one utility class used by the root page", () => {
    expect(
      existsSync(buildDir),
      `missing ${buildDir}; run "npm run build -w apps/web" first`,
    ).toBe(true);

    const cssFiles = cssFilesUnder(buildDir);
    expect(cssFiles, `no .css files under ${buildDir}`).not.toHaveLength(0);
    const css = cssFiles.map((file) => readFileSync(file, "utf8")).join("\n");

    const pageClasses = classNamesIn(readFileSync(pagePath, "utf8"));
    expect(pageClasses, "root page has no className values").not.toHaveLength(
      0,
    );

    const withRules = classesWithRules(css, pageClasses);
    expect(
      withRules,
      `none of the root page classes (${pageClasses.join(" ")}) has a CSS rule`,
    ).not.toHaveLength(0);
  });

  // The check above must be able to fail. These cases pin its behaviour.
  it("the rule check finds no rules in CSS that has only base styles", () => {
    expect(
      classesWithRules("body{margin:0}:root{--x:1}", ["flex", "p-8"]),
    ).toEqual([]);
  });

  it("the rule check finds the classes that have rules and ignores the rest", () => {
    expect(
      classesWithRules(
        "/* .p-8{} */.flex{display:flex}.flex-col{flex-direction:column}.p-8{padding:2rem}",
        ["flex", "p-8", "min-h-screen"],
      ),
    ).toEqual(["flex", "p-8"]);
  });
});
