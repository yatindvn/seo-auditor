"use client";

import React, { useState, useEffect } from "react";
import { useAudit } from "@/lib/audit-context";
import { X, CheckCircle2, AlertCircle, Info, ShieldAlert } from "lucide-react";

export function PageExplorerDrawer() {
  const { selectedPage, setSelectedPage } = useAudit();
  const [activeTab, setActiveTab] = useState<string>("overview");

  // Reset tab when new page is selected
  useEffect(() => {
    if (selectedPage) setActiveTab("overview");
  }, [selectedPage]);

  if (!selectedPage) return null;

  const p = selectedPage;

  // Pass/Fail logic
  const isStatusPass = p.status_code === 200;
  const isTimePass = (p.response_time_ms || 0) < 500;
  const isTitlePass = !!(p.title && p.title.length >= 30 && p.title.length <= 60);
  const isDescPass = !!(p.meta_description && p.meta_description.length >= 120 && p.meta_description.length <= 160);
  const isH1Pass = !!(p.h1 && p.h1.length > 0);
  const isAltPass = (p.missing_alt_count || 0) === 0;
  
  let securityScore = 0;
  if (p.url.startsWith("https")) securityScore++;
  if (p.security_headers?.["Strict-Transport-Security"]) securityScore++;
  if (p.security_headers?.["Content-Security-Policy"]) securityScore++;
  if (p.security_headers?.["X-Frame-Options"]) securityScore++;
  const isSecurityPass = securityScore >= 3;

  const BadgeIcon = ({ pass, warn = false }: { pass: boolean, warn?: boolean }) => {
    if (pass) return <CheckCircle2 className="h-4 w-4 text-emerald-500" />;
    if (warn) return <Info className="h-4 w-4 text-amber-500" />;
    return <AlertCircle className="h-4 w-4 text-rose-500" />;
  };

  const tabs = [
    "overview", "seo", "content", "images", "links", 
    "performance", "security", "accessibility", "headers", "structured data"
  ];

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-background/80 backdrop-blur-sm">
      <div className="w-full max-w-3xl bg-card border-l border-border/80 shadow-2xl p-6 overflow-y-auto space-y-6 animate-in slide-in-from-right-full duration-300">
        
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border/60 pb-4">
          <div className="min-w-0 pr-4 flex-1">
            <span className="text-[10px] uppercase font-bold tracking-wider text-muted-foreground flex items-center gap-2">
              Page Inspection Drawer
              {(p.critical_issues + p.warning_issues + p.info_issues) > 0 && <span className="bg-rose-500/10 text-rose-500 px-1.5 py-0.5 rounded text-[9px]">{p.critical_issues + p.warning_issues + p.info_issues} Issues</span>}
            </span>
            <h3 className="text-lg font-bold text-foreground truncate font-mono mt-1" title={p.url}>
              {p.url}
            </h3>
          </div>
          <button
            onClick={() => setSelectedPage(null)}
            className="rounded-lg p-2 text-muted-foreground hover:bg-muted/80 transition-colors"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Tab Navigation */}
        <div className="flex flex-wrap border-b border-border/60 text-xs font-semibold">
          {tabs.map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`pb-2 px-3 capitalize border-b-2 transition-all whitespace-nowrap ${
                activeTab === tab
                  ? "border-primary text-primary font-bold"
                  : "border-transparent text-muted-foreground hover:text-foreground hover:bg-muted/20"
              }`}
            >
              {tab}
            </button>
          ))}
        </div>

        {/* Tab Content Panels */}
        <div className="space-y-4 text-sm animate-in fade-in duration-300">
          
          {activeTab === "overview" && (
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
              <div className="rounded-xl border border-border/60 bg-muted/20 p-4">
                <span className="text-xs font-semibold text-muted-foreground flex items-center justify-between">
                  HTTP Status <BadgeIcon pass={isStatusPass} />
                </span>
                <p className={`text-xl font-bold mt-2 ${isStatusPass ? 'text-emerald-500' : 'text-rose-500'}`}>{p.status_code || "ERR"}</p>
              </div>
              <div className="rounded-xl border border-border/60 bg-muted/20 p-4">
                <span className="text-xs font-semibold text-muted-foreground flex items-center justify-between">
                  Response Time <BadgeIcon pass={isTimePass} />
                </span>
                <p className={`text-xl font-bold mt-2 ${isTimePass ? 'text-emerald-500' : 'text-amber-500'}`}>{p.response_time_ms}ms</p>
              </div>
              <div className="rounded-xl border border-border/60 bg-muted/20 p-4">
                <span className="text-xs font-semibold text-muted-foreground flex items-center justify-between">
                  Crawl Depth <BadgeIcon pass={true} />
                </span>
                <p className="text-xl font-bold mt-2">{p.depth}</p>
              </div>
              <div className="rounded-xl border border-border/60 bg-muted/20 p-4">
                <span className="text-xs font-semibold text-muted-foreground flex items-center justify-between">
                  Word Count <BadgeIcon pass={(p.word_count || 0) > 300} warn={(p.word_count || 0) > 0} />
                </span>
                <p className="text-xl font-bold mt-2">{p.word_count}</p>
              </div>
              <div className="rounded-xl border border-border/60 bg-muted/20 p-4">
                <span className="text-xs font-semibold text-muted-foreground flex items-center justify-between">
                  HTML Size <BadgeIcon pass={true} />
                </span>
                <p className="text-xl font-bold mt-2">{((p.html_size_bytes || 0)/1024).toFixed(1)} KB</p>
              </div>
            </div>
          )}

          {activeTab === "seo" && (
            <div className="space-y-4">
              <div className={`rounded-xl border p-4 ${isTitlePass ? 'border-border/60' : 'border-amber-500/30 bg-amber-500/5'}`}>
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-bold text-muted-foreground uppercase">Title Tag</span>
                  <BadgeIcon pass={isTitlePass} warn={(p.title?.length ?? 0) > 0} />
                </div>
                <p className="font-medium text-foreground">{p.title || "Missing Title"}</p>
                <p className="text-[10px] text-muted-foreground mt-2">Length: {p.title?.length || 0} chars (Optimal: 30-60)</p>
              </div>
              
              <div className={`rounded-xl border p-4 ${isDescPass ? 'border-border/60' : 'border-amber-500/30 bg-amber-500/5'}`}>
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-bold text-muted-foreground uppercase">Meta Description</span>
                  <BadgeIcon pass={isDescPass} warn={(p.meta_description?.length ?? 0) > 0} />
                </div>
                <p className="text-muted-foreground">{p.meta_description || "Missing Meta Description"}</p>
                <p className="text-[10px] text-muted-foreground mt-2">Length: {p.meta_description?.length || 0} chars (Optimal: 120-160)</p>
              </div>
              
              <div className="rounded-xl border border-border/60 p-4">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-bold text-muted-foreground uppercase">Canonical Tag</span>
                  <BadgeIcon pass={true} />
                </div>
                <p className="font-mono text-muted-foreground break-all">{p.canonical || "Self-referencing / None"}</p>
              </div>
            </div>
          )}

          {activeTab === "content" && (
            <div className="space-y-4">
              <div className={`rounded-xl border p-4 ${isH1Pass ? 'border-border/60' : 'border-rose-500/30 bg-rose-500/5'}`}>
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-bold text-muted-foreground uppercase">Primary H1</span>
                  <BadgeIcon pass={isH1Pass} />
                </div>
                <p className="font-medium text-foreground">{p.h1 || "No H1 Found"}</p>
              </div>
              
              <div className="grid grid-cols-2 gap-4">
                <div className="rounded-xl border border-border/60 p-4">
                  <span className="text-xs font-bold text-muted-foreground uppercase">H2 Count</span>
                  <p className="text-xl font-bold mt-2">{p.h2_count || 0}</p>
                </div>
                <div className="rounded-xl border border-border/60 p-4">
                  <span className="text-xs font-bold text-muted-foreground uppercase">H3 Count</span>
                  <p className="text-xl font-bold mt-2">{p.h3_count || 0}</p>
                </div>
              </div>
              
              {p.heading_hierarchy && p.heading_hierarchy.length > 0 && (
                <div className="rounded-xl border border-border/60 p-4 max-h-64 overflow-y-auto">
                  <span className="text-xs font-bold text-muted-foreground uppercase mb-4 block">Heading Structure</span>
                  <div className="space-y-1.5 font-mono text-[11px]">
                    {p.heading_hierarchy.map((h, i) => (
                      <div key={i} style={{ paddingLeft: `${(h.level - 1) * 12}px` }} className="truncate" title={h.text}>
                        <span className="text-muted-foreground mr-2">H{h.level}</span>
                        {h.text}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {activeTab === "images" && (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div className="rounded-xl border border-border/60 p-4">
                <span className="text-xs font-bold text-muted-foreground uppercase">Total Images</span>
                <p className="text-2xl font-bold mt-2">{p.images_count || 0}</p>
              </div>
              <div className={`rounded-xl border p-4 ${isAltPass ? 'border-border/60' : 'border-rose-500/30 bg-rose-500/5'}`}>
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold text-muted-foreground uppercase">Missing Alt Text</span>
                  <BadgeIcon pass={isAltPass} />
                </div>
                <p className={`text-2xl font-bold mt-2 ${isAltPass ? 'text-foreground' : 'text-rose-500'}`}>{p.missing_alt_count || 0}</p>
              </div>
            </div>
          )}

          {activeTab === "links" && (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div className="rounded-xl border border-border/60 p-4">
                <span className="text-xs font-bold text-muted-foreground uppercase block mb-2">Internal Links</span>
                <p className="text-3xl font-bold text-blue-500">{p.internal_links_count || 0}</p>
                <p className="text-[10px] text-muted-foreground mt-1">Links to other pages on this domain</p>
              </div>
              <div className="rounded-xl border border-border/60 p-4">
                <span className="text-xs font-bold text-muted-foreground uppercase block mb-2">External Links</span>
                <p className="text-3xl font-bold text-emerald-500">{p.external_links_count || 0}</p>
                <p className="text-[10px] text-muted-foreground mt-1">Links to outbound domains</p>
              </div>
            </div>
          )}

          {activeTab === "performance" && (
            <div className="space-y-4">
              <div className={`rounded-xl border p-4 ${isTimePass ? 'border-border/60 bg-emerald-500/5' : 'border-amber-500/30 bg-amber-500/5'}`}>
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-bold text-muted-foreground uppercase">Time to First Byte (approx)</span>
                  <BadgeIcon pass={isTimePass} />
                </div>
                <p className="text-2xl font-bold">{p.response_time_ms}ms</p>
              </div>
              <div className="rounded-xl border border-border/60 p-4">
                <span className="text-xs font-bold text-muted-foreground uppercase mb-2 block">Payload Size</span>
                <p className="text-2xl font-bold">{((p.html_size_bytes || 0)/1024).toFixed(2)} KB</p>
              </div>
            </div>
          )}

          {activeTab === "security" && (
            <div className="space-y-4">
              <div className="flex items-center justify-between p-4 rounded-xl border border-border/60 bg-muted/20">
                <span className="font-bold">Security Score</span>
                <span className={`px-2 py-1 rounded text-xs font-bold ${isSecurityPass ? 'bg-emerald-500/20 text-emerald-500' : 'bg-rose-500/20 text-rose-500'}`}>
                  {securityScore}/4
                </span>
              </div>
              
              <div className="rounded-xl border border-border/60 overflow-hidden">
                <table className="w-full text-left text-xs">
                  <tbody className="divide-y divide-border/60 font-mono">
                    <tr className="bg-muted/10">
                      <td className="p-3">HTTPS Enabled</td>
                      <td className="p-3 text-right"><BadgeIcon pass={p.url.startsWith("https")} /></td>
                    </tr>
                    <tr className="bg-muted/10">
                      <td className="p-3">Strict-Transport-Security</td>
                      <td className="p-3 text-right"><BadgeIcon pass={!!p.security_headers?.["Strict-Transport-Security"]} /></td>
                    </tr>
                    <tr className="bg-muted/10">
                      <td className="p-3">Content-Security-Policy</td>
                      <td className="p-3 text-right"><BadgeIcon pass={!!p.security_headers?.["Content-Security-Policy"]} /></td>
                    </tr>
                    <tr className="bg-muted/10">
                      <td className="p-3">X-Frame-Options</td>
                      <td className="p-3 text-right"><BadgeIcon pass={!!p.security_headers?.["X-Frame-Options"]} /></td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          )}
          
          {activeTab === "accessibility" && (
            <div className="space-y-4">
               <div className={`rounded-xl border p-4 ${isAltPass ? 'border-border/60 bg-emerald-500/5' : 'border-rose-500/30 bg-rose-500/5'}`}>
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-bold text-muted-foreground uppercase">Image Alt Attributes</span>
                  <BadgeIcon pass={isAltPass} />
                </div>
                <p className="text-sm">
                  {isAltPass 
                    ? "All images have alt text." 
                    : `${p.missing_alt_count} images are missing alt text.`}
                </p>
              </div>
            </div>
          )}

          {activeTab === "headers" && (
            <div className="rounded-xl border border-border/60 p-4">
              <span className="text-xs font-bold text-muted-foreground uppercase mb-4 block">Raw Security Headers</span>
              {p.security_headers && Object.keys(p.security_headers).length > 0 ? (
                <div className="space-y-2 font-mono text-[11px] bg-muted/30 p-3 rounded-lg overflow-x-auto">
                  {Object.entries(p.security_headers).map(([key, val]) => (
                    <div key={key} className="flex flex-col sm:flex-row sm:gap-4">
                      <span className="font-bold text-primary min-w-[200px]">{key}:</span>
                      <span className="text-muted-foreground break-all">{String(val)}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-muted-foreground italic text-sm">No security headers detected.</p>
              )}
            </div>
          )}

          {activeTab === "structured data" && (
            <div className="rounded-xl border border-border/60 p-4">
              <div className="flex items-center justify-between mb-4">
                <span className="text-xs font-bold text-muted-foreground uppercase">JSON-LD / Microdata</span>
                <BadgeIcon pass={(p.structured_data?.length || 0) > 0} warn={false} />
              </div>
              
              {p.structured_data && p.structured_data.length > 0 ? (
                <div className="space-y-4">
                  {p.structured_data.map((sd, i) => (
                    <div key={i} className="bg-muted/30 rounded-lg p-3">
                      <span className="inline-block bg-primary/20 text-primary px-2 py-0.5 rounded text-[10px] font-bold mb-2">
                        {sd.type}
                      </span>
                      <pre className="text-[10px] font-mono text-muted-foreground overflow-x-auto whitespace-pre-wrap max-h-48">
                        {sd.raw}
                      </pre>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-muted-foreground italic text-sm">No structured data found on this page.</p>
              )}
            </div>
          )}

        </div>
      </div>
    </div>
  );
}
