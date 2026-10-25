"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { Menu, Plus, Search } from "lucide-react";

import { cn } from "@/lib/utils";

const LINKS = [
  { href: "/projects", label: "Projects" },
  { href: "/keywords", label: "Keywords Explorer" },
];

export function GlobalNav() {
  const pathname = usePathname() || "/";
  const [open, setOpen] = useState(false);
  const linkClass = (href: string) =>
    cn("rounded-full px-3 py-1.5 text-sm transition-colors hover:text-foreground",
       pathname.startsWith(href) ? "text-foreground font-medium" : "text-muted-foreground");

  return (
    <header className="sticky top-0 z-40 h-[52px] border-b bg-background/95 backdrop-blur">
      <nav className="mx-auto flex h-full max-w-7xl items-center gap-2 px-4 sm:px-6" aria-label="Main">
        <Link href="/projects" className="mr-2 flex items-center gap-2 font-semibold tracking-tight">
          <Search className="h-4 w-4 text-primary" aria-hidden /> SEO Auditor
        </Link>
        <div className="hidden items-center gap-1 md:flex">
          {LINKS.map((l) => (
            <Link key={l.href} href={l.href} className={linkClass(l.href)}
                  aria-current={pathname.startsWith(l.href) ? "page" : undefined}>{l.label}</Link>
          ))}
        </div>
        <div className="ml-auto flex items-center gap-2">
          <Link href="/" className="inline-flex h-9 items-center gap-1.5 rounded-full bg-primary px-4 text-sm font-medium text-primary-foreground active:scale-95">
            <Plus className="h-4 w-4" aria-hidden /> New audit
          </Link>
          <button type="button" className="inline-flex h-11 w-11 items-center justify-center rounded-full md:hidden"
                  aria-label="Menu" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
            <Menu className="h-5 w-5" />
          </button>
        </div>
      </nav>
      {open && (
        <div className="border-b bg-background px-4 py-2 md:hidden">
          {LINKS.map((l) => (
            <Link key={l.href} href={l.href} onClick={() => setOpen(false)}
                  className="block rounded-lg px-3 py-3 text-sm">{l.label}</Link>
          ))}
        </div>
      )}
    </header>
  );
}
