export const DEFAULT_CRAWL_CONFIG = {
    MAX_PAGES: 15,
    MAX_DEPTH: 2,
    CONCURRENCY: 10,
    TIMEOUT: 10,
};
export const SEVERITY_LEVELS = {
    CRITICAL: "critical",
    WARNING: "warning",
    INFO: "info",
};
export const HTTP_STATUS_CODES = {
    OK: 200,
    BAD_REQUEST: 400,
    NOT_FOUND: 404,
    INTERNAL_SERVER_ERROR: 500,
};
export const WS_EVENTS = {
    CONNECT: "connect",
    DISCONNECT: "disconnect",
    CRAWL_START: "crawl:start",
    CRAWL_PROGRESS: "crawl:progress",
    CRAWL_COMPLETE: "crawl:complete",
    CRAWL_ERROR: "crawl:error",
};
