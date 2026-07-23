import { AuditRequestParams, AuditResponse, WS_EVENTS } from "@seo-auditor/shared";
import { CrawlEngine } from "../crawler/crawlEngine";
import { wsServer } from "../websocket/wsServer";
import { SessionModel } from "../models/sessionModel";

export class AuditService {
  public static async runAudit(params: AuditRequestParams): Promise<AuditResponse> {
    const startTime = Date.now();
    wsServer.broadcast(WS_EVENTS.CRAWL_START, { url: params.url, timestamp: startTime });

    const progressCallback = (done: number, total: number, currentUrl: string) => {
      const elapsedSec = Math.max(0.1, (Date.now() - startTime) / 1000);
      const speed = round(done / elapsedSec, 1);
      const remainingPages = Math.max(0, total - done);
      const eta = speed > 0 ? round(remainingPages / speed, 0) : 0;

      wsServer.broadcast(WS_EVENTS.CRAWL_PROGRESS, {
        stage: `Crawling page ${done} of ${total}`,
        progress: Math.min(100, Math.round((done / Math.max(total, 1)) * 100)),
        pages_crawled: done,
        current_url: currentUrl,
        current_depth: 1,
        queue_remaining: remainingPages,
        speed_pages_per_sec: speed,
        elapsed_seconds: round(elapsedSec, 1),
        eta_seconds: eta,
      });

      wsServer.emitPageCrawled({
        url: currentUrl,
        status: 200,
        depth: 1,
        response_time: round(elapsedSec * 100, 0),
        timestamp: new Date().toISOString(),
      });
    };

    try {
      const result = await CrawlEngine.execute(params);
      
      // Save session for historical tracking (Phase 8)
      SessionModel.saveSession({
        id: `session_${Date.now()}`,
        url: params.url,
        timestamp: new Date().toISOString(),
        auditResult: result,
      });

      wsServer.broadcast(WS_EVENTS.CRAWL_COMPLETE, { url: params.url, pages: result.pages.length, score: result.executive_summary.health_score.score });
      return result;
    } catch (error: any) {
      wsServer.broadcast(WS_EVENTS.CRAWL_ERROR, { url: params.url, error: error.message });
      throw error;
    }
  }
}

function round(val: number, decimals: number): number {
  const factor = Math.pow(10, decimals);
  return Math.round(val * factor) / factor;
}
