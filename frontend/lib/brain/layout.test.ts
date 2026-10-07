import { describe, expect, it } from "vitest";
import { CLUSTER_ANCHORS, hash01, layoutNeurons, nodeRadius } from "./layout";
import snapshot from "../__samples__/brain-snapshot.json";

// A synthetic brain-shaped cloud: an ellipsoid shell, deterministic.
function cloud(n: number): Float32Array {
  const out = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) {
    const u = hash01(`u${i}`);
    const v = hash01(`v${i}`);
    const th = u * Math.PI * 2;
    const ph = Math.acos(2 * v - 1);
    out.set([Math.sin(ph) * Math.cos(th), Math.sin(ph) * Math.sin(th) * 0.55, Math.cos(ph) * 0.5], i * 3);
  }
  return out;
}

describe("brain layout", () => {
  const pts = cloud(3000);
  const nodes = snapshot.nodes as { entity_id: string; cluster: string }[];

  it("is deterministic", () => {
    const a = layoutNeurons(pts, nodes);
    const b = layoutNeurons(pts, [...nodes].reverse());
    expect([...a]).toEqual([...b]);
  });
  it("places every neuron on the visible side of the surface, apart from its neighbours", () => {
    const m = layoutNeurons(pts, nodes);
    expect(m.size).toBe(nodes.length);
    const list = [...m.values()];
    list.forEach((p) => expect(p[2]).toBeGreaterThan(0));
    for (let i = 0; i < list.length; i++)
      for (let j = i + 1; j < list.length; j++) expect(Math.hypot(list[i][0] - list[j][0], list[i][1] - list[j][1], list[i][2] - list[j][2])).toBeGreaterThan(0.08);
  });
  it("keeps each channel near its cluster anchor", () => {
    const m = layoutNeurons(pts, nodes);
    for (const n of nodes.filter((x) => x.cluster in CLUSTER_ANCHORS && x.cluster !== "catalog")) {
      const p = m.get(n.entity_id)!;
      const a = CLUSTER_ANCHORS[n.cluster];
      expect(Math.hypot(p[0] - a[0], p[1] - a[1])).toBeLessThan(0.6);
    }
  });
  it("sizes nodes by the square root of spend", () => {
    expect(nodeRadius(0, 100)).toBe(3);
    expect(nodeRadius(100, 100)).toBeCloseTo(9.5);
    expect(nodeRadius(25, 100)).toBeCloseTo(6.25);
  });
});
