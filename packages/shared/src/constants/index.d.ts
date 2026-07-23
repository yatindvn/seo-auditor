export declare const DEFAULT_CRAWL_CONFIG: {
    readonly MAX_PAGES: 15;
    readonly MAX_DEPTH: 2;
    readonly CONCURRENCY: 10;
    readonly TIMEOUT: 10;
};
export declare const SEVERITY_LEVELS: {
    readonly CRITICAL: "critical";
    readonly WARNING: "warning";
    readonly INFO: "info";
};
export declare const HTTP_STATUS_CODES: {
    readonly OK: 200;
    readonly BAD_REQUEST: 400;
    readonly NOT_FOUND: 404;
    readonly INTERNAL_SERVER_ERROR: 500;
};
export declare const WS_EVENTS: {
    readonly CONNECT: "connect";
    readonly DISCONNECT: "disconnect";
    readonly CRAWL_START: "crawl:start";
    readonly CRAWL_PROGRESS: "crawl:progress";
    readonly CRAWL_COMPLETE: "crawl:complete";
    readonly CRAWL_ERROR: "crawl:error";
};
