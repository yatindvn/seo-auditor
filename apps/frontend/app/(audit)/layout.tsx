import React from "react";

import { AuditProvider } from "@/lib/audit-context";

/** The pages that run and show a live audit share one AuditProvider: starting
 *  an audit on the homepage hands its state to the dashboard. Other pages
 *  (projects, keywords, content) don't load the audit code at all. */
export default function AuditLayout({ children }: { children: React.ReactNode }) {
  return <AuditProvider>{children}</AuditProvider>;
}
