import type { Metadata } from "next";
import "./globals.css";
import { GlobalNav } from "@/components/platform/global-nav";
import { AuditProvider } from "@/lib/audit-context";
import { SHARE_IMAGE, SITE_DESCRIPTION, SITE_NAME, SITE_URL, jsonLd, structuredData } from "@/lib/seo";

// Site-wide share tags. No canonical here: it would resolve to the homepage for
// every page. Each public page sets its own in its layout (lib/seo.ts).
export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: "SEO Auditor — Full-Site Technical SEO Analysis",
  description: SITE_DESCRIPTION,
  openGraph: { type: "website", siteName: SITE_NAME, title: "SEO Auditor", description: SITE_DESCRIPTION, images: [SHARE_IMAGE] },
  twitter: { card: "summary_large_image", title: "SEO Auditor", description: SITE_DESCRIPTION, images: [SHARE_IMAGE.url] },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>
        <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: jsonLd(structuredData()) }} />
        <AuditProvider>
          <GlobalNav />
          {children}
        </AuditProvider>
      </body>
    </html>
  );
}
