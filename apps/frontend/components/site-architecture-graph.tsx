"use client";

import React, { useState, useRef, useEffect, useCallback } from "react";
import { useAudit } from "@/lib/audit-context";
import { ApiService } from "@/services/api";
import { formatNumber } from "@/lib/utils";
import { GitFork, Network, Search, Filter, ZoomIn, ZoomOut, Maximize, ArrowLeft, AlertTriangle } from "lucide-react";

/** A node as this component draws it, whichever view produced it. */
interface GraphNode {
  id: string;
  label: string;
  url: string;
  /** Pages this node stands for: 1 for a page, many for a section. */
  count: number;
  /** A section opens; a page opens the drawer. */
  isSection: boolean;
  depth?: number;
  status?: number;
  inboundCount?: number;
  outboundCount?: number;
  isBroken?: boolean;
  isOrphan?: boolean;
  isDeadEnd?: boolean;
  isHub?: boolean;
}

export function SiteArchitectureGraph() {
  const { activeSessionId, setSelectedPage } = useAudit();
  const [viewMode, setViewMode] = useState<"graph" | "tree">("graph");
  const [filterType, setFilterType] = useState<"all" | "broken" | "orphan" | "deadend" | "hub" | "deep">("all");
  const [searchQuery, setSearchQuery] = useState("");

  const [scale, setScale] = useState(1);
  const [position, setPosition] = useState({ x: 0, y: 0 });
  const [isDragging, setIsDragging] = useState(false);
  const dragStart = useRef({ x: 0, y: 0 });

  // Which section is open, or null for the whole site. The graph is fetched
  // rather than read from the audit payload: that payload carried a node per
  // page, which is ~5000 nodes and a few hundred thousand edges at the Full
  // Site Crawl preset -- more than a browser draws interactively.
  const [expanded, setExpanded] = useState<string | null>(null);
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [links, setLinks] = useState<Array<{ source: string; target: string }>>([]);
  const [isClustered, setIsClustered] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    if (!activeSessionId) return;
    let cancelled = false;

    ApiService.getArchitecture(activeSessionId, expanded ?? undefined)
      .then((graph) => {
        if (cancelled) return;
        const clustered = graph.clustered !== false;
        setIsClustered(clustered);
        setLinks(graph.links ?? []);
        setNodes(
          (graph.nodes ?? []).map((node: any): GraphNode =>
            clustered
              ? {
                  id: node.id,
                  label: node.label ?? node.id,
                  url: node.url ?? node.id,
                  count: node.count ?? 1,
                  // A section standing for a single page behaves as that page:
                  // expanding it would add a click and show the same thing.
                  isSection: !node.is_page,
                }
              : {
                  id: node.url,
                  label: node.url,
                  url: node.url,
                  count: 1,
                  isSection: false,
                  depth: node.depth,
                  status: node.status,
                  inboundCount: node.internal_links_count,
                  outboundCount: node.external_links_count,
                  isBroken: typeof node.status === "number" && node.status >= 400,
                },
          ),
        );
        setLoadError(null);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        // Said rather than swallowed: an empty canvas and a failed request look
        // the same, and only one of them is true.
        setLoadError(err instanceof Error ? err.message : String(err));
        setNodes([]);
        setLinks([]);
      });

    return () => {
      cancelled = true;
    };
  }, [activeSessionId, expanded]);

  const openNode = useCallback((node: GraphNode) => {
    if (node.isSection) {
      setExpanded(node.id);
      setScale(1);
      setPosition({ x: 0, y: 0 });
      return;
    }
    setSelectedPage({ url: node.url } as any);
  }, [setSelectedPage]);

  const filteredNodes = nodes.filter((node) => {
    const matchesSearch = node.url.toLowerCase().includes(searchQuery.toLowerCase())
      || node.label.toLowerCase().includes(searchQuery.toLowerCase());
    if (!matchesSearch) return false;
    // The page-level filters have nothing to say about a section: a section is
    // neither broken nor orphaned, and claiming otherwise would be a guess.
    if (isClustered) return true;
    if (filterType === "broken") return node.isBroken;
    if (filterType === "orphan") return node.isOrphan;
    if (filterType === "deadend") return node.isDeadEnd;
    if (filterType === "hub") return node.isHub;
    if (filterType === "deep") return (node.depth ?? 0) >= 3;
    return true;
  });

  const handleMouseDown = (e: React.MouseEvent) => {
    setIsDragging(true);
    dragStart.current = { x: e.clientX - position.x, y: e.clientY - position.y };
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (isDragging) {
      setPosition({
        x: e.clientX - dragStart.current.x,
        y: e.clientY - dragStart.current.y
      });
    }
  };

  const handleMouseUp = () => {
    setIsDragging(false);
  };

  const handleWheel = (e: React.WheelEvent) => {
    // Only zoom if ctrl/cmd is held or just always (we'll do always but smoothly)
    const zoomSensitivity = 0.002;
    const delta = -e.deltaY * zoomSensitivity;
    const newScale = Math.min(Math.max(0.1, scale * (1 + delta)), 5);
    setScale(newScale);
  };

  const resetZoom = () => {
    setScale(1);
    setPosition({ x: 0, y: 0 });
  };

  return (
    <div className="space-y-4 rounded-2xl border border-border/80 bg-card/80 p-6 shadow-glass backdrop-blur-md">
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-border/60 pb-4">
        <div>
          <div className="flex items-center gap-2">
            <Network className="h-5 w-5 text-primary" />
            <h3 className="text-lg font-bold tracking-tight text-foreground">Site Architecture Visualizer</h3>
          </div>
          <p className="text-xs text-muted-foreground">
            Explore link topology, crawl hierarchy, orphan nodes, and authority hubs
          </p>
        </div>

        {/* View mode toggle */}
        <div className="flex items-center gap-2 rounded-xl border border-border/60 bg-muted/30 p-1">
          <button
            onClick={() => setViewMode("graph")}
            className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition-all ${
              viewMode === "graph" ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
            }`}
          >
            <Network className="h-3.5 w-3.5" />
            Node Graph
          </button>
          <button
            onClick={() => setViewMode("tree")}
            className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition-all ${
              viewMode === "tree" ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
            }`}
          >
            <GitFork className="h-3.5 w-3.5" />
            Tree Hierarchy
          </button>
        </div>
      </div>

      {/* Filters & Search Bar */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[200px]">
          <Search className="absolute left-3 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
          <input
            type="text"
            placeholder="Search node URLs..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full rounded-xl border border-border/60 bg-background pl-9 pr-3 py-1.5 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
          />
        </div>

        {expanded && (
          <button
            onClick={() => setExpanded(null)}
            className="flex items-center gap-1.5 rounded-lg border border-border/60 px-2.5 py-1 text-xs font-medium text-muted-foreground hover:bg-muted"
          >
            <ArrowLeft className="h-3.5 w-3.5" /> All sections
          </button>
        )}

        <div className={`flex items-center gap-1.5 overflow-x-auto text-xs ${isClustered ? "hidden" : ""}`}>
          <Filter className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
          {(["all", "broken", "orphan", "deadend", "hub", "deep"] as const).map((type) => (
            <button
              key={type}
              onClick={() => setFilterType(type)}
              className={`capitalize rounded-lg px-2.5 py-1 text-xs font-medium transition-colors ${
                filterType === type
                  ? "bg-primary text-primary-foreground font-semibold"
                  : "bg-muted/40 text-muted-foreground hover:bg-muted"
              }`}
            >
              {type}
            </button>
          ))}
        </div>
      </div>

      {/* Graph Render Box */}
      <div className="relative h-[450px] w-full overflow-hidden rounded-xl border border-border/60 bg-gradient-to-b from-background/90 to-muted/20 p-0 group">
        {nodes.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center text-center text-muted-foreground p-4">
            {loadError ? (
              <>
                <AlertTriangle className="mb-2 h-8 w-8 opacity-40 text-rose-500" />
                <p className="text-xs">Could not load the site graph — {loadError}</p>
              </>
            ) : (
              <>
                <Network className="mb-2 h-8 w-8 opacity-40" />
                <p className="text-xs">No architecture node graph data available yet.</p>
              </>
            )}
          </div>
        ) : viewMode === "graph" ? (
          <>
            {/* Controls Overlay */}
            <div className="absolute top-4 right-4 z-10 flex flex-col gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
              <button onClick={() => setScale(s => Math.min(5, s * 1.2))} className="bg-card border border-border p-2 rounded hover:bg-muted">
                <ZoomIn className="h-4 w-4" />
              </button>
              <button onClick={() => setScale(s => Math.max(0.1, s / 1.2))} className="bg-card border border-border p-2 rounded hover:bg-muted">
                <ZoomOut className="h-4 w-4" />
              </button>
              <button onClick={resetZoom} className="bg-card border border-border p-2 rounded hover:bg-muted">
                <Maximize className="h-4 w-4" />
              </button>
            </div>

            {/* SVG Interactive Topology Canvas */}
            <svg
              className={`h-full w-full outline-none ${isDragging ? 'cursor-grabbing' : 'cursor-grab'}`}
              onMouseDown={handleMouseDown}
              onMouseMove={handleMouseMove}
              onMouseUp={handleMouseUp}
              onMouseLeave={handleMouseUp}
              onWheel={handleWheel}
            >
              <g transform={`translate(${position.x}, ${position.y}) scale(${scale})`}>
                {/* Draw Links */}
                {links.slice(0, 500).map((link, idx) => {
                  const srcNode = nodes.find((n) => n.id === link.source);
                  const tgtNode = nodes.find((n) => n.id === link.target);
                  if (!srcNode || !tgtNode) return null;

                  // Keep the same mock layout generation logic as before
                  const srcIdx = nodes.indexOf(srcNode);
                  const tgtIdx = nodes.indexOf(tgtNode);
                  const x1 = 50 + (srcIdx * 140) % 800;
                  const y1 = 50 + (srcIdx * 60) % 400;
                  const x2 = 50 + (tgtIdx * 140) % 800;
                  const y2 = 50 + (tgtIdx * 60) % 400;

                  return (
                    <line
                      key={idx}
                      x1={x1}
                      y1={y1}
                      x2={x2}
                      y2={y2}
                      stroke="currentColor"
                      strokeOpacity="0.15"
                      strokeWidth={1.5 / scale} // keep line width consistent regardless of zoom
                    />
                  );
                })}

                {/* Draw Nodes */}
                {filteredNodes.slice(0, 200).map((node) => {
                  const nodeIdx = nodes.indexOf(node);
                  const x = 50 + (nodeIdx * 140) % 800;
                  const y = 50 + (nodeIdx * 60) % 400;
                  let fill = "#3b82f6"; // default blue
                  if (node.isBroken) fill = "#ef4444"; // red
                  else if (node.isOrphan) fill = "#a855f7"; // purple
                  else if (node.isDeadEnd) fill = "#f97316"; // orange
                  else if (node.isHub) fill = "#10b981"; // green
                  else if (node.isSection) fill = "#6366f1"; // indigo: a section

                  // Sections are sized by the pages they stand for, so a 2,800
                  // page section does not look like a 6 page one. Square-rooted
                  // because area, not radius, is what the eye compares.
                  const radius = node.isSection
                    ? Math.min(34, 14 + Math.sqrt(node.count) * 1.4)
                    : 14;

                  return (
                    <g
                      key={node.id}
                      data-testid="graph-node"
                      transform={`translate(${x}, ${y})`}
                      className="cursor-pointer"
                      onClick={(e) => {
                        e.stopPropagation();
                        openNode(node);
                      }}
                    >
                      <circle r={radius / scale} fill={fill} fillOpacity="0.2" stroke={fill} strokeWidth={2 / scale} />
                      <circle r={6 / scale} fill={fill} />
                      <text
                        x={(radius + 6) / scale}
                        y={4 / scale}
                        fill="currentColor"
                        fontSize={10 / scale}
                        fontWeight="500"
                        className="opacity-90"
                      >
                        {node.label.length > 35 ? node.label.substring(0, 32) + "…" : node.label}
                      </text>
                      {node.isSection && (
                        <text
                          x={(radius + 6) / scale}
                          y={16 / scale}
                          fill="currentColor"
                          fontSize={9 / scale}
                          className="opacity-60"
                        >
                          {formatNumber(node.count)} pages
                        </text>
                      )}
                    </g>
                  );
                })}
              </g>
            </svg>
          </>
        ) : (
          /* Tree Hierarchy List */
          <div className="h-full overflow-y-auto space-y-2 p-4 text-xs">
            {filteredNodes.map((node) => (
              <div
                key={node.id}
                className="flex items-center justify-between rounded-lg border border-border/40 bg-card/60 px-3 py-2 hover:bg-muted/50 cursor-pointer"
                onClick={() => openNode(node)}
              >
                <div className="flex items-center gap-2 min-w-0">
                  <span
                    className={`h-2 w-2 rounded-full shrink-0 ${
                      node.isBroken
                        ? "bg-rose-500"
                        : node.isOrphan
                        ? "bg-purple-500"
                        : node.isDeadEnd
                        ? "bg-amber-500"
                        : node.isHub
                        ? "bg-emerald-500"
                        : "bg-blue-500"
                    }`}
                  />
                  <span className="font-mono truncate">{node.url}</span>
                </div>
                <div className="flex items-center gap-3 shrink-0 text-[10px] text-muted-foreground">
                  {node.isSection ? (
                    <span className="font-semibold text-foreground/70">
                      {formatNumber(node.count)} pages
                    </span>
                  ) : (
                    <>
                      <span className="font-semibold text-foreground/70">Depth {node.depth ?? 0}</span>
                      <span>In: {node.inboundCount ?? 0}</span>
                      <span>Out: {node.outboundCount ?? 0}</span>
                    </>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Legend Footer */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border/40 pt-3 text-[11px] text-muted-foreground">
        <div className="flex flex-wrap items-center gap-4">
          <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-blue-500" /> Normal Page</span>
          <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-emerald-500" /> Hub Page</span>
          <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-purple-500" /> Orphan Page</span>
          <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-amber-500" /> Dead End Page</span>
          <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-rose-500" /> Broken Page (404/500)</span>
        </div>
        <span>Total Nodes: {nodes.length}</span>
      </div>
    </div>
  );
}
