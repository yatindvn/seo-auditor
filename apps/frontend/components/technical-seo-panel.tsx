"use client";

import React from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { FileCode2, Map } from "lucide-react";
import { ExecutiveSummary, PageItem } from "@/lib/types";

interface TechnicalSeoPanelProps {
  es: ExecutiveSummary;
  pages: PageItem[];
}

export function TechnicalSeoPanel({ es, pages }: TechnicalSeoPanelProps) {
  const robotsFound = es.robots_txt_found;
  const sitemaps = es.sitemaps_found || [];
  const sitemapUrls = es.sitemap_urls || [];
  
  const crawledUrls = new Set(pages.map(p => p.url));
  const sitemapUrlSet = new Set(sitemapUrls);
  
  let crawledInSitemap = 0;
  let missingFromSitemap = 0;
  let extraInSitemap = 0;
  
  crawledUrls.forEach(url => {
    if (sitemapUrlSet.has(url)) crawledInSitemap++;
    else missingFromSitemap++;
  });
  
  sitemapUrlSet.forEach(url => {
    if (!crawledUrls.has(url)) extraInSitemap++;
  });
  
  const coverage = sitemapUrls.length > 0 ? Math.round((crawledInSitemap / sitemapUrls.length) * 100) : 0;

  return (
    <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <FileCode2 className="h-4 w-4 text-muted-foreground" />
            Robots.txt Analysis
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            <div className="flex items-center justify-between border-b border-border/40 pb-2">
              <span className="text-sm font-medium">Status</span>
              <span className={`px-2 py-0.5 rounded text-xs font-semibold ${robotsFound ? 'bg-emerald-500/10 text-emerald-500' : 'bg-rose-500/10 text-rose-500'}`}>
                {robotsFound ? "Found" : "Missing"}
              </span>
            </div>
            {robotsFound && (
              <div className="rounded-lg bg-muted/40 p-3 max-h-48 overflow-y-auto">
                <pre className="text-[10px] font-mono text-muted-foreground whitespace-pre-wrap">
                  {es.robots_txt_content || "No content visible."}
                </pre>
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <Map className="h-4 w-4 text-muted-foreground" />
            Sitemap Analysis
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-3 text-sm">
            <div className="flex justify-between border-b border-border/40 pb-2">
              <span className="text-muted-foreground">Sitemaps Found</span>
              <span className="font-semibold">{sitemaps.length}</span>
            </div>
            <div className="flex justify-between border-b border-border/40 pb-2">
              <span className="text-muted-foreground">URLs in Sitemap</span>
              <span className="font-semibold">{sitemapUrls.length}</span>
            </div>
            <div className="flex justify-between border-b border-border/40 pb-2">
              <span className="text-muted-foreground">URLs Crawled (in Sitemap)</span>
              <span className="font-semibold">{crawledInSitemap}</span>
            </div>
            <div className="flex justify-between border-b border-border/40 pb-2">
              <span className="text-muted-foreground">Extra URLs (not crawled)</span>
              <span className="font-semibold text-amber-500">{extraInSitemap}</span>
            </div>
            <div className="flex justify-between border-b border-border/40 pb-2">
              <span className="text-muted-foreground">Missing URLs (crawled, not in sitemap)</span>
              <span className="font-semibold text-rose-500">{missingFromSitemap}</span>
            </div>
            <div className="flex justify-between pt-1">
              <span className="font-semibold">Coverage</span>
              <span className="font-bold text-primary">{coverage}%</span>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
