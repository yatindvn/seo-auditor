"use client";

import React from "react";
import { Duplicates } from "@/lib/types";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ExternalLink, Copy } from "lucide-react";

interface DuplicatesPanelProps {
  duplicates: Duplicates;
}

function DuplicateGroup({
  label,
  urls,
}: {
  label: string;
  urls: string[];
}) {
  return (
    <div className="rounded-xl border border-border/60 bg-muted/20 p-3">
      <div className="mb-2 flex items-start justify-between gap-2">
        <p
          className="text-xs font-medium text-foreground/80 line-clamp-2"
          title={label}
        >
          &ldquo;{label}&rdquo;
        </p>
        <span className="shrink-0 rounded-full bg-amber-500/10 px-2 py-0.5 text-[10px] font-bold text-amber-700 dark:text-amber-400">
          {urls.length} pages
        </span>
      </div>
      <div className="space-y-1">
        {urls.map((url, idx) => (
          <a
            key={idx}
            href={url}
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-1.5 font-mono text-[10px] text-primary hover:underline"
          >
            <ExternalLink className="h-2.5 w-2.5 shrink-0 opacity-70" />
            <span className="truncate">{url}</span>
          </a>
        ))}
      </div>
    </div>
  );
}

function DuplicateTabContent({
  data,
  emptyLabel,
}: {
  data: Record<string, string[]>;
  emptyLabel: string;
}) {
  const entries = Object.entries(data);
  if (entries.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-emerald-300 bg-emerald-50/40 dark:border-emerald-900/40 dark:bg-emerald-950/10 p-8 text-center">
        <Copy className="h-6 w-6 text-emerald-500 opacity-80 mb-2" />
        <p className="text-sm font-semibold text-emerald-700 dark:text-emerald-400">
          No {emptyLabel} duplicates found!
        </p>
      </div>
    );
  }

  return (
    <div className="max-h-80 space-y-2 overflow-y-auto pr-1">
      {entries.map(([key, urls], idx) => (
        <DuplicateGroup key={idx} label={key} urls={urls} />
      ))}
    </div>
  );
}

export function DuplicatesPanel({ duplicates }: DuplicatesPanelProps) {
  const tabs = [
    { key: "titles", label: "Titles", data: duplicates.duplicate_titles },
    { key: "descs", label: "Descriptions", data: duplicates.duplicate_meta_descriptions },
    { key: "h1", label: "H1", data: duplicates.duplicate_h1 },
    { key: "content", label: "Content", data: duplicates.duplicate_content },
    { key: "canonicals", label: "Canonicals", data: duplicates.duplicate_canonicals },
  ];

  return (
    <Tabs defaultValue="titles">
      <TabsList className="flex-wrap h-auto gap-1">
        {tabs.map((tab) => {
          const count = Object.keys(tab.data).length;
          return (
            <TabsTrigger key={tab.key} value={tab.key} className="text-xs">
              {tab.label}
              {count > 0 && (
                <span className="ml-1.5 rounded-full bg-amber-500/20 px-1.5 py-0 text-[10px] font-bold text-amber-700 dark:text-amber-400">
                  {count}
                </span>
              )}
            </TabsTrigger>
          );
        })}
      </TabsList>

      {tabs.map((tab) => (
        <TabsContent key={tab.key} value={tab.key} className="mt-3">
          <DuplicateTabContent data={tab.data} emptyLabel={tab.label.toLowerCase()} />
        </TabsContent>
      ))}
    </Tabs>
  );
}
