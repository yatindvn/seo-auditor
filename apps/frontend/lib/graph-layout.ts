/** Where the architecture graph draws node `index`: a simple wrapping grid. */
export function nodePosition(index: number): { x: number; y: number } {
  return { x: 50 + (index * 140) % 800, y: 50 + (index * 60) % 400 };
}

const PAD = { left: 40, right: 160, top: 40, bottom: 50 };   // right: room for labels
const MIN = { width: 360, height: 240 };                       // never zoom in further

/** The SVG viewBox framing the drawn nodes, so the graph fills its card at any
 *  width. A frame smaller than MIN grows evenly around its centre. */
export function viewBoxFor(indices: number[]): string {
  if (indices.length === 0) return "0 0 960 460";
  const points = indices.map(nodePosition);
  let x = Math.min(...points.map((p) => p.x)) - PAD.left;
  let y = Math.min(...points.map((p) => p.y)) - PAD.top;
  let width = Math.max(...points.map((p) => p.x)) + PAD.right - x;
  let height = Math.max(...points.map((p) => p.y)) + PAD.bottom - y;
  if (width < MIN.width) { x -= (MIN.width - width) / 2; width = MIN.width; }
  if (height < MIN.height) { y -= (MIN.height - height) / 2; height = MIN.height; }
  return `${x} ${y} ${width} ${height}`;
}
