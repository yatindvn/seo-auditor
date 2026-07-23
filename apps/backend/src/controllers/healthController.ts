import { Request, Response } from "express";

export class HealthController {
  public static getHealth(_req: Request, res: Response) {
    res.status(200).json({ status: "ok", service: "seo-auditor-backend", timestamp: new Date().toISOString() });
  }
}
