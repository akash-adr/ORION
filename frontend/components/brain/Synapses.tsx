"use client";

import { useEffect, useMemo, useRef } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import {
  AdditiveBlending,
  BufferGeometry,
  Color,
  Float32BufferAttribute,
  type ShaderMaterial,
} from "three";
import { dotFragment, pulseVertex } from "./shaders/pulses";
import { ALERT_COLOR, REGION_META } from "./regions";
import { useBrainStore, type BrainState } from "./store";
import type { BrainData } from "./brainData";

const PAIRS = 600;
const PULSES = 160;
const MIN_LEN = 0.08;
const MAX_LEN = 0.4;

const stateColor: Record<BrainState, Color> = {
  idle: new Color("#9db8ff"),
  ingesting: new Color(REGION_META.ingest.color),
  anomaly: new Color(ALERT_COLOR),
  deciding: new Color(REGION_META.decide.color),
  learning: new Color(REGION_META.learn.color),
};

function rng(seed: number) {
  return () => {
    seed = (seed * 16807) % 2147483647;
    return (seed - 1) / 2147483646;
  };
}

export default function Synapses({ data }: { data: BrainData }) {
  const dpr = useThree((s) => s.viewport.dpr);

  const { lines, pulses } = useMemo(() => {
    const rand = rng(1234);
    const n = data.positions.length / 3;
    const segs: number[] = [];
    const p = data.positions;
    let guard = 0;
    while (segs.length / 6 < PAIRS && guard++ < PAIRS * 40) {
      const i = Math.floor(rand() * n);
      let best = -1;
      let bestD = Infinity;
      for (let k = 0; k < 40; k++) {
        const j = Math.floor(rand() * n);
        if (j === i) continue;
        const d = Math.hypot(
          p[i * 3] - p[j * 3],
          p[i * 3 + 1] - p[j * 3 + 1],
          p[i * 3 + 2] - p[j * 3 + 2],
        );
        if (d > MIN_LEN && d < bestD) {
          bestD = d;
          best = j;
        }
      }
      if (best < 0 || bestD > MAX_LEN) continue;
      segs.push(
        p[i * 3], p[i * 3 + 1], p[i * 3 + 2],
        p[best * 3], p[best * 3 + 1], p[best * 3 + 2],
      );
    }

    const lines = new BufferGeometry();
    lines.setAttribute("position", new Float32BufferAttribute(segs, 3));

    const count = segs.length / 6;
    const start: number[] = [];
    const end: number[] = [];
    const seed: number[] = [];
    for (let k = 0; k < PULSES; k++) {
      const s = Math.floor(rand() * count) * 6;
      start.push(segs[s], segs[s + 1], segs[s + 2]);
      end.push(segs[s + 3], segs[s + 4], segs[s + 5]);
      seed.push(rand());
    }
    const pulses = new BufferGeometry();
    pulses.setAttribute("position", new Float32BufferAttribute(start, 3));
    pulses.setAttribute("aStart", new Float32BufferAttribute(start, 3));
    pulses.setAttribute("aEnd", new Float32BufferAttribute(end, 3));
    pulses.setAttribute("aSeed", new Float32BufferAttribute(seed, 1));
    return { lines, pulses };
  }, [data]);

  useEffect(
    () => () => {
      lines.dispose();
      pulses.dispose();
    },
    [lines, pulses],
  );

  const uniforms = useMemo(
    () => ({
      uTime: { value: 0 },
      uSize: { value: 30 },
      uPixelRatio: { value: 1 },
      uColor: { value: new Color("#9db8ff") },
    }),
    [],
  );

  const matRef = useRef<ShaderMaterial>(null);
  useFrame((_, dt) => {
    const u = matRef.current?.uniforms as typeof uniforms | undefined;
    if (!u) return;
    const { brainState } = useBrainStore.getState();
    // Pulses travel faster while ingesting / anomalous.
    const speed = brainState === "ingesting" ? 2.4 : brainState === "anomaly" ? 1.8 : 1;
    u.uTime.value += dt * speed;
    u.uPixelRatio.value = dpr;
    u.uColor.value.lerp(stateColor[brainState], 1 - Math.exp(-dt * 4));
  });

  return (
    <group>
      <lineSegments geometry={lines} frustumCulled={false} raycast={() => null}>
        <lineBasicMaterial
          color="#6d8dff"
          transparent
          opacity={0.07}
          depthWrite={false}
          blending={AdditiveBlending}
        />
      </lineSegments>
      <points geometry={pulses} frustumCulled={false} raycast={() => null}>
        <shaderMaterial
          ref={matRef}
          uniforms={uniforms}
          vertexShader={pulseVertex}
          fragmentShader={dotFragment}
          transparent
          depthWrite={false}
          blending={AdditiveBlending}
        />
      </points>
    </group>
  );
}

