import { Request, Response, NextFunction } from "express";
import { validateAuditRequest, sanitizeUrl } from "@seo-auditor/shared";
import { AuditService } from "../services/auditService";
import { SessionModel } from "../models/sessionModel";

let latestAuditResult: any = null;

export class AuditController {
  public static async runAudit(req: Request, res: Response, next: NextFunction) {
    try {
      const validation = validateAuditRequest(req.body);
      if (!validation.valid || !validation.data) {
        return res.status(400).json({ detail: validation.error || "Invalid audit parameters" });
      }

      const params = {
        ...validation.data,
        url: sanitizeUrl(validation.data.url),
      };

      const result = await AuditService.runAudit(params);
      latestAuditResult = result;
      return res.status(200).json(result);
    } catch (error) {
      return next(error);
    }
  }

  public static getPages(_req: Request, res: Response) {
    if (!latestAuditResult) {
      return res.status(404).json({ detail: "No audit session found" });
    }
    return res.status(200).json(latestAuditResult.pages || []);
  }

  public static getIssues(_req: Request, res: Response) {
    if (!latestAuditResult) {
      return res.status(404).json({ detail: "No audit session found" });
    }
    return res.status(200).json(latestAuditResult.recommendations || []);
  }

  public static getArchitecture(_req: Request, res: Response) {
    if (!latestAuditResult) {
      return res.status(404).json({ detail: "No audit session found" });
    }
    return res.status(200).json(latestAuditResult.architecture || { nodes: [], links: [] });
  }

  public static getHistory(_req: Request, res: Response) {
    const sessions = SessionModel.getAllSessions();
    const comparison = latestAuditResult ? SessionModel.getHistoryComparison(latestAuditResult) : null;
    return res.status(200).json({ sessions, comparison });
  }

  public static getPageById(req: Request, res: Response) {
    if (!latestAuditResult) {
      return res.status(404).json({ detail: "No audit session found" });
    }
    const targetUrl = decodeURIComponent(req.params.id || "");
    const page = latestAuditResult.pages.find((p: any) => p.url === targetUrl || p.url.includes(targetUrl));
    if (!page) {
      return res.status(404).json({ detail: "Page not found" });
    }
    return res.status(200).json(page);
  }

  public static getInternalLinks(_req: Request, res: Response) {
    if (!latestAuditResult) {
      return res.status(404).json({ detail: "No audit session found" });
    }
    return res.status(200).json({
      site_wide_analysis: latestAuditResult.site_wide_analysis,
      broken_links: latestAuditResult.broken_links,
    });
  }
}
