"use client";

import React, { createContext, useContext, useState, useEffect } from "react";
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

  // Restore from sessionStorage on initial load
  useEffect(() => {
    try {
      const saved = sessionStorage.getItem(STORAGE_KEY);
      if (saved) {
        setAuditDataState(JSON.parse(saved));
      }
    } catch {
      // Ignore storage errors
    }
  }, []);

  // Connect to WebSocket Server for Live Streaming Events
  useEffect(() => {
    // Keep a ref to activeSessionId to use inside the WebSocket callback
    const activeSessionRef = { current: activeSessionId };
    activeSessionRef.current = activeSessionId;

    const ws = ApiService.createWebSocketClient((event: MessageEvent) => {
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
          setIsLoading(false);
          setLiveCrawlMetrics((prev) => (prev ? { ...prev, completed: true, progress: 100 } : null));
          if (activeSessionRef.current) {
            ApiService.getLatestAudit(activeSessionRef.current).then(data => {
              setAuditDataState(data);
              try { sessionStorage.setItem(STORAGE_KEY, JSON.stringify(data)); } catch {}
            }).catch(console.error);
          }
        } else if (evtType === WS_EVENTS.CRAWL_ERROR) {
          setIsLoading(false);
          setError(payload.error || "Crawl failed");
        }
      } catch {
        // Ignore JSON parse errors
      }
    });

    return () => {
      if (ws) ws.close();
    };
  }, [activeSessionId]);

  const startNewAudit = (sessionId: string) => {
    setActiveSessionId(sessionId);
    setAuditDataState(null);
    setIsLoading(true);
    setLiveCrawlMetrics(null);
    setActivityLog([]);
    setLivePageRows([]);
    setError(null);
    sessionStorage.removeItem(STORAGE_KEY);
  };

  const setAuditData = (data: AuditResponse | null) => {
    setAuditDataState(data);
    if (data) {
      try {
        sessionStorage.setItem(STORAGE_KEY, JSON.stringify(data));
      } catch {
        // Ignore storage quota errors
      }
    } else {
      sessionStorage.removeItem(STORAGE_KEY);
    }
  };

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
