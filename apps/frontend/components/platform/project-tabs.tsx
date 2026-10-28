"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

export const TABS = [
  { suffix: "", label: "Overview" },
  { suffix: "/audits", label: "Site Audit" },
  { suffix: "/ranks", label: "Rank Tracker" },
  { suffix: "/gap", label: "Content Gap" },
  { suffix: "/rules", label: "Custom Rules" },
];

export function activeSuffix(pathname: string, projectId: number): string {
  const rest = pathname.replace(`/projects/${projectId}`, "");
  return TABS.slice(1).find((t) => rest.startsWith(t.suffix))?.suffix ?? "";
}

export function ProjectTabs({ projectId }: { projectId: number }) {
  const current = activeSuffix(usePathname() || "", projectId);
  return (
    <div className="-mx-1 flex gap-1 overflow-x-auto" role="navigation" aria-label="Project">
      {TABS.map((t) => {
        const active = t.suffix === current;
        return (
          <Link key={t.label} href={`/projects/${projectId}${t.suffix}`} aria-current={active ? "page" : undefined}
                className={cn("whitespace-nowrap rounded-full px-3 py-1.5 text-sm transition-colors",
                              active ? "bg-foreground text-background font-medium" : "text-muted-foreground hover:text-foreground")}>
            {t.label}
          </Link>
        );
      })}
    </div>
  );
}
