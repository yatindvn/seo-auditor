import type { Metadata } from "next";
import React from "react";

import { ProjectSwitcher } from "@/components/platform/project-switcher";
import { ProjectTabs } from "@/components/platform/project-tabs";
import { PRIVATE_PAGE } from "@/lib/seo";

export const metadata: Metadata = PRIVATE_PAGE;

export default function ProjectLayout({ children, params }: { children: React.ReactNode; params: { id: string } }) {
  const projectId = Number(params.id);
  return (
    <div className="min-h-screen bg-background">
      <div className="sticky top-[52px] z-30 border-b bg-background/80 backdrop-blur">
        <div className="mx-auto flex max-w-7xl flex-col gap-2 px-4 py-3 sm:flex-row sm:items-center sm:gap-4 sm:px-6">
          <ProjectSwitcher projectId={projectId} />
          <ProjectTabs projectId={projectId} />
        </div>
      </div>
      <main className="mx-auto max-w-7xl space-y-6 px-4 py-6 sm:px-6 sm:py-8">{children}</main>
    </div>
  );
}
