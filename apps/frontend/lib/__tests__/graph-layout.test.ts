import { describe, expect, it } from "vitest";

import { nodePosition, viewBoxFor } from "@/lib/graph-layout";

describe("graph layout", () => {
  it("places nodes on the same grid as before", () => {
    expect(nodePosition(0)).toEqual({ x: 50, y: 50 });
    expect(nodePosition(2)).toEqual({ x: 330, y: 170 });
    expect(nodePosition(6)).toEqual({ x: 50 + (6 * 140) % 800, y: 50 + (6 * 60) % 400 });
  });

  it("frames only the drawn nodes, with room for labels", () => {
    // nodes at x 50..330, y 50..170; 40 padding, 160 on the right for labels
    expect(viewBoxFor([0, 1, 2])).toBe("10 -5 480 240");
  });

  it("never zooms past a minimum frame, and copes with no nodes", () => {
    expect(viewBoxFor([0])).toBe("-70 -65 360 240");
    expect(viewBoxFor([])).toBe("0 0 960 460");
  });
});
