import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AsyncState } from "@/components/platform/async-state";
import { DeltaBadge } from "@/components/platform/delta-badge";
import { DryRunBanner } from "@/components/platform/dry-run-banner";
import { ApiError } from "@/services/platform";

const state = (over: Partial<{ data: any; error: Error | null; isLoading: boolean }>) => ({
  data: null, error: null, isLoading: false, reload: vi.fn(), ...over,
});

describe("AsyncState", () => {
  it("shows a skeleton while loading", () => {
    render(<AsyncState state={state({ isLoading: true })}>{() => "content"}</AsyncState>);
    expect(screen.getByTestId("async-loading")).toBeInTheDocument();
  });

  it("explains a 503 and retries", async () => {
    const s = state({ error: new ApiError(503, "central database unavailable") });
    render(<AsyncState state={s}>{() => "content"}</AsyncState>);
    expect(screen.getByRole("alert")).toHaveTextContent(/unavailable right now/i);
    await userEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(s.reload).toHaveBeenCalled();
  });

  it("shows the empty state with its action", () => {
    render(
      <AsyncState state={state({ data: [] })} isEmpty={(d: any[]) => d.length === 0}
                  emptyTitle="No projects yet" emptyAction={<a href="/">Run an audit</a>}>
        {() => "content"}
      </AsyncState>,
    );
    expect(screen.getByText("No projects yet")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Run an audit" })).toBeInTheDocument();
  });

  it("renders children with data", () => {
    render(<AsyncState state={state({ data: { n: 3 } })}>{(d: any) => `n=${d.n}`}</AsyncState>);
    expect(screen.getByText("n=3")).toBeInTheDocument();
  });
});

describe("DeltaBadge", () => {
  it("higher is better by default", () => {
    render(<DeltaBadge value={3} />);
    expect(screen.getByLabelText("improved by 3")).toHaveTextContent("▲3");
  });

  it("for ranks a lower number is an improvement", () => {
    render(<DeltaBadge value={-5} lowerIsBetter />);
    expect(screen.getByLabelText("improved by 5")).toHaveTextContent("▲5");
  });

  it("a worse rank points down", () => {
    render(<DeltaBadge value={5} lowerIsBetter />);
    expect(screen.getByLabelText("worse by 5")).toHaveTextContent("▼5");
  });

  it("renders nothing for no change or no data", () => {
    const { container } = render(<><DeltaBadge value={0} /><DeltaBadge value={null} /></>);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("DryRunBanner", () => {
  it("is visible only for dry-run data", () => {
    const { rerender } = render(<DryRunBanner show />);
    expect(screen.getByRole("note")).toHaveTextContent(/made up/i);
    rerender(<DryRunBanner show={false} />);
    expect(screen.queryByRole("note")).toBeNull();
  });
});
