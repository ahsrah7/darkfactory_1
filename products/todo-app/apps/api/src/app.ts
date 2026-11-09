import express, { type Express } from "express";

/** Builds the HTTP app. It does not touch the database. */
export function createApp(): Express {
  const app = express();
  app.disable("x-powered-by");

  app.get("/health", (_req, res) => {
    res.status(200).json({ status: "ok" });
  });

  return app;
}
