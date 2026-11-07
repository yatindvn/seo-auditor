import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { GlobalNav } from "@/components/platform/global-nav";

let pathname = "/";
vi.mock("next/navigation", () => ({ usePathname: () => pathname }));

describe("GlobalNav", () => {
  it("has no New audit button on the homepage, which is the audit form itself", () => {
    pathname = "/";
    render(<GlobalNav />);
    expect(screen.queryByRole("link", { name: /new audit/i })).toBeNull();
  });

  it.each(["/projects", "/keywords", "/content", "/dashboard", "/projects/1/audits"])(
    "links to the audit form from %s", (path) => {
      pathname = path;
      render(<GlobalNav />);
      expect(screen.getByRole("link", { name: /new audit/i })).toHaveAttribute("href", "/");
    });
});
