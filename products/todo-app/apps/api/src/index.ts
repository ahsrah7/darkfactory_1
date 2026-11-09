import { createApp } from "./app.js";
import { ConfigError, loadConfig } from "./config.js";
import { createPrismaClient } from "./db.js";

function fail(message: string): never {
  console.error(message);
  process.exit(1);
}

let port: number;
let databaseUrl: string;
try {
  ({ port, databaseUrl } = loadConfig(process.env));
} catch (error) {
  if (error instanceof ConfigError) {
    fail(`Configuration error: ${error.message}`);
  }
  throw error;
}

const prisma = createPrismaClient(databaseUrl);
const server = createApp().listen(port, () => {
  console.log(`API listening on port ${port}`);
});

server.on("error", (error: NodeJS.ErrnoException) => {
  fail(`Cannot listen on port ${port}: ${error.code ?? error.message}`);
});

// Time allowed for in-flight requests and the database disconnect before the
// process is forced to exit.
const SHUTDOWN_TIMEOUT_MS = 5_000;

// Set on the first SIGTERM or SIGINT. A repeated signal must not start a second
// shutdown: it would add another timer and call server.close() again.
let shuttingDown = false;

function shutdown(signal: string): void {
  if (shuttingDown) {
    console.log(`Received ${signal} during shutdown, ignoring`);
    return;
  }
  shuttingDown = true;
  console.log(`Received ${signal}, shutting down`);
  setTimeout(() => {
    server.closeAllConnections?.();
    console.error(
      `Shutdown did not finish within ${SHUTDOWN_TIMEOUT_MS} ms, forcing exit.`,
    );
    process.exit(1);
  }, SHUTDOWN_TIMEOUT_MS);
  server.close(() => {
    void prisma.$disconnect().finally(() => process.exit(0));
  });
}

process.on("SIGTERM", () => shutdown("SIGTERM"));
process.on("SIGINT", () => shutdown("SIGINT"));
