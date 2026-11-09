export const DEFAULT_PORT = 4000;

export interface ApiConfig {
  readonly port: number;
  readonly databaseUrl: string;
}

/** A startup configuration problem. The message names the setting, never its value. */
export class ConfigError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ConfigError";
  }
}

const POSTGRES_PROTOCOLS = new Set(["postgres:", "postgresql:"]);

/**
 * Reads the API configuration from environment variables.
 *
 * DATABASE_URL is required even though /health does not use it. There is no
 * default database URL. PORT is optional and defaults to 4000.
 *
 * @throws {ConfigError} when DATABASE_URL is missing or malformed, or PORT is invalid.
 */
export function loadConfig(env: NodeJS.ProcessEnv = process.env): ApiConfig {
  return {
    port: parsePort(env["PORT"]),
    databaseUrl: parseDatabaseUrl(env["DATABASE_URL"]),
  };
}

function parsePort(raw: string | undefined): number {
  if (raw === undefined || raw.trim() === "") {
    return DEFAULT_PORT;
  }
  const trimmed = raw.trim();
  const port = Number(trimmed);
  if (!/^\d+$/.test(trimmed) || port < 1 || port > 65535) {
    throw new ConfigError(
      `PORT must be a whole number from 1 to 65535 (got "${trimmed}").`,
    );
  }
  return port;
}

function parseDatabaseUrl(raw: string | undefined): string {
  if (raw === undefined || raw.trim() === "") {
    throw new ConfigError(
      "DATABASE_URL is not set. Set it in the environment, or in a local .env file read with --env-file. See .env.example.",
    );
  }
  let parsed: URL;
  try {
    parsed = new URL(raw);
  } catch {
    throw new ConfigError(
      "DATABASE_URL is not a valid URL. Check it against .env.example. The value is not shown.",
    );
  }
  if (!POSTGRES_PROTOCOLS.has(parsed.protocol)) {
    throw new ConfigError(
      "DATABASE_URL must start with postgresql://. The value is not shown.",
    );
  }
  return raw;
}
