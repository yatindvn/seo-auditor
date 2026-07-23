import { AuditResponse, HistoricalComparison } from "@seo-auditor/shared";

export interface CrawlSession {
  id: string;
  url: string;
  timestamp: string;
  auditResult: AuditResponse;
}

const sessionsStore: CrawlSession[] = [];

export class SessionModel {
  public static saveSession(session: CrawlSession): void {
    sessionsStore.unshift(session);
    if (sessionsStore.length > 50) {
      sessionsStore.pop();
    }
  }

  public static getSession(id: string): CrawlSession | undefined {
    return sessionsStore.find((s) => s.id === id);
  }

  public static getAllSessions(): CrawlSession[] {
    return [...sessionsStore];
  }

  public static getHistoryComparison(currentResult: AuditResponse): HistoricalComparison | null {
    if (sessionsStore.length < 2) return null;
    const previous = sessionsStore[1].auditResult;
    const currScore = currentResult.executive_summary.health_score.score;
    const prevScore = previous.executive_summary.health_score.score;

    const currentIssues = new Set(currentResult.recommendations.map((r) => r.code));
    const prevIssues = new Set(previous.recommendations.map((r) => r.code));

    const newIssues = Array.from(currentIssues).filter((code) => !prevIssues.has(code));
    const resolvedIssues = Array.from(prevIssues).filter((code) => !currentIssues.has(code));

    return {
      previousDate: previous.executive_summary.audit_date,
      currentDate: currentResult.executive_summary.audit_date,
      scoreChange: Math.round((currScore - prevScore) * 10) / 10,
      previousScore: prevScore,
      currentScore: currScore,
      newIssuesCount: newIssues.length,
      resolvedIssuesCount: resolvedIssues.length,
      newIssues,
      resolvedIssues,
      pagesCountDelta: currentResult.pages.length - previous.pages.length,
    };
  }
}
