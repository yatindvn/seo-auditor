"use client";

import { useEffect } from "react";

/** /dashboard?session=<id> opens that saved audit. Read from window.location
 *  rather than useSearchParams, which would force a Suspense boundary onto the
 *  whole dashboard page in a static build. */
export function useSessionParam(activeSessionId: string | null, startNewAudit: (id: string) => void) {
  useEffect(() => {
    const session = new URLSearchParams(window.location.search).get("session");
    if (session && session !== activeSessionId) startNewAudit(session);
    // Only on mount: later session changes come from the app itself.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}
