import { readdirSync, readFileSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

// AC13: no automated step applies a migration. This test reads the app's
// package.json scripts, the files under scripts/ and the README as text. The
// only places that may name the forbidden commands are:
//   1. the human-only script definition "db:migrate:deploy": "prisma migrate deploy"
//   2. the "## Migration policy" section of the README
const here = dirname(fileURLToPath(import.meta.url));
const appRoot = resolve(here, "../../..");

const FORBIDDEN: readonly { label: string; pattern: RegExp }[] = [
  { label: "migrate deploy", pattern: /\bmigrate\s+deploy\b/ },
  { label: "migrate dev", pattern: /\bmigrate\s+dev\b/ },
  { label: "migrate reset", pattern: /\bmigrate\s+reset\b/ },
  { label: "db push", pattern: /\bdb\s+push\b/ },
  // Naming the human-only script from another script would run it too.
  { label: "db:migrate:deploy", pattern: /\bdb:migrate:deploy\b/ },
];

const HUMAN_ONLY_SCRIPT = "db:migrate:deploy";
const HUMAN_ONLY_COMMAND = "prisma migrate deploy";

interface Hit {
  line: number;
  label: string;
}

/** Forbidden commands found in text, with 1-based line numbers. */
export function forbiddenUses(text: string): Hit[] {
  const hits: Hit[] = [];
  text.split(/\r?\n/).forEach((line, index) => {
    for (const { label, pattern } of FORBIDDEN) {
      if (pattern.test(line)) hits.push({ line: index + 1, label });
    }
  });
  return hits;
}

/** The README text with its "## Migration policy" section removed. */
export function outsidePolicySection(markdown: string): string {
  const heading = /^## Migration policy\r?$/m.exec(markdown);
  if (heading === null) {
    throw new Error('README has no "## Migration policy" section');
  }
  const bodyStart = heading.index + heading[0].length;
  const nextHeading = /^## /m.exec(markdown.slice(bodyStart));
  const bodyEnd =
    nextHeading === null ? markdown.length : bodyStart + nextHeading.index;
  return markdown.slice(0, heading.index) + markdown.slice(bodyEnd);
}

function filesUnder(dir: string): string[] {
  const found: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) found.push(...filesUnder(path));
    else if (entry.isFile()) found.push(path);
  }
  return found;
}

/** Forbidden script commands in a package.json, as "script: label" strings. */
function scriptViolations(manifestPath: string): string[] {
  const manifest = JSON.parse(readFileSync(manifestPath, "utf8")) as {
    scripts?: Record<string, string>;
  };
  const violations: string[] = [];
  for (const [name, command] of Object.entries(manifest.scripts ?? {})) {
    if (name === HUMAN_ONLY_SCRIPT && command === HUMAN_ONLY_COMMAND) continue;
    for (const hit of forbiddenUses(command)) {
      violations.push(`${name}: ${hit.label}`);
    }
  }
  return violations;
}

function manifestPaths(): string[] {
  const apps = join(appRoot, "apps");
  const workspaces = readdirSync(apps, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => join(apps, entry.name, "package.json"));
  return [join(appRoot, "package.json"), ...workspaces];
}

describe("migration policy (AC13)", () => {
  // AC13: package.json scripts never run a forbidden migrate command.
  it("AC13: no package.json script runs migrate deploy, migrate dev, migrate reset or db push", () => {
    const violations = manifestPaths().flatMap(scriptViolations);
    expect(violations).toEqual([]);
  });

  it("AC13: the human-only db:migrate:deploy script is defined as prisma migrate deploy", () => {
    const manifest = JSON.parse(
      readFileSync(join(appRoot, "package.json"), "utf8"),
    ) as { scripts?: Record<string, string> };
    expect(manifest.scripts?.[HUMAN_ONLY_SCRIPT]).toBe(HUMAN_ONLY_COMMAND);
  });

  // AC13: nothing under scripts/ runs a forbidden command. No exception applies.
  it("AC13: no file under scripts/ names a forbidden migrate command", () => {
    const files = filesUnder(join(appRoot, "scripts"));
    expect(files).not.toHaveLength(0);
    const violations = files.flatMap((file) =>
      forbiddenUses(readFileSync(file, "utf8")).map(
        (hit) => `${relative(appRoot, file)}:${hit.line}: ${hit.label}`,
      ),
    );
    expect(violations).toEqual([]);
  });

  // AC13: the README names the forbidden commands only in its policy section.
  it("AC13: the README names forbidden commands only in the Migration policy section", () => {
    const readme = readFileSync(join(appRoot, "README.md"), "utf8");
    const violations = forbiddenUses(outsidePolicySection(readme)).map(
      (hit) => `README.md: ${hit.label}`,
    );
    expect(violations).toEqual([]);
  });

  // The checks above must be able to fail. These cases pin the detector.
  it("the detector flags each forbidden command", () => {
    const labels = forbiddenUses(
      [
        "prisma migrate deploy",
        "prisma migrate dev --name x",
        "prisma migrate reset --force",
        "prisma db push",
        "npm run db:migrate:deploy",
      ].join("\n"),
    ).map((hit) => hit.label);
    expect(labels).toEqual([
      "migrate deploy",
      "migrate dev",
      "migrate reset",
      "db push",
      "db:migrate:deploy",
    ]);
  });

  it("the detector allows read-only and unrelated commands", () => {
    expect(
      forbiddenUses(
        "prisma migrate status\nprisma validate\nprisma generate\nnpm run db:check",
      ),
    ).toEqual([]);
  });

  it("the README exemption removes only the Migration policy section", () => {
    const readme = [
      "## Database",
      "prisma migrate dev is not used here",
      "",
      "## Migration policy",
      "prisma migrate deploy is human only",
      "",
      "## Secrets",
      "prisma db push is not a script",
      "",
    ].join("\n");
    const outside = outsidePolicySection(readme);
    expect(outside).toContain("prisma migrate dev is not used here");
    expect(outside).toContain("## Secrets");
    expect(outside).not.toContain("prisma migrate deploy is human only");
    expect(forbiddenUses(outside).map((hit) => hit.label)).toEqual([
      "migrate dev",
      "db push",
    ]);
  });
});
