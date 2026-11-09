import { PrismaPg } from "@prisma/adapter-pg";
import { PrismaClient } from "./generated/prisma/client.js";

/**
 * Creates the Prisma client with the PostgreSQL driver adapter.
 *
 * Constructing the client does not open a connection. Connections are made on
 * the first query, which PR-1 never runs.
 */
export function createPrismaClient(databaseUrl: string): PrismaClient {
  const adapter = new PrismaPg({ connectionString: databaseUrl });
  return new PrismaClient({ adapter });
}
