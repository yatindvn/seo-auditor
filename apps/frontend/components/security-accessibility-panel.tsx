"use client";

import React from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ShieldCheck, UserCircle } from "lucide-react";
import { PageItem } from "@/lib/types";

interface SecurityAccessibilityPanelProps {
  pages: PageItem[];
}

export function SecurityAccessibilityPanel({ pages }: SecurityAccessibilityPanelProps) {
  let httpsCount = 0;
  let hstsCount = 0;
  let cspCount = 0;
  let frameOptionsCount = 0;
  
  let totalMissingAlt = 0;

  pages.forEach(p => {
    if (p.url.startsWith("https")) httpsCount++;
    if (p.security_headers) {
      if (p.security_headers["Strict-Transport-Security"]) hstsCount++;
      if (p.security_headers["Content-Security-Policy"]) cspCount++;
      if (p.security_headers["X-Frame-Options"]) frameOptionsCount++;
    }
    totalMissingAlt += (p.missing_alt_count || 0);
  });

  const total = pages.length || 1;
  const securityScore = Math.round(((httpsCount + hstsCount + cspCount + frameOptionsCount) / (total * 4)) * 100);

  return (
    <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <ShieldCheck className="h-4 w-4 text-muted-foreground" />
            Security Headers
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-between mb-4 pb-4 border-b border-border/40">
            <div>
              <p className="text-xs text-muted-foreground">Estimated Security Score</p>
              <p className="text-2xl font-bold">{securityScore}/100</p>
            </div>
            <div className={`h-12 w-12 rounded-full flex items-center justify-center text-lg font-bold border-4 ${securityScore > 80 ? 'border-emerald-500 text-emerald-500' : securityScore > 50 ? 'border-amber-500 text-amber-500' : 'border-rose-500 text-rose-500'}`}>
              {securityScore > 80 ? 'A' : securityScore > 50 ? 'C' : 'F'}
            </div>
          </div>
          <div className="space-y-3 text-sm">
            <div className="flex justify-between">
              <span className="text-muted-foreground">HTTPS Active</span>
              <span className="font-semibold">{httpsCount} / {pages.length}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Strict-Transport-Security</span>
              <span className="font-semibold">{hstsCount} / {pages.length}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Content-Security-Policy</span>
              <span className="font-semibold">{cspCount} / {pages.length}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">X-Frame-Options</span>
              <span className="font-semibold">{frameOptionsCount} / {pages.length}</span>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <UserCircle className="h-4 w-4 text-muted-foreground" />
            Accessibility Metrics
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-4 text-sm mt-4">
            <div className="p-4 rounded-xl border border-border/40 bg-muted/20 text-center">
              <p className="text-xs text-muted-foreground mb-1 uppercase tracking-wider">Total Missing Image Alt Tags</p>
              <p className={`text-3xl font-bold ${totalMissingAlt > 0 ? 'text-amber-500' : 'text-emerald-500'}`}>
                {totalMissingAlt}
              </p>
            </div>
            <p className="text-xs text-muted-foreground text-center">
              Accessibility checks are performed during markup extraction. Currently focusing on WCAG image alt attributes. Additional ARIA checks can be enabled in Crawler Settings.
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
