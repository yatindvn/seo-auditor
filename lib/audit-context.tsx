"use client";

import React, { createContext, useContext, useState, useEffect } from "react";
import { AuditResponse } from "./types";

interface AuditContextType {
  auditData: AuditResponse | null;
  setAuditData: (data: AuditResponse | null) => void;
  isLoading: boolean;
  setIsLoading: (loading: boolean) => void;
  error: string | null;
  setError: (error: string | null) => void;
}

const AuditContext = createContext<AuditContextType | undefined>(undefined);

const STORAGE_KEY = "seo_auditor_latest_results";

export function AuditProvider({ children }: { children: React.ReactNode }) {
  const [auditData, setAuditDataState] = useState<AuditResponse | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

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
