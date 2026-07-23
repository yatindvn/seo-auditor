import { Request, Response, NextFunction } from "express";

export function errorHandler(err: any, _req: Request, res: Response, _next: NextFunction) {
  console.error("API Error:", err);
  const status = err.status || 500;
  const detail = err.message || "Internal Server Error";
  res.status(status).json({ detail });
}
