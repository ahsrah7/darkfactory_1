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
  // Only checks that the factory returns a client and that $disconnect
  // resolves. Generation with no database is checked by `npm run db:check`.
  it("createPrismaClient returns a client whose $disconnect resolves", async () => {
    const client = createPrismaClient("postgresql://localhost:5432/todo_test");
    expect(client).toBeDefined();
    await expect(client.$disconnect()).resolves.toBeUndefined();
  });
});
