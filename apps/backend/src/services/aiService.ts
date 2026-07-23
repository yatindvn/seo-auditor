import { AuditResponse } from "@seo-auditor/shared";

export class AiService {
  public static async generateSuggestions(auditData: AuditResponse): Promise<string[]> {
    const suggestions: string[] = [];
    const health = auditData.executive_summary.health_score;

    if (health.critical_issues > 0) {
      suggestions.push(`Fix ${health.critical_issues} critical SEO errors to improve performance score.`);
    }
    if (auditData.executive_summary.broken_links > 0) {
      suggestions.push(`Repair ${auditData.executive_summary.broken_links} broken links detected across pages.`);
    }
    if (auditData.executive_summary.duplicate_titles > 0) {
      suggestions.push(`Unique meta titles needed for ${auditData.executive_summary.duplicate_titles} pages.`);
    }

    return suggestions;
  }
}
