"use client";

import { useEffect, useMemo, useRef } from "react";
import { useFrame, useThree, type ThreeEvent } from "@react-three/fiber";
import {
  AdditiveBlending,
  BufferGeometry,
  Color,
  Float32BufferAttribute,
  MathUtils,
  ShaderMaterial,
  Vector3,
} from "three";
import { brainPointsFragment, brainPointsVertex } from "./shaders/brainPoints";
import { ALERT_COLOR, REGIONS, REGION_META, type Region } from "./regions";
import { useBrainStore } from "./store";
import type { BrainData } from "./brainData";

interface Props {
  data: BrainData;
  onRegionClick: (region: Region) => void;
}

const IDLE = new Color("#a9c4ff");
const AMBER = new Color(REGION_META.learn.color);
const GREEN = new Color(REGION_META.decide.color);
const RED = new Color(ALERT_COLOR);
const regionColors = REGIONS.map((r) => new Color(REGION_META[r].color));

export default function BrainPoints({ data, onRegionClick }: Props) {
  const dpr = useThree((s) => s.viewport.dpr);
  const matRef = useRef<ShaderMaterial>(null);

  const geometry = useMemo(() => {
    const g = new BufferGeometry();
    g.setAttribute("position", new Float32BufferAttribute(data.positions, 3));
    g.setAttribute("aRegion", new Float32BufferAttribute(data.regions, 1));
    g.setAttribute("aRand", new Float32BufferAttribute(data.rands, 1));
    return g;
  }, [data]);
  useEffect(() => () => geometry.dispose(), [geometry]);

  const uniforms = useMemo(
    () => ({
      uTime: { value: 0 },
      uSize: { value: 20 },
      uPixelRatio: { value: 1 },
      uMouse: { value: new Vector3(99, 99, 99) },
      uMouseStrength: { value: 0 },
      uIdleColor: { value: IDLE.clone() },
      uTint: { value: 0.22 },
      uRegionColor: { value: regionColors.map((c) => c.clone()) },
      uRegionGlow: { value: [0, 0, 0, 0] },
      uWaveColor: { value: AMBER.clone() },
      uWaveRadius: { value: 0 },
      uWaveStrength: { value: 0 },
      uSpotPos: { value: new Vector3() },
      uSpotColor: { value: RED.clone() },
      uSpotStrength: { value: 0 },
    }),
    [],
  );

  const anim = useRef({ hovering: false, mouse: new Vector3() });
  const tmp = useMemo(() => new Vector3(), []);

  useFrame((state, dt) => {
    const u = matRef.current?.uniforms as typeof uniforms | undefined;
    if (!u) return;
    const now = performance.now() / 1000;
    const { brainState, stateStartedAt, hoveredRegion, selectedRegion } = useBrainStore.getState();
    const t = now - stateStartedAt;

    u.uTime.value = state.clock.elapsedTime;
    u.uPixelRatio.value = dpr;

    // Mouse push easing.
    u.uMouse.value.copy(anim.current.mouse);
    u.uMouseStrength.value = MathUtils.damp(
      u.uMouseStrength.value,
      anim.current.hovering ? 1 : 0,
      anim.current.hovering ? 8 : 3,
      dt,
    );

    // Target glow / colour per region for the current state.
    const glow = [0, 0, 0, 0];
    const color = regionColors.map((c) => c.clone());
    const { ingest, diagnose, decide, learn } = REGION_META;
    let waveStrength = 0;
    let waveRadius = 0;
    let spotStrength = 0;

    if (hoveredRegion) glow[REGION_META[hoveredRegion].index] = 0.95;
    if (selectedRegion) {
      const i = REGION_META[selectedRegion].index;
      glow[i] = Math.max(glow[i], 0.55);
    }

    switch (brainState) {
      case "ingesting":
        glow[ingest.index] = Math.max(glow[ingest.index], 0.55 + 0.2 * Math.sin(now * 3));
        break;
      case "anomaly": {
        const flashing = (t > 0 && t < 0.4) || (t > 0.7 && t < 1.1);
        if (flashing) {
          glow[diagnose.index] = 1.4;
          color[diagnose.index].copy(RED);
        }
        if (t > 1.2 && t < 2.5) {
          const k = MathUtils.smoothstep((t - 1.2) / 1.2, 0, 1);
          u.uSpotPos.value.lerpVectors(
            data.centroids.diagnose,
            data.centroids.decide,
            k,
          );
          u.uSpotColor.value.copy(RED).lerp(GREEN, k);
          spotStrength = 1 - MathUtils.smoothstep((t - 2.2) / 0.3, 0, 1);
        }
        if (t > 2.3 && t < 3.6) glow[decide.index] = Math.max(glow[decide.index], 0.9);
        break;
      }
      case "deciding":
        glow[decide.index] = Math.max(glow[decide.index], 0.85 + 0.04 * Math.sin(now * 2));
        break;
      case "learning": {
        const period = 2.6;
        const p = (t % period) / period;
        waveRadius = p * 1.8;
        waveStrength = Math.pow(1 - p, 1.2);
        glow[learn.index] = Math.max(glow[learn.index], 0.7);
        break;
      }
    }

    for (let i = 0; i < 4; i++) {
      const cur = u.uRegionGlow.value[i];
      u.uRegionGlow.value[i] = MathUtils.damp(cur, glow[i], glow[i] > cur ? 14 : 3.5, dt);
      u.uRegionColor.value[i].lerp(color[i], 1 - Math.exp(-dt * 16));
    }
    u.uWaveRadius.value = waveRadius;
    u.uWaveStrength.value = waveStrength;
    u.uSpotStrength.value = MathUtils.damp(u.uSpotStrength.value, spotStrength, 20, dt);
  });

  const regionOf = (e: ThreeEvent<PointerEvent | MouseEvent>): Region | null => {
    if (e.index == null) return null;
    return REGIONS[data.regions[e.index]] ?? null;
  };

  return (
    <points
      geometry={geometry}
      frustumCulled={false}
      onPointerMove={(e) => {
        const region = regionOf(e);
        const { hoveredRegion, setHoveredRegion } = useBrainStore.getState();
        if (region !== hoveredRegion) setHoveredRegion(region);
        e.object.worldToLocal(tmp.copy(e.point));
        anim.current.mouse.copy(tmp);
        anim.current.hovering = true;
        document.body.style.cursor = "pointer";
      }}
      onPointerOut={() => {
        anim.current.hovering = false;
        useBrainStore.getState().setHoveredRegion(null);
        document.body.style.cursor = "";
      }}
      onClick={(e) => {
        if (e.delta > 5) return; // it was a drag, not a click
        const region = regionOf(e);
        if (region) {
          e.stopPropagation();
          onRegionClick(region);
        }
      }}
    >
      <shaderMaterial
        ref={matRef}
        uniforms={uniforms}
        vertexShader={brainPointsVertex}
        fragmentShader={brainPointsFragment}
        transparent
        depthWrite={false}
        blending={AdditiveBlending}
      />
    </points>
  );
}

