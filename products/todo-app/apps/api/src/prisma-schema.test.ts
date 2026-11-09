import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { createPrismaClient } from "./db.js";

const here = dirname(fileURLToPath(import.meta.url));
const schemaPath = resolve(here, "../../../prisma/schema.prisma");
const schema = readFileSync(schemaPath, "utf8");

describe("Prisma schema", () => {
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

  it("PR-2: the schema has one model, Todo", () => {
    const models = [...schema.matchAll(/^\s*model\s+(\w+)\s*\{/gm)].map(
      (match) => match[1],
    );
    expect(models).toEqual(["Todo"]);
  });

  it('PR-2: the Todo model maps to table "Todo"', () => {
    const todo = /model\s+Todo\s*\{([\s\S]*?)\n\}/.exec(schema);
    expect(todo).not.toBeNull();
    expect(todo?.[1]).toMatch(/@@map\("Todo"\)/);
  });

  it("PR-2: the Todo title is VARCHAR(200)", () => {
    const todo = /model\s+Todo\s*\{([\s\S]*?)\n\}/.exec(schema);
    expect(todo?.[1]).toMatch(/^\s*title\s+String\s+@db\.VarChar\(200\)\s*$/m);
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
