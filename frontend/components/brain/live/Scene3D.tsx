"use client";

import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import { AdditiveBlending, Color, Group, Mesh, MeshBasicMaterial, PointsMaterial, Vector3 } from "three";
import type { BrainData } from "@/components/brain/brainData";
import type { V3 } from "@/lib/brain/layout";
import { useBrainPlayer } from "@/lib/brain/store";
import { prefersReducedMotion, readToken } from "@/lib/brain/tokens";
import type { RefMap } from "./NeuronOverlay";

const POOL = 6;
const TONE_TOKEN = { loss: "--loss", gain: "--gain", risk: "--risk", synapse: "--synapse" } as const;

interface Props {
  data: BrainData;
  maxDots: number;
  positions: Map<string, V3>;
  refs: React.RefObject<RefMap>;
  /** capsule element, so tokens resolve inside the dark scope */
  scope: React.RefObject<HTMLElement | null>;
  sway: boolean;
}

function Rig({ data, maxDots, positions, refs, scope, sway }: Props) {
  const rig = useRef<Group>(null);
  const pool = useRef<(Mesh | null)[]>([]);
  const { camera, size } = useThree();
  const tmp = useMemo(() => new Vector3(), []);
  const colors = useRef(new Map<string, Color>());
  const reduce = useMemo(() => prefersReducedMotion(), []);

  const dotPositions = useMemo(() => data.positions.slice(0, Math.min(maxDots, data.positions.length / 3) * 3), [data, maxDots]);
  const dotMaterial = useRef<PointsMaterial>(null);
  useEffect(() => {
    dotMaterial.current?.color.set(readToken("--fog", scope.current, "#8b97b0"));
  }, [scope]);

  // Fit the brain (long axis spans [-1, 1]) to the panel for any aspect ratio.
  useEffect(() => {
    const aspect = size.width / Math.max(1, size.height);
    const halfH = Math.max(0.62, 1.12 / Math.max(0.5, aspect));
    const dist = halfH / Math.tan((40 * Math.PI) / 360);
    camera.position.set(0, 0, dist);
    camera.lookAt(0, 0, 0);
    camera.updateProjectionMatrix();
  }, [camera, size]);

  useFrame(({ clock }) => {
    const g = rig.current;
    if (!g) return;
    g.rotation.y = sway && !reduce ? Math.sin(clock.elapsedTime * 0.16) * 0.16 : 0;
    g.updateMatrixWorld(true);

    // Project every neuron to screen space and move its SVG group there.
    for (const [id, p] of positions) {
      const el = refs.current.get(id);
      if (!el) continue;
      tmp.set(p[0], p[1], p[2]).applyMatrix4(g.matrixWorld);
      const facing = tmp.z;
      tmp.project(camera);
      el.setAttribute("transform", `translate(${((tmp.x * 0.5 + 0.5) * size.width).toFixed(1)} ${((1 - (tmp.y * 0.5 + 0.5)) * size.height).toFixed(1)})`);
      el.style.opacity = facing > -0.05 ? "1" : "0.35";
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
        const pos = positions.get(t);
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
      const k = Math.min(pts.length - 2, Math.floor(f));
      const a = pts[Math.max(0, k)];
      const b = pts[Math.min(pts.length - 1, k + 1)];
      mesh.position.lerpVectors(a, b, pts.length === 1 ? 0 : f - k);
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
        <bufferGeometry>
          <bufferAttribute attach="attributes-position" args={[dotPositions, 3]} />
        </bufferGeometry>
        <pointsMaterial ref={dotMaterial} color="#8b97b0" size={0.017} sizeAttenuation transparent opacity={0.8} depthWrite={false} blending={AdditiveBlending} />
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
