import { describe, expect, it } from "vitest";
import { ConfigError, DEFAULT_PORT, loadConfig } from "./config.js";

const VALID_URL = "postgresql://localhost:5432/todo_test";

describe("loadConfig", () => {
  // AC7: with DATABASE_URL unset, startup fails and names the setting only.
  it("AC7: throws a ConfigError that names DATABASE_URL when it is unset", () => {
    expect(() => loadConfig({})).toThrow(ConfigError);
    expect(() => loadConfig({})).toThrow(/DATABASE_URL/);
  });

  it("AC7: treats an empty DATABASE_URL as unset", () => {
    expect(() => loadConfig({ DATABASE_URL: "   " })).toThrow(
      /DATABASE_URL is not set/,
    );
  });

  it("AC7: a malformed DATABASE_URL error names the setting and does not echo the value", () => {
    const badValue = "not a url secretlike-value";
    let message = "";
    try {
      loadConfig({ DATABASE_URL: badValue });
    } catch (error) {
      message = error instanceof Error ? error.message : "";
    }
    expect(message).toContain("DATABASE_URL");
    expect(message).not.toContain(badValue);
  });

  it("AC7: rejects a non-PostgreSQL scheme without echoing the value", () => {
    const value = "mysql://localhost:3306/todo_test";
    let message = "";
    try {
      loadConfig({ DATABASE_URL: value });
    } catch (error) {
      message = error instanceof Error ? error.message : "";
    }
    expect(message).toContain("DATABASE_URL must start with postgresql://");
    expect(message).not.toContain("localhost");
  });

  it("accepts a postgresql:// URL and defaults the port to 4000", () => {
    const config = loadConfig({ DATABASE_URL: VALID_URL });
    expect(config.databaseUrl).toBe(VALID_URL);
    expect(config.port).toBe(DEFAULT_PORT);
    expect(DEFAULT_PORT).toBe(4000);
  });

  it("accepts postgres:// as well as postgresql://", () => {
    expect(
      loadConfig({ DATABASE_URL: "postgres://localhost:5432/todo_test" })
        .databaseUrl,
    ).toBe("postgres://localhost:5432/todo_test");
  });

  // AC5: the API listens on its configured port.
  it("AC5: reads PORT when it is a valid number", () => {
    expect(loadConfig({ DATABASE_URL: VALID_URL, PORT: "5050" }).port).toBe(
      5050,
    );
  });

  it.each(["abc", "0", "65536", "-1", "80.5"])(
    "rejects an invalid PORT (%s) and names PORT",
    (port) => {
      expect(() => loadConfig({ DATABASE_URL: VALID_URL, PORT: port })).toThrow(
        /PORT must be a whole number/,
      );
    },
  );
});
