"use client";

import { useFrame } from "@react-three/fiber";
import { useMemo, useRef } from "react";
import * as THREE from "three";
import type { Vec3 } from "@/lib/types";

/*
 * Three small particle systems that make the 3D scene feel alive without
 * touching the sim core:
 *
 *   RotorWash   — cyan dust blowing out from each rotor when the drone is
 *                 moving or the controller is pushing thrust.
 *   Contrail    — a short-lived trail of cyan embers behind the drone,
 *                 implemented as a ring-buffer of THREE.Points positions.
 *   InterceptBurst — red radial burst emitted once per "intercept" event
 *                 (ownship inside a bandit's lethal radius).
 *
 * All three are implemented directly on top of THREE.Points with a
 * buffer attribute that we mutate in useFrame.  No extra libraries.
 */

// ------------------------------------------------------------------ //
// Shared sprite texture: a soft radial puff drawn once into a canvas.
// ------------------------------------------------------------------ //
function makePuffTexture(colorHex: string): THREE.CanvasTexture {
  const size = 64;
  const canvas = typeof document !== "undefined"
    ? document.createElement("canvas")
    : ({ width: size, height: size } as unknown as HTMLCanvasElement);
  canvas.width = size; canvas.height = size;
  const ctx = (canvas as HTMLCanvasElement).getContext?.("2d");
  if (ctx) {
    const g = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
    g.addColorStop(0.0, colorHex + "ff");
    g.addColorStop(0.4, colorHex + "60");
    g.addColorStop(1.0, colorHex + "00");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, size, size);
  }
  const tex = new THREE.CanvasTexture(canvas as HTMLCanvasElement);
  tex.needsUpdate = true;
  return tex;
}

// ------------------------------------------------------------------ //
// ROTOR WASH                                                          //
// ------------------------------------------------------------------ //

const ROTOR_OFFSETS: [number, number, number][] = [
  [ 0.25, 0,  0],
  [-0.25, 0,  0],
  [ 0,    0,  0.25],
  [ 0,    0, -0.25],
];

interface Particle {
  x: number; y: number; z: number;
  vx: number; vy: number; vz: number;
  life: number;      // seconds remaining
  maxLife: number;   // initial life for alpha easing
}

export function RotorWash({
  dronePos,
  droneYaw,
  active = true,
}: {
  dronePos: Vec3;          // sim ENU
  droneYaw: number;        // rad
  active?: boolean;
}) {
  const COUNT = 120;
  const geometryRef = useRef<THREE.BufferGeometry>(null);
  const particles = useMemo<Particle[]>(
    () => Array.from({ length: COUNT }, () => ({
      x: 0, y: 0, z: 0, vx: 0, vy: 0, vz: 0, life: 0, maxLife: 1,
    })),
    [],
  );
  const positions = useMemo(() => new Float32Array(COUNT * 3), []);
  const alphas    = useMemo(() => new Float32Array(COUNT), []);
  const texture   = useMemo(() => makePuffTexture("#7fdfff"), []);

  useFrame((_, dt) => {
    const capped = Math.min(dt, 0.05);
    // Three-space drone anchor: sim (x,y,z) -> three (x, z, -y)
    const baseX = dronePos[0];
    const baseY = dronePos[2];
    const baseZ = -dronePos[1];
    const cos = Math.cos(-droneYaw - Math.PI / 2);
    const sin = Math.sin(-droneYaw - Math.PI / 2);

    let spawned = 0;
    const spawnBudget = active ? 3 : 0;

    for (let i = 0; i < COUNT; i++) {
      const p = particles[i];
      if (p.life > 0) {
        p.life -= capped;
        p.x += p.vx * capped;
        p.y += p.vy * capped;
        p.z += p.vz * capped;
        p.vy -= 0.8 * capped;           // gentle gravity
        p.vx *= 0.96; p.vz *= 0.96;     // air drag
      } else if (spawned < spawnBudget) {
        spawned++;
        // Choose a rotor, rotate its offset by yaw
        const r = ROTOR_OFFSETS[i % 4];
        const ox = r[0] * cos - r[2] * sin;
        const oz = r[0] * sin + r[2] * cos;
        p.x = baseX + ox;
        p.y = Math.max(0.04, baseY + r[1]);
        p.z = baseZ + oz;
        const angle = Math.random() * Math.PI * 2;
        const speed = 0.8 + Math.random() * 0.6;
        p.vx = Math.cos(angle) * speed;
        p.vz = Math.sin(angle) * speed;
        p.vy = -0.2 - Math.random() * 0.3;
        p.maxLife = 0.55 + Math.random() * 0.35;
        p.life = p.maxLife;
      }

      positions[i * 3]     = p.x;
      positions[i * 3 + 1] = p.y;
      positions[i * 3 + 2] = p.z;
      alphas[i] = Math.max(0, p.life / p.maxLife);
    }

    if (geometryRef.current) {
      const posAttr = geometryRef.current.getAttribute("position") as THREE.BufferAttribute | undefined;
      const aAttr   = geometryRef.current.getAttribute("aAlpha")   as THREE.BufferAttribute | undefined;
      if (posAttr) posAttr.needsUpdate = true;
      if (aAttr)   aAttr.needsUpdate   = true;
    }
  });

  return (
    <points frustumCulled={false}>
      <bufferGeometry ref={geometryRef}>
        <bufferAttribute
          attach="attributes-position"
          args={[positions, 3]}
          count={COUNT}
          itemSize={3}
        />
        <bufferAttribute
          attach="attributes-aAlpha"
          args={[alphas, 1]}
          count={COUNT}
          itemSize={1}
        />
      </bufferGeometry>
      <pointsMaterial
        map={texture}
        color="#7fdfff"
        size={0.38}
        sizeAttenuation
        transparent
        depthWrite={false}
        blending={THREE.AdditiveBlending}
        opacity={0.55}
      />
    </points>
  );
}

// ------------------------------------------------------------------ //
// CONTRAIL                                                            //
// ------------------------------------------------------------------ //

export function Contrail({ dronePos }: { dronePos: Vec3 }) {
  const COUNT = 80;
  const geoRef = useRef<THREE.BufferGeometry>(null);
  const positions = useMemo(() => new Float32Array(COUNT * 3), []);
  const alphas    = useMemo(() => new Float32Array(COUNT), []);
  const texture   = useMemo(() => makePuffTexture("#00d4ff"), []);
  const head = useRef(0);
  const timer = useRef(0);
  const SPAWN_INTERVAL = 0.06;

  // On mount, park all particles off-screen.
  useMemo(() => {
    for (let i = 0; i < COUNT; i++) {
      positions[i * 3]     = 0;
      positions[i * 3 + 1] = -999;
      positions[i * 3 + 2] = 0;
      alphas[i] = 0;
    }
  }, [positions, alphas]);

  useFrame((_, dt) => {
    const capped = Math.min(dt, 0.05);
    timer.current += capped;

    // Decay all alphas
    for (let i = 0; i < COUNT; i++) {
      alphas[i] = Math.max(0, alphas[i] - capped * 0.55);
    }

    if (timer.current >= SPAWN_INTERVAL) {
      timer.current = 0;
      const idx = head.current % COUNT;
      head.current++;
      // Drone sim-to-three conversion
      positions[idx * 3]     = dronePos[0];
      positions[idx * 3 + 1] = dronePos[2];
      positions[idx * 3 + 2] = -dronePos[1];
      alphas[idx] = 1;
    }

    if (geoRef.current) {
      const pos = geoRef.current.getAttribute("position") as THREE.BufferAttribute | undefined;
      const a   = geoRef.current.getAttribute("aAlpha")   as THREE.BufferAttribute | undefined;
      if (pos) pos.needsUpdate = true;
      if (a)   a.needsUpdate = true;
    }
  });

  return (
    <points frustumCulled={false}>
      <bufferGeometry ref={geoRef}>
        <bufferAttribute
          attach="attributes-position"
          args={[positions, 3]}
          count={COUNT}
          itemSize={3}
        />
        <bufferAttribute
          attach="attributes-aAlpha"
          args={[alphas, 1]}
          count={COUNT}
          itemSize={1}
        />
      </bufferGeometry>
      <pointsMaterial
        map={texture}
        color="#00d4ff"
        size={0.26}
        sizeAttenuation
        transparent
        depthWrite={false}
        blending={THREE.AdditiveBlending}
        opacity={0.75}
      />
    </points>
  );
}

// ------------------------------------------------------------------ //
// WRECKAGE SMOKE                                                      //
// ------------------------------------------------------------------ //
//
// Dark, slow-rising puffs emitted from a falling/wrecked drone after a
// shoot-down event.  Buoyant (negative gravity) and additive-off so the
// smoke reads as opaque against the bright sky.

export function WreckageSmoke({
  position,
  active,
}: {
  position: Vec3;
  active: boolean;
}) {
  const COUNT = 60;
  const geoRef = useRef<THREE.BufferGeometry>(null);
  const particles = useMemo<Particle[]>(
    () => Array.from({ length: COUNT }, () => ({
      x: 0, y: 0, z: 0, vx: 0, vy: 0, vz: 0, life: 0, maxLife: 1,
    })),
    [],
  );
  const positions = useMemo(() => new Float32Array(COUNT * 3), []);
  const alphas    = useMemo(() => new Float32Array(COUNT), []);
  const texture   = useMemo(() => makePuffTexture("#1a1a1a"), []);

  useFrame((_, dt) => {
    const capped = Math.min(dt, 0.05);
    const baseX = position[0];
    const baseY = position[2];
    const baseZ = -position[1];

    let spawned = 0;
    const spawnBudget = active ? 2 : 0;

    for (let i = 0; i < COUNT; i++) {
      const p = particles[i];
      if (p.life > 0) {
        p.life -= capped;
        p.x += p.vx * capped;
        p.y += p.vy * capped;
        p.z += p.vz * capped;
        p.vy += 0.6 * capped;       // buoyant smoke (rises)
        p.vx *= 0.97; p.vz *= 0.97;
      } else if (spawned < spawnBudget) {
        spawned++;
        p.x = baseX + (Math.random() - 0.5) * 0.18;
        p.y = Math.max(0.05, baseY);
        p.z = baseZ + (Math.random() - 0.5) * 0.18;
        const angle = Math.random() * Math.PI * 2;
        p.vx = Math.cos(angle) * 0.4;
        p.vz = Math.sin(angle) * 0.4;
        p.vy = 0.5 + Math.random() * 0.4;
        p.maxLife = 1.6 + Math.random() * 0.8;
        p.life = p.maxLife;
      }

      positions[i * 3]     = p.x;
      positions[i * 3 + 1] = p.y;
      positions[i * 3 + 2] = p.z;
      alphas[i] = Math.max(0, p.life / p.maxLife) * 0.85;
    }

    if (geoRef.current) {
      const pos = geoRef.current.getAttribute("position") as THREE.BufferAttribute | undefined;
      const a   = geoRef.current.getAttribute("aAlpha")   as THREE.BufferAttribute | undefined;
      if (pos) pos.needsUpdate = true;
      if (a)   a.needsUpdate = true;
    }
  });

  return (
    <points frustumCulled={false}>
      <bufferGeometry ref={geoRef}>
        <bufferAttribute
          attach="attributes-position"
          args={[positions, 3]}
          count={COUNT}
          itemSize={3}
        />
        <bufferAttribute
          attach="attributes-aAlpha"
          args={[alphas, 1]}
          count={COUNT}
          itemSize={1}
        />
      </bufferGeometry>
      <pointsMaterial
        map={texture}
        color="#3a3a3a"
        size={0.6}
        sizeAttenuation
        transparent
        depthWrite={false}
        opacity={0.7}
      />
    </points>
  );
}

// ------------------------------------------------------------------ //
// INTERCEPT BURST                                                     //
// ------------------------------------------------------------------ //

export function InterceptBurst({
  center,
  trigger,
}: {
  center: Vec3;
  trigger: number; // increment this number to fire a new burst
}) {
  const COUNT = 90;
  const geoRef = useRef<THREE.BufferGeometry>(null);
  const particles = useMemo<Particle[]>(
    () => Array.from({ length: COUNT }, () => ({
      x: 0, y: 0, z: 0, vx: 0, vy: 0, vz: 0, life: 0, maxLife: 1,
    })),
    [],
  );
  const positions = useMemo(() => new Float32Array(COUNT * 3), []);
  const alphas    = useMemo(() => new Float32Array(COUNT), []);
  const texture   = useMemo(() => makePuffTexture("#ff5252"), []);
  const lastTrigger = useRef(trigger);

  useFrame((_, dt) => {
    const capped = Math.min(dt, 0.05);

    // Fire on trigger change
    if (trigger !== lastTrigger.current) {
      lastTrigger.current = trigger;
      const cx = center[0], cy = center[2], cz = -center[1];
      for (let i = 0; i < COUNT; i++) {
        const p = particles[i];
        const theta = Math.random() * Math.PI * 2;
        const phi   = Math.acos(2 * Math.random() - 1);
        const speed = 3.5 + Math.random() * 2.5;
        p.x = cx; p.y = cy; p.z = cz;
        p.vx = Math.sin(phi) * Math.cos(theta) * speed;
        p.vy = Math.cos(phi) * speed * 0.8;
        p.vz = Math.sin(phi) * Math.sin(theta) * speed;
        p.maxLife = 0.9 + Math.random() * 0.4;
        p.life = p.maxLife;
      }
    }

    for (let i = 0; i < COUNT; i++) {
      const p = particles[i];
      if (p.life > 0) {
        p.life -= capped;
        p.x += p.vx * capped;
        p.y += p.vy * capped;
        p.z += p.vz * capped;
        p.vy -= 3.2 * capped;      // stronger gravity for burst feel
        p.vx *= 0.94; p.vz *= 0.94;
      }
      positions[i * 3]     = p.x;
      positions[i * 3 + 1] = p.y;
      positions[i * 3 + 2] = p.z;
      alphas[i] = Math.max(0, p.life / p.maxLife);
    }

    if (geoRef.current) {
      const pos = geoRef.current.getAttribute("position") as THREE.BufferAttribute | undefined;
      const a   = geoRef.current.getAttribute("aAlpha")   as THREE.BufferAttribute | undefined;
      if (pos) pos.needsUpdate = true;
      if (a)   a.needsUpdate = true;
    }
  });

  return (
    <points frustumCulled={false}>
      <bufferGeometry ref={geoRef}>
        <bufferAttribute
          attach="attributes-position"
          args={[positions, 3]}
          count={COUNT}
          itemSize={3}
        />
        <bufferAttribute
          attach="attributes-aAlpha"
          args={[alphas, 1]}
          count={COUNT}
          itemSize={1}
        />
      </bufferGeometry>
      <pointsMaterial
        map={texture}
        color="#ff6b6b"
        size={0.55}
        sizeAttenuation
        transparent
        depthWrite={false}
        blending={THREE.AdditiveBlending}
        opacity={0.9}
      />
    </points>
  );
}
