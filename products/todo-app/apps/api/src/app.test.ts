import request from "supertest";
import { describe, expect, it } from "vitest";
import { createApp } from "./app.js";

describe("createApp", () => {
  // AC6: GET /health returns 2xx. The body is {"status":"ok"}.
  it("AC6: GET /health returns 200 with status ok", async () => {
    const response = await request(createApp()).get("/health");
    expect(response.status).toBe(200);
    expect(response.body).toEqual({ status: "ok" });
  });

  it("AC6: GET /health does not need a database", async () => {
    // createApp() takes no database handle, so this runs with DATABASE_URL unset.
    const response = await request(createApp()).get("/health");
    expect(response.status).toBe(200);
  });

  it("returns the Express default 404 for any other route", async () => {
    const response = await request(createApp()).get("/todos");
    expect(response.status).toBe(404);
  });

  it("does not advertise the Express version", async () => {
    const response = await request(createApp()).get("/health");
    expect(response.headers["x-powered-by"]).toBeUndefined();
  });
});
