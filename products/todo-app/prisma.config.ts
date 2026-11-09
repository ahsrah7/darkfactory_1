// Prisma CLI configuration for the Todo app (see README "Database").
// The datasource URL comes from DATABASE_URL in the environment. This file does
// not load .env files: local runs pass them with `node --env-file=.env`.
import { defineConfig, env } from "prisma/config";

export default defineConfig({
  schema: "prisma/schema.prisma",
  migrations: {
    path: "migrations",
  },
  datasource: {
    url: env("DATABASE_URL"),
  },
});
