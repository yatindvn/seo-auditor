"use client";

import React, { createContext, useContext, useState, useEffect, useRef, useCallback } from "react";
import {
  AuditResponse,
  CrawlStatus,
  ActivityLogEvent,
  CrawlPage,
  PageItem,
  HistoricalComparison,
  WS_EVENTS,
} from "@seo-auditor/shared";
import { ApiService } from "@/services/api";

interface AuditContextType {
  auditData: AuditResponse | null;
  setAuditData: (data: AuditResponse | null) => void;
  isLoading: boolean;
  setIsLoading: (loading: boolean) => void;
  error: string | null;
  setError: (error: string | null) => void;

  activeSessionId: string | null;
  startNewAudit: (sessionId: string) => void;

  // A bounded window of page rows, for the panels that summarise across pages.
  // The audit payload no longer carries every row -- at 5000 pages that is tens
  // of megabytes -- so these panels read a sample and say so when there is more.
  pageSample: PageItem[];
  pageSampleTotal: number;
  isPageSampleComplete: boolean;

  // Real-time Live Crawl State
  liveCrawlMetrics: CrawlStatus | null;
  activityLog: ActivityLogEvent[];
  livePageRows: CrawlPage[];
  selectedPage: PageItem | null;
  setSelectedPage: (page: PageItem | null) => void;
  historyComparison: HistoricalComparison | null;
  setHistoryComparison: (history: HistoricalComparison | null) => void;
}

const AuditContext = createContext<AuditContextType | undefined>(undefined);
const STORAGE_KEY = "seo_auditor_latest_results";

// How many rows the cross-page panels load. They summarise rather than list, so
// they do not need every row; the table that does list them pages the server
// instead. Ordered by crawl depth so the sample is the top of the site rather
// than whichever pages happened to score worst.
const PAGE_SAMPLE_SIZE = 200;

interface PersistedState {
  sessionId: string | null;
  summary: AuditResponse | null;
}

function readPersisted(): PersistedState | null {
  try {
    const saved = sessionStorage.getItem(STORAGE_KEY);
    return saved ? (JSON.parse(saved) as PersistedState) : null;
  } catch {
    // Private mode, blocked site data, or malformed leftovers. The dashboard
    // works without persistence and must not fail because of it.
    return null;
  }
}

function writePersisted(state: PersistedState): void {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    // Quota or blocked storage: losing the restore is acceptable, crashing is not.
  }
}

function clearPersisted(): void {
  try {
    sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // As above.
  }
}

export function AuditProvider({ children }: { children: React.ReactNode }) {
  const [auditData, setAuditDataState] = useState<AuditResponse | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const [liveCrawlMetrics, setLiveCrawlMetrics] = useState<CrawlStatus | null>(null);
  const [activityLog, setActivityLog] = useState<ActivityLogEvent[]>([]);
  const [livePageRows, setLivePageRows] = useState<CrawlPage[]>([]);
  const [selectedPage, setSelectedPage] = useState<PageItem | null>(null);
  const [historyComparison, setHistoryComparison] = useState<HistoricalComparison | null>(null);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [pageSample, setPageSample] = useState<PageItem[]>([]);
  const [pageSampleTotal, setPageSampleTotal] = useState<number>(0);

  // Restore from sessionStorage on initial load. The session id is restored
  // with the summary because the panels fetch their own detail now: a summary
  // without its id leaves them with nothing to ask about.
  useEffect(() => {
    const saved = readPersisted();
    if (!saved) return;
    if (saved.summary) setAuditDataState(saved.summary);
    if (saved.sessionId) {
      activeSessionRef.current = saved.sessionId;
      setActiveSessionId(saved.sessionId);
    }
  }, []);

  // The socket must outlive any single audit. Reconnecting whenever
  // activeSessionId changed used to drop the connection at the worst possible
  // moment: startNewAudit() fires immediately after POST /api/audit, by which
  // point the backend is already broadcasting crawl:start. Events emitted
  // during the reconnect were lost, and closing a still-CONNECTING socket
  // logged "closed before the connection is established". The session id now
  // lives in a ref so the handler always reads the current value without the
  // subscription itself having to restart.
  const activeSessionRef = useRef<string | null>(null);
  const completedSessionRef = useRef<string | null>(null);

  useEffect(() => {
    activeSessionRef.current = activeSessionId;
  }, [activeSessionId]);

  const loadFinishedAudit = useCallback((sessionId: string) => {
    if (completedSessionRef.current === sessionId) return;
    completedSessionRef.current = sessionId;
    ApiService.getLatestAudit(sessionId)
      .then(data => {
        setAuditDataState(data);
        setIsLoading(false);
        writePersisted({ sessionId, summary: data });
      })
      .catch(err => {
        // Allow a later crawl:complete or poll to retry this session.
        completedSessionRef.current = null;
        console.error(err);
      });
  }, []);

  // Connect to WebSocket Server for Live Streaming Events
  useEffect(() => {
    let ws: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let closed = false;

    const handleMessage = (event: MessageEvent) => {
      try {
        const message = JSON.parse(event.data);
        const { event: evtType, payload } = message;

        // Ensure payload session_id matches the active session
        if (payload.session_id && payload.session_id !== activeSessionRef.current) {
          return;
        }

        if (evtType === WS_EVENTS.CRAWL_START) {
          setIsLoading(true);
          setActivityLog([]);
          setLivePageRows([]);
          setLiveCrawlMetrics({
            stage: "Crawl Initiated",
            progress: 5,
            pages_crawled: 0,
            current_url: payload.url,
            completed: false,
          });
        } else if (evtType === WS_EVENTS.CRAWL_PROGRESS) {
          setLiveCrawlMetrics(payload);
        } else if (evtType === WS_EVENTS.PAGE_CRAWLED) {
          setLivePageRows((prev) => [payload, ...prev.slice(0, 49)]);
        } else if (evtType === WS_EVENTS.ACTIVITY_NEW) {
          setActivityLog((prev) => [payload, ...prev.slice(0, 99)]);
        } else if (evtType === WS_EVENTS.CRAWL_COMPLETE) {
          setLiveCrawlMetrics((prev) => (prev ? { ...prev, completed: true, progress: 100 } : null));
          if (activeSessionRef.current) {
            loadFinishedAudit(activeSessionRef.current);
          } else {
            setIsLoading(false);
          }
        } else if (evtType === WS_EVENTS.CRAWL_ERROR) {
          setIsLoading(false);
          setError(payload.error || "Crawl failed");
        }
      } catch {
        // Ignore JSON parse errors
      }
    };

    const connect = () => {
      if (closed) return;
      ws = ApiService.createWebSocketClient(handleMessage);
      if (!ws) return;
      // A dropped socket would otherwise strand the UI mid-crawl with no way back.
      ws.onclose = () => {
        if (closed) return;
        reconnectTimer = setTimeout(connect, 2000);
      };
    };

    connect();

    return () => {
      closed = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (ws) {
        ws.onclose = null;
        ws.close();
      }
    };
  }, [loadFinishedAudit]);

  // crawl:complete is a single fire-and-forget broadcast: if it lands while the
  // socket is down, nothing else ever tells the UI the audit finished. Poll for
  // the finished result as a safety net whenever a session is in flight.
  useEffect(() => {
    if (!activeSessionId || !isLoading) return;
    const poll = setInterval(() => {
      ApiService.getLatestAudit(activeSessionId)
        .then(data => { if (data) loadFinishedAudit(activeSessionId); })
        .catch(() => { /* 404 until the audit finishes */ });
    }, 5000);
    return () => clearInterval(poll);
  }, [activeSessionId, isLoading, loadFinishedAudit]);

  const startNewAudit = (sessionId: string) => {
    // Set synchronously: the backend starts broadcasting within milliseconds of
    // POST /api/audit returning, well before the effect that syncs this ref runs.
    activeSessionRef.current = sessionId;
    completedSessionRef.current = null;
    setActiveSessionId(sessionId);
    setAuditDataState(null);
    setIsLoading(true);
    setLiveCrawlMetrics(null);
    setActivityLog([]);
    setLivePageRows([]);
    setError(null);
    setPageSample([]);
    setPageSampleTotal(0);
    clearPersisted();
  };

  const setAuditData = (data: AuditResponse | null) => {
    setAuditDataState(data);
    if (data) {
      writePersisted({ sessionId: activeSessionRef.current, summary: data });
    } else {
      clearPersisted();
    }
  };

  // Loaded once per finished audit, not per panel: eight panels summarise
  // across pages and would otherwise each fetch the same window.
  useEffect(() => {
    if (!activeSessionId || !auditData) {
      return;
    }
    let cancelled = false;
    ApiService.getPages(activeSessionId, { limit: PAGE_SAMPLE_SIZE, sort: "depth", order: "asc" })
      .then((page) => {
        if (cancelled) return;
        setPageSample(page.items as PageItem[]);
        setPageSampleTotal(page.total);
      })
      .catch(() => {
        if (cancelled) return;
        setPageSample([]);
        setPageSampleTotal(0);
      });
    return () => {
      cancelled = true;
    };
  }, [activeSessionId, auditData]);

  return (
    <AuditContext.Provider
      value={{
        auditData,
        setAuditData,
        isLoading,
        setIsLoading,
        error,
        setError,
        activeSessionId,
        pageSample,
        pageSampleTotal,
        isPageSampleComplete: pageSampleTotal <= pageSample.length,
        startNewAudit,
        liveCrawlMetrics,
        activityLog,
        livePageRows,
        selectedPage,
        setSelectedPage,
        historyComparison,
        setHistoryComparison,
      }}
    >
      {children}
    </AuditContext.Provider>
  );
}

export function useAudit() {
  const context = useContext(AuditContext);
  if (!context) {
    throw new Error("useAudit must be used within an AuditProvider");
  }
  return context;
}
