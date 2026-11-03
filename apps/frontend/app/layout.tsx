import type { Metadata } from "next";
import "./globals.css";
import { GlobalNav } from "@/components/platform/global-nav";
import { AuditProvider } from "@/lib/audit-context";
import { SHARE_IMAGE, SITE_NAME, SITE_URL } from "@/lib/seo";

const DESCRIPTION =
  "Crawl any website and get a complete technical, on-page, performance, accessibility, and security SEO audit with a prioritized health score.";

// Site-wide share tags. No canonical here: it would resolve to the homepage for
// every page. Each public page sets its own in its layout (lib/seo.ts).
export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: "SEO Auditor — Full-Site Technical SEO Analysis",
  description: DESCRIPTION,
  openGraph: { type: "website", siteName: SITE_NAME, title: "SEO Auditor", description: DESCRIPTION, images: [SHARE_IMAGE] },
  twitter: { card: "summary_large_image", title: "SEO Auditor", description: DESCRIPTION, images: [SHARE_IMAGE.url] },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>
        <AuditProvider>
          <GlobalNav />
          {children}
        </AuditProvider>
      </body>
    </html>
  );
}
