"use client";

import { usePathname, useRouter } from "next/navigation";

import { activeSuffix } from "@/components/platform/project-tabs";
import { useApi } from "@/lib/use-api";
import { Platform } from "@/services/platform";

export function ProjectSwitcher({ projectId }: { projectId: number }) {
  const router = useRouter();
  const pathname = usePathname() || "";
  const projects = useApi(() => Platform.listProjects(), []);
  const items = projects.data?.items ?? [];
  const current = items.find((p) => p.id === projectId);

  return (
    <label className="flex min-w-0 items-center gap-2">
      <span className="sr-only">Project</span>
      <select
        className="h-9 max-w-[16rem] truncate rounded-full border bg-card px-3 text-sm font-semibold tracking-tight"
        value={projectId}
        onChange={(e) => router.push(`/projects/${e.target.value}${activeSuffix(pathname, projectId)}`)}
      >
        {!current && <option value={projectId}>Project #{projectId}</option>}
        {items.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
      </select>
    </label>
  );
}
