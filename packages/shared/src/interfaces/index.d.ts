import { AuditRequestParams, AuditResponse, CrawlStatus } from "../types";
export interface ICrawlService {
    startCrawl(params: AuditRequestParams): Promise<AuditResponse>;
    getCrawlStatus(jobId: string): CrawlStatus | null;
}
export interface IAiService {
    generateSuggestions(auditData: AuditResponse): Promise<string[]>;
}
export interface IExportService {
    exportCsv(auditData: AuditResponse): string;
    exportPdf(auditData: AuditResponse): Promise<Buffer>;
}
