"use client";

import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { CameraControls } from "@react-three/drei";
import { Bloom, EffectComposer } from "@react-three/postprocessing";
import CameraControlsImpl from "camera-controls";
import { Euler, MathUtils, Vector3, type Group, type RaycasterParameters } from "three";
import type { MotionValue } from "framer-motion";
import BrainPoints from "./BrainPoints";
import Synapses from "./Synapses";
import DataStreams, { type DataStreamsHandle } from "./DataStreams";
import { loadBrainData, type BrainData } from "./brainData";
import { BACKGROUND, type Region } from "./regions";
import { useBrainStore } from "./store";

export interface BrainSceneProps {
  onRegionSelect?: (region: Region) => void;
  /** Canvas background colour (defaults to the original near-black). */
  background?: string;
  /** 0 = hero, 1 = dashboard. Drives brain scale / position. */
  scrollProgress?: MotionValue<number>;
}

const HOME = { pos: new Vector3(0, 0.2, 5), target: new Vector3(0, 0, 0) };
const BASE_ROT = new Euler(0.32, -0.4, 0);
const SWAY = 0.38;

function BrainRig({
  data,
  scrollProgress,
  onRegionSelect,
  controls,
}: BrainSceneProps & { data: BrainData; controls: React.RefObject<CameraControlsImpl | null> }) {
  const rig = useRef<Group>(null);
  const sway = useRef<Group>(null);
  const streams = useRef<DataStreamsHandle>(null);
  const swayAmount = useRef(1);
  const tmp = useMemo(() => new Vector3(), []);

  useFrame(({ clock, size }, dt) => {
    const p = scrollProgress?.get() ?? 0;
    const e = MathUtils.smoothstep(p, 0, 1);
    const aspect = size.width / size.height;
    const heroX = aspect > 1.1 ? Math.min(1.7, (aspect - 1.1) * 1.5) : 0;
    const selected = useBrainStore.getState().selectedRegion !== null;

    if (rig.current) {
      const s = MathUtils.lerp(1.3, 0.62, e);
      rig.current.scale.setScalar(MathUtils.damp(rig.current.scale.x, s, 6, dt));
      rig.current.position.x = MathUtils.damp(rig.current.position.x, heroX * (1 - e), 6, dt);
    }
    if (sway.current) {
      const t = clock.elapsedTime;
      // Hold still while a region is selected so the camera target stays valid.
      swayAmount.current = MathUtils.damp(swayAmount.current, selected ? 0 : 1, 3, dt);
      sway.current.rotation.set(
        BASE_ROT.x + Math.sin(t * 0.21) * 0.04 * swayAmount.current,
        BASE_ROT.y + Math.sin(t * 0.17) * SWAY * swayAmount.current,
        0,
      );
      sway.current.scale.setScalar(1 + Math.sin(t * 1.1) * 0.018);
      // Streams converge on the INGEST centroid, wherever it currently is.
      if (rig.current && streams.current) {
        sway.current.localToWorld(tmp.copy(data.centroids.ingest));
        streams.current.setTarget(rig.current.worldToLocal(tmp));
      }
    }
  });

  const zoomTo = (region: Region) => {
    const c = controls.current;
    const r = rig.current;
    if (!c || !r) return;
    const target = data.centroids[region]
      .clone()
      .applyEuler(BASE_ROT)
      .multiplyScalar(r.scale.x)
      .add(r.position);
    const dist = 2.1 * Math.max(r.scale.x, 0.7);
    c.setLookAt(target.x, target.y + 0.15, target.z + dist, target.x, target.y, target.z, true);
    useBrainStore.getState().setSelectedRegion(region);
    onRegionSelect?.(region);
  };

  return (
    <group ref={rig}>
      <DataStreams ref={streams} />
      <group ref={sway} rotation={[BASE_ROT.x, BASE_ROT.y, 0]}>
        <BrainPoints data={data} onRegionClick={zoomTo} />
        <Synapses data={data} />
      </group>
    </group>
  );
}

function Scene(props: BrainSceneProps) {
  const [data, setData] = useState<BrainData | null>(null);
  const controls = useRef<CameraControlsImpl>(null);

  useEffect(() => {
    let alive = true;
    loadBrainData().then((d) => alive && setData(d));
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    const c = controls.current;
    if (!c) return;
    c.mouseButtons.wheel = CameraControlsImpl.ACTION.NONE;
    c.mouseButtons.right = CameraControlsImpl.ACTION.NONE;
    c.mouseButtons.middle = CameraControlsImpl.ACTION.NONE;
    c.touches.two = CameraControlsImpl.ACTION.NONE;
    c.touches.three = CameraControlsImpl.ACTION.NONE;
  }, []);

  useEffect(() => {
    const reset = () => {
      const { pos, target } = HOME;
      controls.current?.setLookAt(pos.x, pos.y, pos.z, target.x, target.y, target.z, true);
    };
    window.addEventListener("brain:reset", reset);
    return () => window.removeEventListener("brain:reset", reset);
  }, []);

  return (
    <>
      <color attach="background" args={[props.background ?? BACKGROUND]} />
      <CameraControls
        ref={controls}
        makeDefault
        minAzimuthAngle={-0.5}
        maxAzimuthAngle={0.5}
        minPolarAngle={Math.PI / 2 - 0.3}
        maxPolarAngle={Math.PI / 2 + 0.3}
        minDistance={1.2}
        maxDistance={8}
        smoothTime={0.5}
        draggingSmoothTime={0.15}
      />
      {data && <BrainRig {...props} data={data} controls={controls} />}
      <EffectComposer multisampling={0}>
        <Bloom intensity={1.2} luminanceThreshold={0.1} luminanceSmoothing={0.2} mipmapBlur />
      </EffectComposer>
    </>
  );
}

export default function BrainScene(props: BrainSceneProps) {
  const down = useRef({ x: 0, y: 0 });

  return (
    <div
      className="absolute inset-0"
      onPointerDown={(e) => (down.current = { x: e.clientX, y: e.clientY })}
    >
      <Canvas
        dpr={[1, 2]}
        camera={{ position: HOME.pos.toArray(), fov: 40, near: 0.1, far: 50 }}
        gl={{ antialias: false, powerPreference: "high-performance" }}
        raycaster={{ params: { Points: { threshold: 0.05 }, Line: { threshold: 0 } } as RaycasterParameters }}
        onPointerMissed={(e) => {
          // Click on empty space (not a drag) returns to the overview.
          if (Math.hypot(e.clientX - down.current.x, e.clientY - down.current.y) > 5) return;
          const { selectedRegion, setSelectedRegion } = useBrainStore.getState();
          if (!selectedRegion) return;
          setSelectedRegion(null);
          window.dispatchEvent(new CustomEvent("brain:reset"));
        }}
      >
        <Suspense fallback={null}>
          <Scene {...props} />
        </Suspense>
      </Canvas>
    </div>
  );
}

