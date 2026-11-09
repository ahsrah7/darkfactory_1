// Secret scan over the files of this app that would be committed (run from
// products/todo-app).
//
// The file list is every tracked file plus every untracked file that is not
// ignored. Scanning only tracked files would miss new files before they are
// staged, so the scan would pass on nothing.
//
// Checks, in order:
//   1. No env file in that list other than .env.example.
//   2. `git grep` over those files, using the patterns in
//      scripts/secret-patterns.txt. The pattern file itself is excluded.
//
// Output shows file and line numbers only. It never prints matched text, so a
// finding cannot leak the secret into logs. Exit codes: 0 clean, 1 findings,
// 2 the scan could not run.
import { spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";

const PATTERN_FILE = "scripts/secret-patterns.txt";
const ENV_FILE_NAME = /(^|\/)\.env(\..*)?$/;
const ENV_EXAMPLE_NAME = /(^|\/)\.env\.example$/;

function git(args) {
  const result = spawnSync("git", args, {
    encoding: "utf8",
    maxBuffer: 64 << 20,
  });
  if (result.error || result.status === null) {
    console.error(`secrets:scan: could not run git ${args[0]}`);
    process.exit(2);
  }
  return result;
}

const listed = git([
  "ls-files",
  "-z",
  "--cached",
  "--others",
  "--exclude-standard",
]);
if (listed.status !== 0) {
  console.error("secrets:scan: git ls-files failed");
  process.exit(2);
}
// A tracked file deleted in the working tree is listed but not on disk. Skip it.
const candidateFiles = [
  ...new Set(listed.stdout.split("\0").filter((file) => file !== "")),
];
const scannedFiles = candidateFiles.filter((file) => existsSync(file));

const envFiles = scannedFiles.filter(
  (file) => ENV_FILE_NAME.test(file) && !ENV_EXAMPLE_NAME.test(file),
);
for (const file of envFiles) {
  console.error(`FINDING env file would be committed: ${file}`);
}

const patterns = readFileSync(PATTERN_FILE, "utf8")
  .split("\n")
  .map((line) => line.trimEnd())
  .filter((line) => line !== "" && !line.startsWith("#"));

const scanTargets = scannedFiles.filter((file) => file !== PATTERN_FILE);
let findingCount = envFiles.length;

for (const pattern of patterns) {
  const result = git([
    "grep",
    "--no-index",
    "-i",
    "-n",
    "-I",
    "-E",
    "-e",
    pattern,
    "--",
    ...scanTargets,
  ]);
  // git grep exits 1 when nothing matches. Any other non-zero status is an error.
  if (result.status === 1) continue;
  if (result.status !== 0) {
    console.error("secrets:scan: git grep failed");
    process.exit(2);
  }
  for (const line of result.stdout.split("\n")) {
    const match = /^([^:]+):(\d+):/.exec(line);
    if (match) {
      findingCount += 1;
      console.error(`FINDING ${match[1]}:${match[2]}`);
    }
  }
}

if (findingCount > 0) {
  console.error(`secrets:scan: ${findingCount} finding(s). Treat as leaked.`);
  process.exit(1);
}
console.log(
  `secrets:scan: clean. ${scanTargets.length} files scanned, ${patterns.length} patterns.`,
);
process.exit(0);
