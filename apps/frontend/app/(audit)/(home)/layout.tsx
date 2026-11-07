import type { Metadata } from "next";

import { pageMetadata } from "@/lib/seo";

export const metadata: Metadata = pageMetadata("/", "SEO Auditor — Full-Site Technical SEO Analysis",
  "Crawl any website and get a complete technical, on-page, performance, accessibility, and security SEO audit with a prioritized health score.");

export default function HomeLayout({ children }: { children: React.ReactNode }) {
  return children;
}
