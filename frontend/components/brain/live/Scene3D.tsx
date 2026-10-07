"use client";

import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import { AdditiveBlending, BufferAttribute, BufferGeometry, Color, Group, MathUtils, Mesh, MeshBasicMaterial, PointsMaterial, Vector3 } from "three";
import type { BrainData } from "@/components/brain/brainData";
import type { V3 } from "@/lib/brain/layout";
import { useBrainPlayer } from "@/lib/brain/store";
import { prefersReducedMotion, readToken } from "@/lib/brain/tokens";
import type { Anchors, ProjectionBus } from "@/lib/brain/types";
import type { BrainRegion } from "@/lib/types";

const POOL = 6;
const TONE_TOKEN = { loss: "--loss", gain: "--gain", risk: "--risk", synapse: "--synapse" } as const;
/** How far the camera moves in when an item is focused (1 = overview). */
const FOCUS_ZOOM = 1.9;

interface Props {
  data: BrainData;
  maxDots: number;
  /** every projected item, keyed as in lib/brain/layout `key` */
  positions: Map<string, V3>;
  /** neuron positions by entity id, for pulse targets */
  neuronById: Map<string, V3>;
  bus: ProjectionBus;
  scope: React.RefObject<HTMLElement | null>;
  sway: boolean;
  /** brain-space half-extent to fit in the view (bigger when sources float outside the cortex) */
  fit: number;
  /** key of the item the camera should ease toward, or null for the overview */
  focusKey: string | null;
  /* Optional, additive (the Pitch page): every one defaults to the original behaviour. */
  /** ease toward a brain region's centre instead of an item */
  focusRegion?: BrainRegion | null;
  /** tint the dots of these regions with their region colour */
  tintRegions?: BrainRegion[];
  /** dim the dots outside the tinted regions */
  dimOthers?: boolean;
  /** half-swing of the gentle yaw sway, in radians (default 0.16) */
  swayAmp?: number;
  /** called about 30 times a second with the screen position of each region's centre and of the ghosts */
  onAnchors?: (a: Anchors) => void;
}

const REGION_ORDER: BrainRegion[] = ["ingest", "diagnose", "decide", "learn"];

function Rig({ data, maxDots, positions, neuronById, bus, scope, sway, fit, focusKey, focusRegion = null, tintRegions, dimOthers = false, swayAmp = 0.16, onAnchors }: Props) {
  const rig = useRef<Group>(null);
  const pool = useRef<(Mesh | null)[]>([]);
  const { camera, size } = useThree();
  const tmp = useMemo(() => new Vector3(), []);
  const colors = useRef(new Map<string, Color>());
  const reduce = useMemo(() => prefersReducedMotion(), []);
  const dotMaterial = useRef<PointsMaterial>(null);
  const dotPositions = useMemo(() => data.positions.slice(0, Math.min(maxDots, data.positions.length / 3) * 3), [data, maxDots]);

  const geom = useRef<BufferGeometry>(null);
  const tintKey = (tintRegions ?? []).join(",");
  // Dot colours: the fog colour everywhere (as before); optionally tinted by region, optionally dimmed outside the tint.
  useEffect(() => {
    const base = new Color(readToken("--fog", scope.current, "#8b97b0"));
    const tinted = new Set(tintKey ? tintKey.split(",") : []);
    const tint = new Map<string, Color>();
    for (const r of tinted) tint.set(r, new Color(readToken(`--region-${r}`, scope.current, "#3fc7e0")));
    const regionOf = data.regions;
    const dotColors = new Float32Array(dotPositions.length);
    for (let i = 0; i < dotColors.length / 3; i++) {
      const r = REGION_ORDER[regionOf[i]] ?? "ingest";
      const c = tint.get(r) ?? (dimOthers && tinted.size ? base.clone().multiplyScalar(0.45) : base);
      dotColors[i * 3] = c.r;
      dotColors[i * 3 + 1] = c.g;
      dotColors[i * 3 + 2] = c.b;
    }
    geom.current?.setAttribute("color", new BufferAttribute(dotColors, 3));
  }, [data, dotPositions, tintKey, dimOthers, scope]);
  const lastAnchors = useRef(0);
  const ghostCentre = useMemo(() => {
    const g = [...positions].filter(([k]) => k.startsWith("g:")).map(([, p]) => p);
    return g.length ? new Vector3(g.reduce((a, p) => a + p[0], 0) / g.length, g.reduce((a, p) => a + p[1], 0) / g.length, g.reduce((a, p) => a + p[2], 0) / g.length) : null;
  }, [positions]);

  useEffect(() => {
    const aspect = size.width / Math.max(1, size.height);
    const halfH = Math.max(fit * 0.62, (fit * 1.12) / Math.max(0.5, aspect));
    const dist = halfH / Math.tan((40 * Math.PI) / 360);
    camera.position.set(0, 0, dist);
    camera.lookAt(0, 0, 0);
    camera.updateProjectionMatrix();
  }, [camera, size, fit]);

  useFrame(({ clock }, dt) => {
    const g = rig.current;
    if (!g) return;
    const regionCentre = focusRegion ? (data.centroids as Record<string, Vector3>)[focusRegion] : undefined;
    const focus = regionCentre ? ([regionCentre.x, regionCentre.y, regionCentre.z] as V3) : focusKey ? positions.get(focusKey) : undefined;
    // Ease the whole brain so the focused item moves to the centre (about 500 ms; instant with reduced motion).
    const s = focus ? FOCUS_ZOOM : 1;
    const target = focus ? new Vector3(-focus[0] * s, -focus[1] * s, -focus[2] * s * 0.3) : new Vector3();
    const k = reduce ? 1 : 1 - Math.exp(-dt * 8);
    g.scale.setScalar(MathUtils.lerp(g.scale.x, s, k));
    g.position.lerp(target, k);
    g.rotation.y = sway && !reduce && !focus ? Math.sin(clock.elapsedTime * 0.16) * swayAmp : MathUtils.lerp(g.rotation.y, 0, k);
    g.updateMatrixWorld(true);

    const screen = new Map<string, { x: number; y: number }>();
    for (const [id, p] of positions) {
      tmp.set(p[0], p[1], p[2]).applyMatrix4(g.matrixWorld);
      const facing = tmp.z;
      tmp.project(camera);
      const x = (tmp.x * 0.5 + 0.5) * size.width;
      const y = (1 - (tmp.y * 0.5 + 0.5)) * size.height;
      screen.set(id, { x, y });
      const el = bus.els.get(id);
      if (el) {
        el.setAttribute("transform", `translate(${x.toFixed(1)} ${y.toFixed(1)})`);
        el.style.opacity = facing > -0.05 ? "1" : "0.35";
      }
    }
    if (onAnchors && clock.elapsedTime - lastAnchors.current > 1 / 30) {
      lastAnchors.current = clock.elapsedTime;
      const out: Partial<Anchors> = {};
      const proj = (v: Vector3) => {
        tmp.copy(v).applyMatrix4(g.matrixWorld).project(camera);
        return { x: (tmp.x * 0.5 + 0.5) * size.width, y: (1 - (tmp.y * 0.5 + 0.5)) * size.height };
      };
      for (const r of REGION_ORDER) out[r] = proj((data.centroids as Record<string, Vector3>)[r]);
      if (ghostCentre) out.ghost = proj(ghostCentre);
      onAnchors(out as Anchors);
    }
    for (const { el, a, b } of bus.lines.values()) {
      const pa = screen.get(a);
      const pb = screen.get(b);
      if (!pa || !pb) continue;
      el.setAttribute("x1", pa.x.toFixed(1));
      el.setAttribute("y1", pa.y.toFixed(1));
      el.setAttribute("x2", pb.x.toFixed(1));
      el.setAttribute("y2", pb.y.toFixed(1));
    }

    // Pulses: a bright dot travelling region to region, then to the first target neuron.
    const now = performance.now();
    const active = useBrainPlayer.getState().pulses.filter((p) => now - p.startedAt < p.duration).slice(-POOL);
    for (let i = 0; i < POOL; i++) {
      const mesh = pool.current[i];
      if (!mesh) continue;
      const pulse = active[i];
      if (!pulse) {
        mesh.visible = false;
        continue;
      }
      const pts: Vector3[] = [];
      for (const r of pulse.path as string[]) {
        const c = (data.centroids as Record<string, Vector3>)[r];
        if (c) pts.push(c);
      }
      for (const t of pulse.targets) {
        const pos = neuronById.get(t);
        if (pos) {
          pts.push(new Vector3(pos[0], pos[1], pos[2]));
          break;
        }
      }
      if (!pts.length) {
        mesh.visible = false;
        continue;
      }
      const t = reduce ? 1 : Math.min(1, (now - pulse.startedAt) / (pulse.duration * 0.7));
      const f = t * (pts.length - 1);
      const j = Math.min(pts.length - 2, Math.floor(f));
      mesh.position.lerpVectors(pts[Math.max(0, j)], pts[Math.min(pts.length - 1, j + 1)], pts.length === 1 ? 0 : f - j);
      const fade = 1 - Math.max(0, (now - pulse.startedAt) / pulse.duration - 0.7) / 0.3;
      let col = colors.current.get(pulse.tone);
      if (!col) {
        col = new Color(readToken(TONE_TOKEN[pulse.tone], scope.current, "#3fc7e0"));
        colors.current.set(pulse.tone, col);
      }
      (mesh.material as MeshBasicMaterial).color.copy(col);
      (mesh.material as MeshBasicMaterial).opacity = Math.max(0, fade) * (pulse.strong ? 1 : 0.8);
      mesh.scale.setScalar(pulse.strong ? 1.5 : 1);
      mesh.visible = true;
    }
  });

  return (
    <group ref={rig}>
      <points frustumCulled={false}>
        <bufferGeometry ref={geom}>
          <bufferAttribute attach="attributes-position" args={[dotPositions, 3]} />
        </bufferGeometry>
        <pointsMaterial ref={dotMaterial} vertexColors color="#ffffff" size={0.017} sizeAttenuation transparent opacity={0.8} depthWrite={false} blending={AdditiveBlending} />
      </points>
      {Array.from({ length: POOL }, (_, i) => (
        <mesh key={i} ref={(m) => void (pool.current[i] = m)} visible={false}>
          <sphereGeometry args={[0.035, 12, 12]} />
          <meshBasicMaterial transparent depthWrite={false} blending={AdditiveBlending} />
        </mesh>
      ))}
    </group>
  );
}

export default function Scene3D(props: Props & { paused: boolean }) {
  return (
    <Canvas dpr={[1, 2]} frameloop={props.paused ? "never" : "always"} camera={{ fov: 40, near: 0.1, far: 50, position: [0, 0, 3.4] }} gl={{ antialias: true, alpha: true, powerPreference: "low-power" }} style={{ position: "absolute", inset: 0 }}>
      <Rig {...props} />
    </Canvas>
  );
}
