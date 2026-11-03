import type { Metadata } from "next";

import { pageMetadata } from "@/lib/seo";

export const metadata: Metadata = pageMetadata("/keywords", "Keywords Explorer — SEO Auditor", "Keyword ideas, search volume, difficulty and a traffic estimate for any seed keyword.");

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
