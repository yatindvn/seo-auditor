"use client";

import { AsyncState } from "@/components/platform/async-state";
import { GscAuditSection } from "@/components/platform/gsc-audit-section";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useApi } from "@/lib/use-api";
import { Platform } from "@/services/platform";

export function GscReportPanel({ auditId }: { auditId: number }) {
  const gsc = useApi(() => Platform.auditGsc(auditId), [auditId]);
  return (
    <Card>
      <CardHeader className="pb-3"><CardTitle className="text-base">Search Console</CardTitle></CardHeader>
      <CardContent><AsyncState state={gsc}>{(g) => <GscAuditSection data={g} />}</AsyncState></CardContent>
    </Card>
  );
}
