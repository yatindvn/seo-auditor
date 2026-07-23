import { AuditRequestParams, AuditResponse } from "@seo-auditor/shared";
import { runPythonCrawler } from "../utils/pythonRunner";

export class CrawlEngine {
  public static async execute(params: AuditRequestParams): Promise<AuditResponse> {
    return await runPythonCrawler(params);
  }
}
