import type { Metadata } from "next";
import "./globals.css";
import { AuditProvider } from "@/lib/audit-context";

export const metadata: Metadata = {
  title: "SEO Auditor — Full-Site Technical SEO Analysis",
  description:
    "Crawl any website and get a complete technical, on-page, performance, accessibility, and security SEO audit with a prioritized health score.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>
        <AuditProvider>{children}</AuditProvider>
      </body>
    </html>
  );
}
