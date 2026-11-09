import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { createPrismaClient } from "./db.js";

const here = dirname(fileURLToPath(import.meta.url));
const schemaPath = resolve(here, "../../../prisma/schema.prisma");
const schema = readFileSync(schemaPath, "utf8");

describe("Prisma schema (PR-1: empty)", () => {
  // AC11: the datasource provider is postgresql.
  it("AC11: the datasource provider is postgresql", () => {
    const datasource = /datasource\s+\w+\s*\{([^}]*)\}/.exec(schema);
    expect(datasource).not.toBeNull();
    expect(datasource?.[1]).toMatch(/provider\s*=\s*"postgresql"/);
  });

  it("AC11: the datasource block does not set a URL (it lives in prisma.config.ts)", () => {
    const datasource = /datasource\s+\w+\s*\{([^}]*)\}/.exec(schema);
    expect(datasource?.[1]).not.toMatch(/\burl\s*=/);
  });

  it("AC11: the PR-1 schema has no models", () => {
    expect(schema).not.toMatch(/^\s*model\s+\w+/m);
  });
});

describe("createPrismaClient", () => {
  // AC11: the client can be built with no database reachable. It opens no
  // connection until a query runs, and PR-1 runs none.
  it("AC11: builds a client and disconnects without connecting to a database", async () => {
    const client = createPrismaClient("postgresql://localhost:5432/todo_test");
    expect(client).toBeDefined();
    await expect(client.$disconnect()).resolves.toBeUndefined();
  });
});
