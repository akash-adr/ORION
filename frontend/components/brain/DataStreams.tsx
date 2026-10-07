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

const NODES = [
  { label: "Meta Ads", pos: [-1.9, 1.15, 0.3] },
  { label: "Google Ads", pos: [-2.3, 0.2, -0.2] },
  { label: "Amazon Ads", pos: [-1.95, -0.8, 0.4] },
  { label: "TikTok Ads", pos: [-0.9, 1.5, -0.4] },
  { label: "Shopify Sales", pos: [-1.2, -1.4, 0.2] },
  { label: "Inventory / ERP", pos: [-0.1, -1.55, -0.3] },
] as const;
const PER_NODE = 140;
const BLUE = new Color(REGION_META.ingest.color);

function Node({ label, pos, index }: { label: string; pos: readonly number[]; index: number }) {
  const ref = useRef<Group>(null);
  const dot = useRef<Mesh>(null);
  const labelRef = useRef<HTMLDivElement>(null);
  useFrame(({ clock }) => {
    const t = clock.elapsedTime + index * 1.3;
    ref.current?.position.set(pos[0], pos[1] + Math.sin(t * 0.8) * 0.06, pos[2]);
    const active = useBrainStore.getState().brainState === "ingesting";
    dot.current?.scale.setScalar(MathUtils.damp(dot.current.scale.x, active ? 1.5 : 1, 6, 0.016));
    if (labelRef.current) labelRef.current.style.opacity = active ? "1" : "0.45";
  });
  return (
    <group ref={ref} position={[pos[0], pos[1], pos[2]]}>
      <mesh ref={dot}>
        <sphereGeometry args={[0.02, 16, 16]} />
        <meshBasicMaterial color={BLUE.clone().multiplyScalar(1.1)} toneMapped={false} />
      </mesh>
      <Html center zIndexRange={[5, 0]} style={{ pointerEvents: "none" }} position={[0, 0.16, 0]}>
        <div
          ref={labelRef}
          className="whitespace-nowrap rounded-full border border-blue-400/30 bg-blue-500/10 px-2.5 py-0.5 font-mono text-[10px] tracking-wide text-blue-200 backdrop-blur-sm transition-opacity duration-500"
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

const DataStreams = forwardRef<DataStreamsHandle>(function DataStreams(_, ref) {
  const dpr = useThree((s) => s.viewport.dpr);

  const geometry = useMemo(() => {
    const start: number[] = [];
    const jitter: number[] = [];
    const seed: number[] = [];
    let s = 99;
    const rnd = () => ((s = (s * 16807) % 2147483647) - 1) / 2147483646;
    NODES.forEach((n) => {
      for (let i = 0; i < PER_NODE; i++) {
        start.push(n.pos[0], n.pos[1], n.pos[2]);
        jitter.push((rnd() - 0.5) * 0.4, (rnd() - 0.5) * 0.4, (rnd() - 0.5) * 0.4);
        seed.push(rnd());
      }
    });
    const g = new BufferGeometry();
    g.setAttribute("position", new Float32BufferAttribute(start, 3));
    g.setAttribute("aStart", new Float32BufferAttribute(start, 3));
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
      uActive: { value: 0 },
      uTarget: { value: new Vector3(-0.5, 0, 0) },
      uColor: { value: BLUE.clone() },
    }),
    [],
  );

  useImperativeHandle(ref, () => ({ setTarget: (v) => uniforms.uTarget.value.copy(v) }), [uniforms]);

  const matRef = useRef<ShaderMaterial>(null);
  useFrame(({ clock }, dt) => {
    const u = matRef.current?.uniforms as typeof uniforms | undefined;
    if (!u) return;
    const active = useBrainStore.getState().brainState === "ingesting";
    u.uTime.value = clock.elapsedTime;
    u.uPixelRatio.value = dpr;
    u.uActive.value = MathUtils.damp(u.uActive.value, active ? 1 : 0, 3, dt);
  });

  return (
    <group>
      {NODES.map((n, i) => (
        <Node key={n.label} label={n.label} pos={n.pos} index={i} />
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

