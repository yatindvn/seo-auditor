import type { Metadata } from "next";

import { pageMetadata } from "@/lib/seo";

export const metadata: Metadata = pageMetadata("/projects", "Projects — SEO Auditor", "Every audited site, with its health score and audit history.");

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
