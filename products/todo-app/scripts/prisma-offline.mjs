// Runs `prisma validate` or `prisma generate` without a database.
//
// Prisma 7 cannot load prisma.config.ts when DATABASE_URL is unset (its env()
// call throws), and neither command connects to a database. This wrapper sets
// DATABASE_URL to a placeholder for the child process only. Any value already in
// the caller's environment is replaced, not read, so a real URL is never used.
// The placeholder has no credentials.
import { spawnSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const PLACEHOLDER_DATABASE_URL = "postgresql://localhost:5432/placeholder";
const ALLOWED_COMMANDS = ["validate", "generate"];

const command = process.argv[2];
if (!ALLOWED_COMMANDS.includes(command)) {
  console.error(
    `usage: node scripts/prisma-offline.mjs <${ALLOWED_COMMANDS.join("|")}>`,
  );
  process.exit(2);
}

const appRoot = join(dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(import.meta.url);
const prismaPackageDir = dirname(require.resolve("prisma/package.json"));
const prismaCli = join(prismaPackageDir, "build", "index.js");

const result = spawnSync(process.execPath, [prismaCli, command], {
  cwd: appRoot,
  stdio: "inherit",
  env: { ...process.env, DATABASE_URL: PLACEHOLDER_DATABASE_URL },
});

if (result.error) {
  console.error(`Failed to start Prisma CLI: ${result.error.message}`);
  process.exit(1);
}
process.exit(result.status ?? 1);
