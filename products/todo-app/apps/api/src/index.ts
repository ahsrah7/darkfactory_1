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

function shutdown(signal: string): void {
  console.log(`Received ${signal}, shutting down`);
  server.close(() => {
    void prisma.$disconnect().finally(() => process.exit(0));
  });
}

process.on("SIGTERM", () => shutdown("SIGTERM"));
process.on("SIGINT", () => shutdown("SIGINT"));
