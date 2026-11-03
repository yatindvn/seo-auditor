import type { Metadata } from "next";

import { pageMetadata } from "@/lib/seo";

export const metadata: Metadata = pageMetadata("/content", "Content Explorer — SEO Auditor", "What the top 10 results for a topic look like: length, headings, schema and backlinks.");

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
