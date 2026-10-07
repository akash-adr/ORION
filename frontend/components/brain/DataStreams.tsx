"use client";

import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import { Html } from "@react-three/drei";
import {
  AdditiveBlending,
  BufferGeometry,
  Color,
  Float32BufferAttribute,
  MathUtils,
  Mesh,
  Vector3,
  type Group,
  type ShaderMaterial,
} from "three";
import { dotFragment, streamVertex } from "./shaders/pulses";
import { REGION_META } from "./regions";
import { useBrainStore } from "./store";

/**
 * Data-source nodes sit on an arc around the brain's back (INGEST) side.
 * Angles are degrees around the brain centre (180 = directly behind/left).
 * `angle` is the open (dashboard) layout; `heroAngle` splits the nodes above and below
 * the brain so they stay clear of the hero copy on the left.
 */
const NODES = [
  { label: "Meta Ads", angle: 108, heroAngle: 75, z: 0.3 },
  { label: "TikTok Ads", angle: 136, heroAngle: 105, z: -0.4 },
  { label: "Google Ads", angle: 164, heroAngle: 135, z: -0.2 },
  { label: "Amazon Ads", angle: 196, heroAngle: 225, z: 0.4 },
  { label: "Shopify Sales", angle: 224, heroAngle: 255, z: 0.2 },
  { label: "Inventory / ERP", angle: 252, heroAngle: 285, z: -0.3 },
] as const;
const PER_NODE = 160;
const IDLE_FLOW = 0; // streams are hidden outside the ingestion stage
const INGEST_FLOW = 1; // full intensity while brainState is "ingesting"
const BLUE = new Color(REGION_META.ingest.color);

// Arc radii (brain-local units) when there is room; shrunk to fit the viewport otherwise.
const ARC_RX = 1.9;
const ARC_RY = 1.35;
const ARC_MIN = 1.1; // never closer than this to the brain centre
const EDGE_MARGIN = 0.18; // world units kept clear at the screen edge
const LABEL_PAD = 0.22; // extra headroom above a dot for its label
const HERO_TEXT_FRAC = 0.4; // share of the viewport width (left side) taken by the hero copy
const HERO_SHIFT = 1.0; // brain x-offset (world units) at which the hero layout is fully applied

function Node({ label, index, positions }: { label: string; index: number; positions: Vector3[] }) {
  const ref = useRef<Group>(null);
  const dot = useRef<Mesh>(null);
  const labelRef = useRef<HTMLDivElement>(null);
  useFrame(({ clock }, dt) => {
    const p = positions[index];
    ref.current?.position.set(p.x, p.y + Math.sin(clock.elapsedTime * 0.8 + index * 1.3) * 0.04, p.z);
    const active = useBrainStore.getState().brainState === "ingesting";
    dot.current?.scale.setScalar(MathUtils.damp(dot.current.scale.x, active ? 1.5 : 1, 6, dt));
    if (labelRef.current) labelRef.current.style.opacity = active ? "1" : "0.45";
  });
  return (
    <group ref={ref} position={positions[index].toArray()}>
      <mesh ref={dot}>
        <sphereGeometry args={[0.02, 16, 16]} />
        <meshBasicMaterial color={BLUE.clone().multiplyScalar(1.1)} toneMapped={false} />
      </mesh>
      <Html center zIndexRange={[5, 0]} style={{ pointerEvents: "none" }} position={[0, 0.13, 0]}>
        <div
          ref={labelRef}
          className="whitespace-nowrap rounded-full border border-blue-400/30 bg-blue-500/10 px-2.5 py-0.5 text-xs text-blue-200 backdrop-blur-sm transition-opacity duration-500"
        >
          {label}
        </div>
      </Html>
    </group>
  );
}

export interface DataStreamsHandle {
  /** Where streams should converge (in this component's local space). */
  setTarget: (v: Vector3) => void;
}

function arcPoint(angleDeg: number, rx: number, ry: number, z: number, out: Vector3) {
  const a = (angleDeg * Math.PI) / 180;
  return out.set(Math.cos(a) * rx, Math.sin(a) * ry, z);
}

const DataStreams = forwardRef<DataStreamsHandle>(function DataStreams(_, ref) {
  const dpr = useThree((s) => s.viewport.dpr);
  const group = useRef<Group>(null);

  // Current node positions (local to this group), eased toward the viewport-fitted arc.
  const positions = useMemo(() => NODES.map((n) => arcPoint(n.angle, ARC_RX, ARC_RY, n.z, new Vector3())), []);
  const tmp = useMemo(() => ({ world: new Vector3(), scale: new Vector3(), target: new Vector3() }), []);

  const geometry = useMemo(() => {
    const node: number[] = [];
    const jitter: number[] = [];
    const seed: number[] = [];
    let s = 99;
    const rnd = () => ((s = (s * 16807) % 2147483647) - 1) / 2147483646;
    NODES.forEach((_, i) => {
      for (let k = 0; k < PER_NODE; k++) {
        node.push(i);
        jitter.push((rnd() - 0.5) * 0.4, (rnd() - 0.5) * 0.4, (rnd() - 0.5) * 0.4);
        seed.push(rnd());
      }
    });
    const g = new BufferGeometry();
    g.setAttribute("position", new Float32BufferAttribute(new Array(node.length * 3).fill(0), 3));
    g.setAttribute("aStart", new Float32BufferAttribute(new Array(node.length * 3).fill(0), 3));
    g.userData.node = node; // source index per particle
    g.setAttribute("aJitter", new Float32BufferAttribute(jitter, 3));
    g.setAttribute("aSeed", new Float32BufferAttribute(seed, 1));
    return g;
  }, []);
  useEffect(() => () => geometry.dispose(), [geometry]);

  const uniforms = useMemo(
    () => ({
      uTime: { value: 0 },
      uSize: { value: 26 },
      uPixelRatio: { value: 1 },
      uActive: { value: IDLE_FLOW },
      uTarget: { value: new Vector3(-0.5, 0, 0) },
      uColor: { value: BLUE.clone() },
    }),
    [],
  );

  useImperativeHandle(ref, () => ({ setTarget: (v) => uniforms.uTarget.value.copy(v) }), [uniforms]);

  // Copy each particle's source-node position into its aStart attribute.
  const writeStarts = () => {
    const attr = geometry.getAttribute("aStart") as Float32BufferAttribute;
    const node = geometry.userData.node as number[];
    for (let k = 0; k < node.length; k++) {
      const p = positions[node[k]];
      attr.setXYZ(k, p.x, p.y, p.z);
    }
    attr.needsUpdate = true;
  };

  const matRef = useRef<ShaderMaterial>(null);
  useFrame((state, dt) => {
    const u = matRef.current?.uniforms as typeof uniforms | undefined;
    const g = group.current;
    if (!u || !g) return;
    const active = useBrainStore.getState().brainState === "ingesting";
    u.uTime.value = state.clock.elapsedTime;
    u.uPixelRatio.value = dpr;
    u.uActive.value = MathUtils.damp(u.uActive.value, active ? INGEST_FLOW : IDLE_FLOW, 3, dt);

    // Fit the arc inside the visible area. Skip while zoomed into a region so nodes don't jump.
    if (useBrainStore.getState().selectedRegion) return writeStarts();
    g.getWorldPosition(tmp.world);
    g.getWorldScale(tmp.scale);
    const s = tmp.scale.x || 1;
    const vp = state.viewport.getCurrentViewport(state.camera, tmp.world);
    // In the hero the brain is shifted right and the copy fills the left; keep nodes off the copy.
    const heroAmount = MathUtils.clamp(tmp.world.x / HERO_SHIFT, 0, 1);
    const leftEdge = state.camera.position.x - vp.width / 2 + vp.width * HERO_TEXT_FRAC * heroAmount;
    const left = (tmp.world.x - leftEdge - EDGE_MARGIN) / s;
    const up = (vp.height / 2 - tmp.world.y - EDGE_MARGIN - LABEL_PAD) / s;
    const down = (tmp.world.y + vp.height / 2 - EDGE_MARGIN) / s;
    const rx = Math.max(ARC_MIN, Math.min(ARC_RX, left));
    const ry = Math.max(ARC_MIN * 0.8, Math.min(ARC_RY, up, down));
    NODES.forEach((n, i) => {
      arcPoint(MathUtils.lerp(n.angle, n.heroAngle, heroAmount), rx, ry, n.z, tmp.target);
      positions[i].lerp(tmp.target, 1 - Math.exp(-dt * 6));
    });
    writeStarts();
  });

  return (
    <group ref={group}>
      {NODES.map((n, i) => (
        <Node key={n.label} label={n.label} index={i} positions={positions} />
      ))}
      <points geometry={geometry} frustumCulled={false} raycast={() => null}>
        <shaderMaterial
          ref={matRef}
          uniforms={uniforms}
          vertexShader={streamVertex}
          fragmentShader={dotFragment}
          transparent
          depthWrite={false}
          blending={AdditiveBlending}
        />
      </points>
    </group>
  );
});

export default DataStreams;
