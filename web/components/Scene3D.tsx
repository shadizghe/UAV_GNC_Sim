"use client";

import { Canvas, useFrame, useThree } from "@react-three/fiber";
import {
  Cylinder,
  Float,
  Grid,
  Html,
  Line,
  OrbitControls,
  TransformControls,
} from "@react-three/drei";
import { Suspense, useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { useAppStore } from "@/lib/store";
import type {
  DefensiveEvent,
  EnemyPayload,
  FriendlyDronePayload,
  InterceptorBatteryPayload,
  Vec3,
  ZonePayload,
} from "@/lib/types";
import { Terrain } from "./Terrain";
import { RotorWash, Contrail, InterceptBurst, WreckageSmoke } from "./Particles";
import { PostFX } from "./PostFX";
import { SkyEnvironment } from "./SkyEnvironment";
import { RadarSweep } from "./RadarSweep";
import {
  setMuted, startRotor, stopRotor, setRotorThrottle,
  playKlaxon, playWaypointCapture,
} from "@/lib/sounds";

/*
 * Coordinate convention:
 * Sim uses ENU: +X east, +Y north, +Z up.
 * Three.js uses Y-up: +X east, +Y up, +Z south.
 * Map (sim x, y, z) -> three (x, z, -y).
 */
const enuToThree = (p: Vec3): [number, number, number] => [p[0], p[2], -p[1]];
const roundCoord = (value: number) => Math.round(value * 100) / 100;
const threeToEnu = (p: THREE.Vector3): Vec3 => [
  roundCoord(p.x),
  roundCoord(-p.z),
  Math.max(0, roundCoord(p.y)),
];

type SceneRoomMode = "range" | "night" | "analysis";
type SceneCameraPreset = "orbit" | "top" | "chase";
type SceneEditTarget = { kind: "enemy" | "zone" | "battery" | "friendly"; index: number } | null;

const INTERCEPTOR_STATUS = {
  inactive: 0,
  boost: 1,
  coast: 2,
  hit: 3,
  miss: 4,
} as const;
const SEEKER_STATUS = {
  search: 0,
  locked: 1,
  memory: 2,
} as const;

const roomPalette: Record<SceneRoomMode, {
  background: string;
  floor: string;
  cell: string;
  section: string;
  accent: string;
  warning: string;
  hemi: [string, string, number];
  key: number;
}> = {
  range: {
    background: "radial-gradient(ellipse at center, #0c1530 0%, #06070d 80%)",
    floor: "#07101f",
    cell: "#1b3a5c",
    section: "#00d4ff",
    accent: "#00d4ff",
    warning: "#ff4081",
    hemi: ["#aad8ff", "#0a0e1a", 0.6],
    key: 0.9,
  },
  night: {
    background: "radial-gradient(ellipse at center, #071021 0%, #02040a 82%)",
    floor: "#050911",
    cell: "#122440",
    section: "#b388ff",
    accent: "#b388ff",
    warning: "#ff5252",
    hemi: ["#6ca0ff", "#02040a", 0.42],
    key: 0.62,
  },
  analysis: {
    background: "radial-gradient(ellipse at center, #0f1725 0%, #05070c 82%)",
    floor: "#0a111c",
    cell: "#203448",
    section: "#2ecc71",
    accent: "#2ecc71",
    warning: "#ffc107",
    hemi: ["#d8fff0", "#07100d", 0.68],
    key: 1.02,
  },
};

function GroundGrid({ mode }: { mode: SceneRoomMode }) {
  const palette = roomPalette[mode];
  return (
    <>
      <mesh position={[0, -0.012, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <planeGeometry args={[70, 70]} />
        <meshStandardMaterial color={palette.floor} roughness={0.82} metalness={0.08} />
      </mesh>
      <Grid
        args={[40, 40]}
        cellSize={1}
        cellThickness={0.6}
        cellColor={palette.cell}
        sectionSize={5}
        sectionThickness={1.2}
        sectionColor={palette.section}
        fadeDistance={45}
        fadeStrength={1.4}
        infiniteGrid
        position={[0, 0, 0]}
      />
      <mesh position={[0, 0.005, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[0.45, 0.6, 64]} />
        <meshBasicMaterial color={palette.accent} transparent opacity={0.4} />
      </mesh>
      {[6, 12, 18].map((radius) => (
        <mesh key={radius} position={[0, 0.01, 0]} rotation={[-Math.PI / 2, 0, 0]}>
          <ringGeometry args={[radius - 0.015, radius + 0.015, 128]} />
          <meshBasicMaterial color={palette.accent} transparent opacity={radius === 6 ? 0.22 : 0.11} />
        </mesh>
      ))}
      <mesh position={[0, 0.05, -0.85]}>
        <coneGeometry args={[0.12, 0.3, 12]} />
        <meshBasicMaterial color={palette.warning} />
      </mesh>
      <mesh position={[12, 0.04, 0]}>
        <boxGeometry args={[0.035, 0.08, 24]} />
        <meshBasicMaterial color={palette.accent} transparent opacity={0.36} />
      </mesh>
      <mesh position={[-12, 0.04, 0]}>
        <boxGeometry args={[0.035, 0.08, 24]} />
        <meshBasicMaterial color={palette.accent} transparent opacity={0.18} />
      </mesh>
      <mesh position={[0, 0.04, 12]}>
        <boxGeometry args={[24, 0.08, 0.035]} />
        <meshBasicMaterial color={palette.warning} transparent opacity={0.24} />
      </mesh>
    </>
  );
}

function LaunchPad({ position }: { position: Vec3 }) {
  const p = enuToThree(position);
  return (
    <group position={[p[0], 0.012, p[2]]}>
      <mesh rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[0.46, 0.58, 64]} />
        <meshBasicMaterial color="#00d4ff" transparent opacity={0.75} />
      </mesh>
      <mesh rotation={[-Math.PI / 2, 0, 0]}>
        <circleGeometry args={[0.36, 64]} />
        <meshBasicMaterial color="#00d4ff" transparent opacity={0.08} />
      </mesh>
    </group>
  );
}

function SamBatteryMarker({
  battery,
  index,
  selected,
  launchCount,
  onSelect,
  onMove,
}: {
  battery: InterceptorBatteryPayload;
  index: number;
  selected: boolean;
  launchCount: number;
  onSelect: (index: number) => void;
  onMove: (index: number, patch: Partial<InterceptorBatteryPayload>) => void;
}) {
  const groupRef = useRef<THREE.Group>(null);
  const p = useMemo(() => enuToThree([battery.x, battery.y, battery.z]), [battery.x, battery.y, battery.z]);
  const color = selected ? "#ff8a8a" : "#ff5252";

  useEffect(() => {
    groupRef.current?.position.set(p[0], 0.025, p[2]);
  }, [p]);

  const marker = (
    <group
      ref={groupRef}
      position={[p[0], 0.025, p[2]]}
      onPointerDown={(event) => {
        event.stopPropagation();
        onSelect(index);
      }}
    >
      <mesh rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[Math.max(0.05, battery.launch_range - 0.035), battery.launch_range + 0.035, 128]} />
        <meshBasicMaterial color={color} transparent opacity={selected ? 0.2 : 0.12} />
      </mesh>
      <mesh rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[0.42, 0.58, 48]} />
        <meshBasicMaterial color={color} transparent opacity={0.9} />
      </mesh>
      <mesh position={[0, 0.12, 0]}>
        <cylinderGeometry args={[0.18, 0.24, 0.24, 16]} />
        <meshStandardMaterial color="#331016" metalness={0.45} roughness={0.42} emissive="#5a0f18" emissiveIntensity={0.3} />
      </mesh>
      <group position={[0, 0.34, 0]} rotation={[0.72, 0, -0.45]}>
        <mesh>
          <cylinderGeometry args={[0.07, 0.08, 0.72, 16]} />
      <meshStandardMaterial color="#9c1f2f" metalness={0.55} roughness={0.32} emissive="#ff2d45" emissiveIntensity={0.22} />
        </mesh>
        <mesh position={[0, 0.42, 0]}>
          <coneGeometry args={[0.09, 0.18, 16]} />
          <meshBasicMaterial color="#ff8a3d" />
        </mesh>
      </group>
      <LaunchPulse origin={[battery.x, battery.y, battery.z]} trigger={launchCount} />
      <Html
        position={[0, 0.85, 0]}
        center
        distanceFactor={10}
        style={{ pointerEvents: "none" }}
      >
        <div className="text-[10px] font-mono text-red bg-bg/75 px-1.5 py-0.5 rounded border border-red/35 whitespace-nowrap">
          {battery.name} | {selected ? "DRAG" : "PN"}
        </div>
      </Html>
    </group>
  );

  if (!selected) return marker;

  return (
    <TransformControls
      mode="translate"
      size={0.82}
      onObjectChange={() => {
        if (!groupRef.current) return;
        const pos = groupRef.current.position;
        onMove(index, {
          x: roundCoord(pos.x),
          y: roundCoord(-pos.z),
          z: Math.max(0, roundCoord(pos.y - 0.025)),
        });
      }}
    >
      {marker}
    </TransformControls>
  );
}

function LaunchPulse({ origin, trigger }: { origin: Vec3; trigger: number }) {
  const ref = useRef<THREE.Mesh>(null);
  const age = useRef(99);
  const lastTrigger = useRef(trigger);
  const p = enuToThree(origin);

  useFrame((_, dt) => {
    if (trigger !== lastTrigger.current) {
      lastTrigger.current = trigger;
      age.current = 0;
    }
    age.current += Math.min(dt, 0.05);
    const life = Math.max(0, 1 - age.current / 0.75);
    if (!ref.current) return;
    ref.current.visible = life > 0;
    ref.current.scale.setScalar(0.6 + (1 - life) * 3.2);
    const material = ref.current.material as THREE.MeshBasicMaterial;
    material.opacity = life * 0.7;
  });

  return (
    <mesh ref={ref} position={[p[0], 0.04, p[2]]} rotation={[-Math.PI / 2, 0, 0]} visible={false}>
      <ringGeometry args={[0.22, 0.3, 64]} />
      <meshBasicMaterial color="#ffd166" transparent opacity={0} depthWrite={false} blending={THREE.AdditiveBlending} />
    </mesh>
  );
}

function InterceptorTrail({
  hist,
  slot,
  frame,
}: {
  hist: number[][][];
  slot: number;
  frame: number;
}) {
  const points = useMemo(() => {
    const out: [number, number, number][] = [];
    const stride = Math.max(1, Math.floor((frame + 1) / 220));
    for (let k = 0; k <= frame && k < hist.length; k += stride) {
      const row = hist[k]?.[slot];
      if (!row || row[6] === INTERCEPTOR_STATUS.inactive) continue;
      out.push(enuToThree([row[0], row[1], row[2]]));
    }
    const row = hist[Math.min(frame, hist.length - 1)]?.[slot];
    if (row && row[6] !== INTERCEPTOR_STATUS.inactive) {
      out.push(enuToThree([row[0], row[1], row[2]]));
    }
    return out;
  }, [frame, hist, slot]);

  if (points.length < 2) return null;
  return (
    <Line
      points={points}
      color="#ff334f"
      lineWidth={2.8}
      transparent
      opacity={0.88}
    />
  );
}

function InterceptorMissile({
  row,
  target,
}: {
  row: number[];
  target: Vec3;
}) {
  const pos = enuToThree([row[0], row[1], row[2]]);
  const vel = new THREE.Vector3(...enuToThree([row[3], row[4], row[5]]));
  const dir = vel.lengthSq() > 1e-6 ? vel.normalize() : new THREE.Vector3(0, 1, 0);
  const quat = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir);
  const status = row[6];
  const boost = status === INTERCEPTOR_STATUS.boost;
  const terminal = status === INTERCEPTOR_STATUS.hit || status === INTERCEPTOR_STATUS.miss;
  const color = status === INTERCEPTOR_STATUS.hit
    ? "#ffd166"
    : status === INTERCEPTOR_STATUS.miss
      ? "#9aa4b2"
      : boost
        ? "#ff8a3d"
        : "#ff334f";
  const targetPoint = enuToThree(target);
  const seeker = row[7] ?? SEEKER_STATUS.search;
  const seekerPoint = Number.isFinite(row[8]) && Number.isFinite(row[9]) && Number.isFinite(row[10])
    ? enuToThree([row[8], row[9], row[10]])
    : targetPoint;
  const seekerLabel = seeker === SEEKER_STATUS.locked ? "LOCK" : seeker === SEEKER_STATUS.memory ? "MEM" : "SEARCH";

  return (
    <group position={pos} quaternion={quat} scale={terminal ? 1.18 : 1}>
      <mesh>
        <coneGeometry args={[0.095, 0.34, 18]} />
        <meshStandardMaterial color={color} emissive={color} emissiveIntensity={terminal ? 0.85 : 0.5} metalness={0.42} roughness={0.26} />
      </mesh>
      <mesh position={[0, -0.2, 0]}>
        <cylinderGeometry args={[0.055, 0.075, 0.32, 18]} />
        <meshStandardMaterial color="#dbe5ee" metalness={0.65} roughness={0.2} emissive="#ff334f" emissiveIntensity={boost ? 0.18 : 0.04} />
      </mesh>
      {boost && (
        <>
          <mesh position={[0, -0.46, 0]} rotation={[Math.PI, 0, 0]}>
            <coneGeometry args={[0.12, 0.4, 16]} />
            <meshBasicMaterial color="#ff9d2e" transparent opacity={0.75} depthWrite={false} blending={THREE.AdditiveBlending} />
          </mesh>
          <pointLight color="#ff7a2f" intensity={1.2} distance={3} />
        </>
      )}
      <Line
        points={[[0, 0, 0], [seekerPoint[0] - pos[0], seekerPoint[1] - pos[1], seekerPoint[2] - pos[2]]]}
        color={seeker === SEEKER_STATUS.locked ? "#ffd166" : seeker === SEEKER_STATUS.memory ? "#b388ff" : "#9aa4b2"}
        lineWidth={1.2}
        transparent
        opacity={seeker === SEEKER_STATUS.search ? 0.14 : 0.34}
        dashed
        dashSize={0.12}
        gapSize={0.1}
      />
      <Html
        position={[0, 0.34, 0]}
        center
        distanceFactor={10}
        style={{ pointerEvents: "none" }}
      >
        <div className="rounded border border-red/35 bg-bg/75 px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wider text-red whitespace-nowrap">
          {seekerLabel}
        </div>
      </Html>
    </group>
  );
}

function Interceptors({
  hist,
  frame,
  target,
}: {
  hist: number[][][];
  frame: number;
  target: Vec3;
}) {
  const rows = hist[Math.min(frame, hist.length - 1)] ?? [];
  return (
    <>
      {rows.map((row, slot) => {
        if (!row || row[6] === INTERCEPTOR_STATUS.inactive) return null;
        return (
          <group key={slot}>
            <InterceptorTrail hist={hist} slot={slot} frame={frame} />
            <InterceptorMissile row={row} target={target} />
          </group>
        );
      })}
    </>
  );
}

function MissionEditPlane({
  defaultAltitude,
  onAdd,
}: {
  defaultAltitude: number;
  onAdd: (waypoint: Vec3) => void;
}) {
  return (
    <mesh
      position={[0, 0, 0]}
      rotation={[-Math.PI / 2, 0, 0]}
      onPointerDown={(event) => {
        if (!event.nativeEvent.shiftKey) return;
        event.stopPropagation();
        onAdd([roundCoord(event.point.x), roundCoord(-event.point.z), defaultAltitude]);
      }}
    >
      <planeGeometry args={[120, 120]} />
      <meshBasicMaterial transparent opacity={0} depthWrite={false} />
    </mesh>
  );
}

function PlannedPath({ waypoints }: { waypoints: Vec3[] }) {
  const points = useMemo(() => waypoints.map(enuToThree), [waypoints]);
  if (points.length < 2) return null;
  return (
    <Line
      points={points}
      color="#ffc107"
      lineWidth={1.5}
      dashed
      dashSize={0.3}
      gapSize={0.2}
    />
  );
}

function ReplannedPath({ waypoints }: { waypoints: Vec3[] }) {
  const points = useMemo(() => waypoints.map(enuToThree), [waypoints]);
  if (points.length < 2) return null;
  return (
    <Line
      points={points}
      color="#2ecc71"
      lineWidth={2.4}
      dashed
      dashSize={0.16}
      gapSize={0.12}
    />
  );
}

function WaypointMarker({
  waypoint,
  index,
  selected,
  reached,
  onSelect,
  onMove,
}: {
  waypoint: Vec3;
  index: number;
  selected: boolean;
  reached: boolean;
  onSelect: (index: number) => void;
  onMove: (index: number, waypoint: Vec3) => void;
}) {
  const groupRef = useRef<THREE.Group>(null);
  const p = useMemo(() => enuToThree(waypoint), [waypoint]);
  const color = selected ? "#00d4ff" : reached ? "#2ecc71" : "#ffc107";
  const labelClass = selected
    ? "text-cyan border-cyan/40"
    : reached
      ? "text-green border-green/40"
      : "text-amber border-amber/30";

  const marker = (
    <group
      ref={groupRef}
      position={p}
      onPointerDown={(event) => {
        event.stopPropagation();
        onSelect(index);
      }}
    >
      <Float speed={1.5} rotationIntensity={0.15} floatIntensity={0.25}>
        <mesh>
          <octahedronGeometry args={[0.22, 0]} />
          <meshStandardMaterial
            color={color}
            emissive={color}
            emissiveIntensity={0.55}
            metalness={0.3}
            roughness={0.4}
          />
        </mesh>
      </Float>
      <mesh position={[0, -p[1] / 2, 0]}>
        <cylinderGeometry args={[0.015, 0.015, p[1], 8]} />
        <meshBasicMaterial color={color} transparent opacity={0.25} />
      </mesh>
      <Html
        position={[0, 0.45, 0]}
        center
        distanceFactor={10}
        style={{ pointerEvents: "none" }}
      >
        <div
          className={
            "text-[10px] font-mono bg-bg/70 px-1.5 py-0.5 rounded border whitespace-nowrap " +
            labelClass
          }
        >
          WPT-{index + 1}{reached ? " ✓" : ""} | z={waypoint[2].toFixed(1)}
        </div>
      </Html>
    </group>
  );

  if (!selected) return marker;

  return (
    <TransformControls
      mode="translate"
      size={0.72}
      onObjectChange={() => {
        if (!groupRef.current) return;
        onMove(index, threeToEnu(groupRef.current.position));
      }}
    >
      {marker}
    </TransformControls>
  );
}

function Waypoints({
  waypoints,
  selectedWaypointIndex,
  reached,
  onSelect,
  onMove,
}: {
  waypoints: Vec3[];
  selectedWaypointIndex: number;
  reached: boolean[];
  onSelect: (index: number) => void;
  onMove: (index: number, waypoint: Vec3) => void;
}) {
  return (
    <>
      {waypoints.map((waypoint, index) => (
        <WaypointMarker
          key={index}
          waypoint={waypoint}
          index={index}
          selected={index === selectedWaypointIndex}
          reached={reached[index] ?? false}
          onSelect={onSelect}
          onMove={onMove}
        />
      ))}
    </>
  );
}

function FlownPath({ pos }: { pos: Vec3[] }) {
  const points = useMemo(() => {
    if (!pos || pos.length < 2) return [];
    const stride = Math.max(1, Math.floor(pos.length / 800));
    const out: [number, number, number][] = [];
    for (let i = 0; i < pos.length; i += stride) out.push(enuToThree(pos[i]));
    out.push(enuToThree(pos[pos.length - 1]));
    return out;
  }, [pos]);
  if (points.length < 2) return null;
  return (
    <Line
      points={points}
      color="#00d4ff"
      lineWidth={2.2}
      transparent
      opacity={0.95}
    />
  );
}

function DefensiveEscapeMarker({
  row,
  dronePos,
}: {
  row: number[];
  dronePos: Vec3;
}) {
  if (!row || row[0] < 0.5) return null;
  const target: Vec3 = [row[1], row[2], row[3]];
  const missile: Vec3 | null = Number.isFinite(row[6]) && Number.isFinite(row[7])
    ? [row[6], row[7], dronePos[2]]
    : null;
  const drone = enuToThree(dronePos);
  const escape = enuToThree(target);
  const missilePoint = missile ? enuToThree(missile) : null;

  return (
    <group>
      <Line
        points={[drone, escape]}
        color="#ffc107"
        lineWidth={3}
        dashed
        dashSize={0.18}
        gapSize={0.1}
        transparent
        opacity={0.95}
      />
      {missilePoint ? (
        <Line
          points={[missilePoint, drone]}
          color="#ff5252"
          lineWidth={1.6}
          dashed
          dashSize={0.1}
          gapSize={0.1}
          transparent
          opacity={0.62}
        />
      ) : null}
      <group position={escape}>
        <Float speed={2.2} rotationIntensity={0.25} floatIntensity={0.3}>
          <mesh>
            <octahedronGeometry args={[0.28, 0]} />
            <meshStandardMaterial
              color="#ffc107"
              emissive="#ffc107"
              emissiveIntensity={0.85}
              metalness={0.35}
              roughness={0.35}
            />
          </mesh>
        </Float>
        <pointLight color="#ffc107" intensity={1.2} distance={4} />
        <mesh position={[0, -escape[1] / 2, 0]}>
          <cylinderGeometry args={[0.018, 0.018, Math.max(0.1, escape[1]), 8]} />
          <meshBasicMaterial color="#ffc107" transparent opacity={0.34} />
        </mesh>
        <Html
          position={[0, 0.5, 0]}
          center
          distanceFactor={10}
          style={{ pointerEvents: "none" }}
        >
          <div className="rounded border border-amber/45 bg-bg/80 px-2 py-1 font-mono text-[10px] uppercase tracking-wider text-amber shadow-lg shadow-amber/10 whitespace-nowrap">
            EVADE | TGO {Number.isFinite(row[5]) ? row[5].toFixed(2) : "--"}s
          </div>
        </Html>
      </group>
    </group>
  );
}

function DroneBody() {
  return (
    <>
      <mesh>
        <boxGeometry args={[0.4, 0.06, 0.4]} />
        <meshStandardMaterial color="#e1e8f0" metalness={0.5} roughness={0.5} />
      </mesh>
      {[
        [0.25, 0, 0, "#00d4ff"],
        [-0.25, 0, 0, "#00d4ff"],
        [0, 0, 0.25, "#ff4081"],
        [0, 0, -0.25, "#ff4081"],
      ].map(([x, y, z, color], i) => (
        <mesh key={i} position={[x as number, y as number, z as number]}>
          <sphereGeometry args={[0.06, 16, 12]} />
          <meshStandardMaterial
            color={color as string}
            emissive={color as string}
            emissiveIntensity={0.7}
          />
        </mesh>
      ))}
      <mesh position={[0.3, 0.04, 0]} rotation={[0, 0, -Math.PI / 2]}>
        <coneGeometry args={[0.05, 0.15, 8]} />
        <meshBasicMaterial color="#00d4ff" />
      </mesh>
    </>
  );
}

/**
 * Replaces the live `Drone` once the replay scrubber has crossed the first
 * intercept event.  The wreckage tumbles and falls under gravity from the
 * impact pose, freezes when it hits the ground, and shows a brief yellow
 * flash + persistent red emissive scarring on the body.
 *
 * Motion is fully derived from `tSinceImpact` so scrubbing the replay back
 * and forth is reversible — no internal animation state.
 */
function ShotDownDrone({
  start,
  startYaw,
  startVel,
  tSinceImpact,
}: {
  start: Vec3;          // sim ENU position at impact frame
  startYaw: number;     // rad (sim yaw)
  startVel: Vec3;       // sim ENU velocity at impact frame
  tSinceImpact: number; // seconds (>= 0)
}) {
  const G = 9.81;
  const TUMBLE_PITCH = 3.4;  // rad/s
  const TUMBLE_ROLL  = 5.1;
  const TUMBLE_YAW   = 1.6;
  const HORIZONTAL_DRAG = 0.6;

  const t = Math.max(0, tSinceImpact);
  const z0 = start[2];
  const vz0 = startVel[2];
  // Time of ground impact (quadratic, taking the positive root)
  const tGround = (vz0 + Math.sqrt(vz0 * vz0 + 2 * G * z0)) / G;
  const tCapped = Math.min(t, Math.max(0, tGround));

  // Horizontal: integrate v0 * exp(-drag * s) ds = v0 * (1 - exp(-drag*t)) / drag
  const decay = Math.exp(-HORIZONTAL_DRAG * tCapped);
  const horizontalIntegral = (1 - decay) / HORIZONTAL_DRAG;
  const x = start[0] + startVel[0] * horizontalIntegral;
  const y = start[1] + startVel[1] * horizontalIntegral;
  const altitude = Math.max(0, z0 + vz0 * t - 0.5 * G * t * t);

  const p: [number, number, number] = [x, altitude, -y];
  const pitch = TUMBLE_PITCH * tCapped;
  const roll  = TUMBLE_ROLL  * tCapped;
  const yawRot = -startYaw - Math.PI / 2 + TUMBLE_YAW * tCapped;

  // Brief yellow flash anchored at the impact point — fades over 0.35 s.
  const flashStrength = Math.max(0, 1 - t / 0.35);
  // Persistent red scarring on the body — fades slowly over the first ~1 s.
  const scarOpacity   = Math.max(0, 0.55 - t * 0.55);

  const flashCenter = enuToThree(start);

  return (
    <>
      <group position={p} rotation={[pitch, yawRot, roll]}>
        <DroneBody />
        {scarOpacity > 0 && (
          <mesh>
            <boxGeometry args={[0.42, 0.075, 0.42]} />
            <meshBasicMaterial
              color="#ff5252"
              transparent
              opacity={scarOpacity}
              depthWrite={false}
            />
          </mesh>
        )}
      </group>
      {flashStrength > 0 && (
        <mesh position={flashCenter} scale={0.4 + flashStrength * 1.6}>
          <sphereGeometry args={[0.6, 16, 12]} />
          <meshBasicMaterial
            color="#ffd966"
            transparent
            opacity={flashStrength * 0.85}
            depthWrite={false}
            blending={THREE.AdditiveBlending}
          />
        </mesh>
      )}
    </>
  );
}

/**
 * 3σ position-uncertainty ellipsoid driven by the EKF covariance diagonal.
 * The sphere is unit-radius and gets scaled per-axis; we convert ENU
 * variances into three.js axes (sim_z → three_y, sim_y → -three_z), so
 * the visible "fattening" of an axis directly reflects the corresponding
 * sigma in the world the user is reasoning about.
 *
 * Recolours during GPS denial — the ellipsoid balloons because the EKF
 * is dead-reckoning on IMU only and its position covariance grows.
 */
function UncertaintyEllipsoid({
  position,
  posVar,
  gpsDenied,
}: {
  position: Vec3;
  posVar: Vec3;
  gpsDenied: boolean;
}) {
  const FLOOR = 1e-4; // m^2 — keeps the ellipsoid drawable when σ→0
  const sx = 3 * Math.sqrt(Math.max(posVar[0], FLOOR));
  const sy_enu = 3 * Math.sqrt(Math.max(posVar[1], FLOOR));
  const sz_enu = 3 * Math.sqrt(Math.max(posVar[2], FLOOR));
  const p = enuToThree(position);
  const color = gpsDenied ? "#ff5252" : "#00d4ff";
  const fillOpacity = gpsDenied ? 0.18 : 0.10;
  const wireOpacity = gpsDenied ? 0.55 : 0.40;
  return (
    <group position={p}>
      <mesh scale={[sx, sz_enu, sy_enu]}>
        <sphereGeometry args={[1, 32, 16]} />
        <meshBasicMaterial
          color={color}
          transparent
          opacity={fillOpacity}
          depthWrite={false}
        />
      </mesh>
      <mesh scale={[sx, sz_enu, sy_enu]}>
        <sphereGeometry args={[1, 24, 12]} />
        <meshBasicMaterial
          color={color}
          wireframe
          transparent
          opacity={wireOpacity}
          depthWrite={false}
        />
      </mesh>
    </group>
  );
}

function Drone({ position, yaw }: { position: Vec3; yaw: number }) {
  const ref = useRef<THREE.Group>(null);
  const p = enuToThree(position);
  useFrame(() => {
    if (ref.current) {
      ref.current.position.set(p[0], p[1], p[2]);
      ref.current.rotation.set(0, -yaw - Math.PI / 2, 0);
    }
  });
  return (
    <group ref={ref}>
      <DroneBody />
    </group>
  );
}

function EditableDrone({
  position,
  onMove,
}: {
  position: Vec3;
  onMove: (position: Vec3) => void;
}) {
  const groupRef = useRef<THREE.Group>(null);
  const p = useMemo(() => enuToThree(position), [position]);

  useEffect(() => {
    groupRef.current?.position.set(p[0], p[1], p[2]);
  }, [p]);

  return (
    <TransformControls
      mode="translate"
      size={0.82}
      onObjectChange={() => {
        if (!groupRef.current) return;
        onMove(threeToEnu(groupRef.current.position));
      }}
    >
      <group ref={groupRef} position={p} rotation={[0, -Math.PI / 2, 0]}>
        <DroneBody />
        <Html
          position={[0, 0.45, 0]}
          center
          distanceFactor={10}
          style={{ pointerEvents: "none" }}
        >
          <div className="text-[10px] font-mono text-cyan bg-bg/70 px-1.5 py-0.5 rounded border border-cyan/40 whitespace-nowrap">
            DRONE | z={position[2].toFixed(1)}
          </div>
        </Html>
      </group>
    </TransformControls>
  );
}

function zonePosition(zone: ZonePayload): [number, number, number] {
  return [zone.cx, (zone.z_min + zone.z_max) / 2, -zone.cy];
}

function ZoneVolume({
  zone,
  index,
  selected,
  onSelect,
  onMove,
}: {
  zone: ZonePayload;
  index: number;
  selected: boolean;
  onSelect: (index: number) => void;
  onMove: (index: number, patch: Partial<ZonePayload>) => void;
}) {
  const groupRef = useRef<THREE.Group>(null);
  const isThreat = zone.kind === "threat";
  const color = isThreat ? "#ffc107" : "#ff5252";
  const height = Math.max(0.1, zone.z_max - zone.z_min);
  const p = useMemo(() => zonePosition(zone), [zone]);

  useEffect(() => {
    groupRef.current?.position.set(p[0], p[1], p[2]);
  }, [p]);

  const volume = (
    <group
      ref={groupRef}
      position={p}
      onPointerDown={(event) => {
        event.stopPropagation();
        onSelect(index);
      }}
    >
      <Cylinder args={[zone.r, zone.r, height, 32, 1, true]}>
        <meshStandardMaterial
          color={color}
          transparent
          opacity={selected ? 0.28 : 0.18}
          side={THREE.DoubleSide}
          emissive={color}
          emissiveIntensity={selected ? 0.32 : 0.15}
        />
      </Cylinder>
      {[height / 2, -height / 2].map((dy, i) => (
        <mesh key={i} position={[0, dy, 0]} rotation={[Math.PI / 2, 0, 0]}>
          <ringGeometry args={[zone.r - 0.02, zone.r + (selected ? 0.04 : 0.02), 64]} />
          <meshBasicMaterial color={color} transparent opacity={selected ? 1 : 0.85} />
        </mesh>
      ))}
      {selected && (
        <mesh rotation={[Math.PI / 2, 0, 0]}>
          <ringGeometry args={[zone.r + 0.11, zone.r + 0.14, 80]} />
          <meshBasicMaterial color="#00d4ff" transparent opacity={0.78} />
        </mesh>
      )}
      <Html
        position={[0, height / 2 + 0.4, 0]}
        center
        distanceFactor={10}
        style={{ pointerEvents: "none" }}
      >
        <div
          className={
            "text-[10px] font-mono px-1.5 py-0.5 rounded border whitespace-nowrap " +
            (isThreat
              ? "text-amber bg-bg/70 border-amber/30"
              : "text-red bg-bg/70 border-red/30")
          }
        >
          {zone.name} | {selected ? "DRAG" : zone.kind.toUpperCase()}
        </div>
      </Html>
    </group>
  );

  if (!selected) return volume;

  return (
    <TransformControls
      mode="translate"
      size={0.86}
      onObjectChange={() => {
        if (!groupRef.current) return;
        const pos = groupRef.current.position;
        const centerY = Math.max(height / 2, roundCoord(pos.y));
        const zMin = roundCoord(Math.max(0, centerY - height / 2));
        onMove(index, {
          cx: roundCoord(pos.x),
          cy: roundCoord(-pos.z),
          z_min: zMin,
          z_max: roundCoord(zMin + height),
        });
      }}
    >
      {volume}
    </TransformControls>
  );
}

function Zones({
  zones,
  selectedTarget,
  onSelect,
  onMove,
}: {
  zones: ZonePayload[];
  selectedTarget: SceneEditTarget;
  onSelect: (index: number) => void;
  onMove: (index: number, patch: Partial<ZonePayload>) => void;
}) {
  return (
    <>
      {zones.map((zone, index) => (
        <ZoneVolume
          key={`${zone.name}-${index}`}
          zone={zone}
          index={index}
          selected={selectedTarget?.kind === "zone" && selectedTarget.index === index}
          onSelect={onSelect}
          onMove={onMove}
        />
      ))}
    </>
  );
}

function FriendlyDroneMarker({
  drone,
  index,
  selected,
  onSelect,
  onMove,
}: {
  drone: FriendlyDronePayload;
  index: number;
  selected: boolean;
  onSelect: (index: number) => void;
  onMove: (index: number, patch: Partial<FriendlyDronePayload>) => void;
}) {
  const groupRef = useRef<THREE.Group>(null);
  const p = useMemo(() => enuToThree([drone.x, drone.y, drone.z]), [drone]);

  useEffect(() => {
    groupRef.current?.position.set(p[0], p[1], p[2]);
  }, [p]);

  const marker = (
    <group
      ref={groupRef}
      position={p}
      onPointerDown={(event) => {
        event.stopPropagation();
        onSelect(index);
      }}
    >
      <Float speed={2.1} rotationIntensity={0.2} floatIntensity={0.1}>
        <mesh rotation={[0, 0, -Math.PI / 2]}>
          <coneGeometry args={[0.18, 0.52, 4]} />
          <meshStandardMaterial
            color={selected ? "#a7ffdf" : "#2ecc71"}
            emissive="#2ecc71"
            emissiveIntensity={selected ? 0.8 : 0.45}
            metalness={0.35}
            roughness={0.35}
          />
        </mesh>
      </Float>
      <mesh rotation={[Math.PI / 2, 0, 0]}>
        <ringGeometry args={[selected ? 0.42 : 0.34, selected ? 0.46 : 0.37, 48]} />
        <meshBasicMaterial color={selected ? "#a7ffdf" : "#2ecc71"} transparent opacity={0.78} />
      </mesh>
      <Html position={[0, 0.45, 0]} center distanceFactor={10} style={{ pointerEvents: "none" }}>
        <div className="text-[10px] font-mono text-green bg-bg/70 px-1.5 py-0.5 rounded border border-green/30 whitespace-nowrap">
          {drone.name} | {selected ? "DRAG" : drone.route_mode.toUpperCase()}
        </div>
      </Html>
    </group>
  );

  if (!selected) return marker;

  return (
    <TransformControls
      mode="translate"
      size={0.72}
      onObjectChange={() => {
        if (!groupRef.current) return;
        const next = threeToEnu(groupRef.current.position);
        onMove(index, { x: next[0], y: next[1], z: next[2] });
      }}
    >
      {marker}
    </TransformControls>
  );
}

function FriendlyDrones({
  drones,
  selectedTarget,
  onSelect,
  onMove,
}: {
  drones: FriendlyDronePayload[];
  selectedTarget: SceneEditTarget;
  onSelect: (index: number) => void;
  onMove: (index: number, patch: Partial<FriendlyDronePayload>) => void;
}) {
  return (
    <>
      {drones.map((drone, index) => (
        <FriendlyDroneMarker
          key={`${drone.name}-${index}`}
          drone={drone}
          index={index}
          selected={selectedTarget?.kind === "friendly" && selectedTarget.index === index}
          onSelect={onSelect}
          onMove={onMove}
        />
      ))}
    </>
  );
}

function EnemyMarker({
  enemy,
  index,
  selected,
  onSelect,
  onMove,
}: {
  enemy: EnemyPayload;
  index: number;
  selected: boolean;
  onSelect: (index: number) => void;
  onMove: (index: number, patch: Partial<EnemyPayload>) => void;
}) {
  const groupRef = useRef<THREE.Group>(null);
  const p = useMemo(() => enuToThree([enemy.x, enemy.y, enemy.z]), [enemy]);

  useEffect(() => {
    groupRef.current?.position.set(p[0], p[1], p[2]);
  }, [p]);

  const marker = (
    <group
      ref={groupRef}
      position={p}
      onPointerDown={(event) => {
        event.stopPropagation();
        onSelect(index);
      }}
    >
      <Float speed={2.5} rotationIntensity={0.4} floatIntensity={0.15}>
        <mesh>
          <octahedronGeometry args={[selected ? 0.28 : 0.22, 0]} />
          <meshStandardMaterial
            color={selected ? "#ff8a8a" : "#ff5252"}
            emissive="#ff5252"
            emissiveIntensity={selected ? 0.85 : 0.55}
            metalness={0.4}
            roughness={0.4}
          />
        </mesh>
      </Float>
      <mesh>
        <sphereGeometry args={[enemy.det_r, 32, 16]} />
        <meshBasicMaterial
          color={selected ? "#ff8a8a" : "#ff5252"}
          transparent
          opacity={selected ? 0.1 : 0.06}
          wireframe
        />
      </mesh>
      {selected && (
        <mesh>
          <sphereGeometry args={[Math.max(0.18, enemy.leth_r), 24, 12]} />
          <meshBasicMaterial color="#ffc107" transparent opacity={0.12} wireframe />
        </mesh>
      )}
      <Html
        position={[0, 0.5, 0]}
        center
        distanceFactor={10}
        style={{ pointerEvents: "none" }}
      >
        <div className="text-[10px] font-mono text-red bg-bg/70 px-1.5 py-0.5 rounded border border-red/30 whitespace-nowrap">
          {enemy.name} | {selected ? "DRAG" : enemy.behavior.toUpperCase()}
        </div>
      </Html>
    </group>
  );

  if (!selected) return marker;

  return (
    <TransformControls
      mode="translate"
      size={0.78}
      onObjectChange={() => {
        if (!groupRef.current) return;
        const next = threeToEnu(groupRef.current.position);
        onMove(index, {
          x: next[0],
          y: next[1],
          z: next[2],
          orbit_cx: next[0],
          orbit_cy: next[1],
        });
      }}
    >
      {marker}
    </TransformControls>
  );
}

function Enemies({
  enemies,
  selectedTarget,
  onSelect,
  onMove,
}: {
  enemies: EnemyPayload[];
  selectedTarget: SceneEditTarget;
  onSelect: (index: number) => void;
  onMove: (index: number, patch: Partial<EnemyPayload>) => void;
}) {
  return (
    <>
      {enemies.map((enemy, index) => (
        <EnemyMarker
          key={`${enemy.name}-${index}`}
          enemy={enemy}
          index={index}
          selected={selectedTarget?.kind === "enemy" && selectedTarget.index === index}
          onSelect={onSelect}
          onMove={onMove}
        />
      ))}
    </>
  );
}

function SceneLoadingHUD() {
  return (
    <Html center>
      <div className="text-cyan text-xs tracking-widest uppercase animate-pulse">
        Initialising scene...
      </div>
    </Html>
  );
}

function CameraPresetRig({
  preset,
  focus,
}: {
  preset: SceneCameraPreset;
  focus: Vec3;
}) {
  const { camera, controls } = useThree();

  useEffect(() => {
    const target = new THREE.Vector3(...enuToThree(focus));
    const next = target.clone();
    if (preset === "top") {
      next.add(new THREE.Vector3(0, 18, 0.01));
    } else if (preset === "chase") {
      next.add(new THREE.Vector3(-6, 4.5, 7));
    } else {
      next.add(new THREE.Vector3(10, 8, 10));
    }
    camera.position.copy(next);
    camera.lookAt(target);
    const orbitControls = controls as { target?: THREE.Vector3; update?: () => void } | undefined;
    if (orbitControls?.target) {
      orbitControls.target.copy(target);
      orbitControls.update?.();
    }
  }, [camera, controls, focus, preset]);

  return null;
}

export function Scene3D() {
  const {
    currentPreset,
    initialPosition,
    antiAirConfig,
    simResult,
    replayIndex,
    sceneRoomMode,
    sceneCameraPreset,
    sceneEditTarget,
    friendlyDrones,
    selectedWaypointIndex,
    selectWaypoint,
    updateWaypoint,
    addWaypoint,
    deleteWaypoint,
    setInitialPosition,
    selectSceneEditTarget,
    updateFriendlyDrone,
    updateEnemy,
    updateZone,
    updateBattery,
    showTerrain,
    showParticles,
    showPostFX,
    showSky,
    showRadarSweep,
    soundEnabled,
  } = useAppStore();

  const waypoints = currentPreset?.waypoints ?? [];
  const zones = currentPreset?.zones ?? [];
  const enemies = currentPreset?.enemies ?? [];
  const interceptorBatteries = simResult?.interceptor_batteries?.length
    ? simResult.interceptor_batteries
    : antiAirConfig.batteries;
  const defaultAltitude = waypoints[selectedWaypointIndex]?.[2] ?? waypoints[waypoints.length - 1]?.[2] ?? 2;

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      const active = document.activeElement;
      if (active instanceof HTMLElement && ["INPUT", "TEXTAREA", "SELECT"].includes(active.tagName)) {
        return;
      }
      if (event.key === "Delete" || event.key === "Backspace") {
        deleteWaypoint();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [deleteWaypoint]);

  const simFrame = simResult
    ? Math.max(0, Math.min(replayIndex, simResult.pos.length - 1))
    : 0;
  const room = roomPalette[sceneRoomMode];

  // --- Engagement event detection (red burst + shoot-down trigger) ----- //
  // The bandit's "kill" radius sits between leth_r (~1 m, the simulator's
  // strict lethal core which the planner usually avoids) and det_r (~3-4 m,
  // the wide awareness bubble — too aggressive: many waypoints sit inside
  // it and would trigger an instant kill on approach). 1.5 × leth_r is the
  // engagement radius: bandit sees you anywhere in det_r, but only kills
  // once you're well inside its weapon envelope.
  const interceptEvents = useMemo(() => {
    if (!simResult || simResult.enemy_hist.length === 0 || enemies.length === 0) {
      return [] as { frame: number; position: Vec3 }[];
    }
    const events: { frame: number; position: Vec3 }[] = [];
    const inside = new Array(enemies.length).fill(false);
    const M = Math.min(enemies.length, simResult.enemy_hist[0]?.length ?? 0);
    for (let k = 0; k < simResult.pos.length; k++) {
      const own = simResult.pos[k];
      const slice = simResult.enemy_hist[k];
      if (!slice) continue;
      for (let j = 0; j < M; j++) {
        const e = slice[j];
        if (!e) continue;
        const range = enemies[j].leth_r * 1.5;
        const dx = e[0] - own[0], dy = e[1] - own[1], dz = e[2] - own[2];
        const d = Math.hypot(dx, dy, dz);
        if (d < range && !inside[j]) {
          events.push({ frame: k, position: own as Vec3 });
          inside[j] = true;
        } else if (d >= range * 1.2) {
          inside[j] = false;
        }
      }
    }
    return events;
  }, [simResult, enemies]);

  const missileHitEvents = useMemo(() => {
    const events = (simResult?.interceptor_events ?? [])
      .flatMap((event) => (
        event.type === "hit"
          ? [{ frame: event.frame, position: event.position }]
          : []
      ));
    return events;
  }, [simResult?.interceptor_events]);

  const combinedEngagementEvents = useMemo(() => {
    return [...interceptEvents, ...missileHitEvents].sort((a, b) => a.frame - b.frame);
  }, [interceptEvents, missileHitEvents]);

  const launchCountsByBattery = useMemo(() => {
    const counts = new Array(interceptorBatteries.length).fill(0);
    for (const event of simResult?.interceptor_events ?? []) {
      if (event.type === "launch" && event.frame <= simFrame && event.battery < counts.length) {
        counts[event.battery] += 1;
      }
    }
    return counts;
  }, [interceptorBatteries.length, simFrame, simResult?.interceptor_events]);

  const interceptCount = useMemo(
    () => combinedEngagementEvents.filter((e) => e.frame <= simFrame).length,
    [combinedEngagementEvents, simFrame],
  );
  const lastInterceptCenter: Vec3 =
    interceptCount > 0
      ? combinedEngagementEvents[interceptCount - 1].position
      : ([0, 0, 0] as Vec3);

  // --- Shoot-down state -------------------------------------------------- //
  // Once the replay reaches the first intercept event, the drone is "shot
  // down": we freeze sim-driven motion at the impact frame and hand off
  // rendering to <ShotDownDrone>, which tumbles to the ground.
  const firstInterceptFrame = combinedEngagementEvents[0]?.frame;
  const shotDown =
    simResult !== null &&
    firstInterceptFrame !== undefined &&
    simFrame >= firstInterceptFrame;

  // Frame at which each waypoint became "captured" (the active-waypoint
  // pointer in waypoint_active advanced past it). Captures that happened
  // after the drone was already shot down don't count.
  const waypointReachedFrames = useMemo(() => {
    if (!simResult || waypoints.length === 0) return [] as number[];
    const frames: number[] = [];
    let prev = simResult.waypoint_active[0];
    let i = 0;
    for (let k = 1; k < simResult.waypoint_active.length; k++) {
      const w = simResult.waypoint_active[k];
      if (!prev || !w) { prev = w; continue; }
      if (w[0] !== prev[0] || w[1] !== prev[1] || w[2] !== prev[2]) {
        if (i < waypoints.length) frames[i++] = k;
      }
      prev = w;
    }
    while (frames.length < waypoints.length) frames.push(Number.POSITIVE_INFINITY);
    return frames;
  }, [simResult, waypoints]);

  const waypointReached = useMemo(() => {
    return waypointReachedFrames.map((f) => {
      if (!simResult) return false;
      if (firstInterceptFrame !== undefined && f > firstInterceptFrame) return false;
      return f <= simFrame;
    });
  }, [simResult, simFrame, firstInterceptFrame, waypointReachedFrames]);

  // Truncate the live drone's apparent state at the impact frame so the
  // flown-path line stops where the wreckage starts to fall.
  const renderFrame =
    shotDown && firstInterceptFrame !== undefined
      ? firstInterceptFrame
      : simFrame;

  const replayPath = simResult ? simResult.pos.slice(0, renderFrame + 1) : [];
  const dronePos: Vec3 = simResult ? simResult.pos[renderFrame] : initialPosition;
  const droneYaw = simResult ? simResult.euler[renderFrame][2] : 0;
  const defensiveRow = simResult?.defensive_hist?.[Math.min(simFrame, (simResult.defensive_hist?.length ?? 1) - 1)] ?? null;
  const defensiveActive = Boolean(defensiveRow && defensiveRow[0] >= 0.5);

  const tSinceImpact =
    shotDown && simResult && firstInterceptFrame !== undefined
      ? Math.max(0, simResult.t[simFrame] - simResult.t[firstInterceptFrame])
      : 0;
  const impactVel: Vec3 =
    shotDown && simResult && firstInterceptFrame !== undefined
      ? simResult.vel[firstInterceptFrame]
      : ([0, 0, 0] as Vec3);

  const currentReroute = useMemo(() => {
    if (!simResult?.reroute_events?.length) return null;
    let latest = null as (typeof simResult.reroute_events)[number] | null;
    for (const event of simResult.reroute_events) {
      if (event.frame <= simFrame) latest = event;
      else break;
    }
    return latest;
  }, [simFrame, simResult]);

  const currentDefensiveEvent = useMemo(() => {
    if (!simResult?.defensive_events?.length) return null as DefensiveEvent | null;
    let latest = null as DefensiveEvent | null;
    for (const event of simResult.defensive_events) {
      if (event.frame <= simFrame) latest = event;
      else break;
    }
    return latest;
  }, [simFrame, simResult]);

  // Wreckage drift position (for smoke emitter to follow the falling body).
  const wreckagePos: Vec3 = shotDown
    ? (() => {
        const G = 9.81;
        const z0 = dronePos[2];
        const vz0 = impactVel[2];
        const tGround = (vz0 + Math.sqrt(vz0 * vz0 + 2 * G * z0)) / G;
        const tc = Math.min(tSinceImpact, Math.max(0, tGround));
        const decay = Math.exp(-0.6 * tc);
        const integ = (1 - decay) / 0.6;
        return [
          dronePos[0] + impactVel[0] * integ,
          dronePos[1] + impactVel[1] * integ,
          Math.max(0, z0 + vz0 * tSinceImpact - 0.5 * G * tSinceImpact * tSinceImpact),
        ];
      })()
    : dronePos;

  // ---- Audio: pitch the rotor whirr from the current thrust + fire ---- //
  // klaxon on each new intercept event; chime on each waypoint capture.
  useEffect(() => {
    setMuted(!soundEnabled);
    if (soundEnabled && simResult && !shotDown) startRotor();
    else stopRotor();
    return () => stopRotor();
  }, [soundEnabled, simResult, shotDown]);

  useEffect(() => {
    if (!soundEnabled || !simResult) return;
    // Map current thrust (~mass*g hover .. 4*thrust_max) to 0..1
    const thrust = simResult.thrust[simFrame] ?? 0;
    const hover = 1.2 * 9.81;
    const range = Math.max(8, hover * 2);
    setRotorThrottle(Math.max(0, Math.min(1, thrust / range)));
  }, [soundEnabled, simResult, simFrame]);

  // Klaxon trigger
  const lastInterceptCountRef = useRef(0);
  useEffect(() => {
    if (!soundEnabled) { lastInterceptCountRef.current = interceptCount; return; }
    if (interceptCount > lastInterceptCountRef.current) {
      playKlaxon();
    }
    lastInterceptCountRef.current = interceptCount;
  }, [soundEnabled, interceptCount]);

  // Waypoint-capture chime: count waypoints reached up to current frame.
  const lastWaypointCountRef = useRef(0);
  const waypointsReachedNow = useMemo(() => {
    if (!simResult) return 0;
    // Count active-waypoint transitions up to simFrame.
    let count = 0;
    let prev = simResult.waypoint_active[0];
    for (let k = 1; k <= simFrame; k++) {
      const w = simResult.waypoint_active[k];
      if (!prev || !w) continue;
      if (w[0] !== prev[0] || w[1] !== prev[1] || w[2] !== prev[2]) count++;
      prev = w;
    }
    return count;
  }, [simResult, simFrame]);

  useEffect(() => {
    if (!soundEnabled) { lastWaypointCountRef.current = waypointsReachedNow; return; }
    if (waypointsReachedNow > lastWaypointCountRef.current) {
      playWaypointCapture();
    }
    lastWaypointCountRef.current = waypointsReachedNow;
  }, [soundEnabled, waypointsReachedNow]);

  return (
    <Canvas
      shadows
      camera={{ position: [10, 9, 10], fov: 45, near: 0.1, far: 200 }}
      gl={{ antialias: true, toneMapping: THREE.NoToneMapping }}
      style={{ background: room.background }}
    >
      <Suspense fallback={<SceneLoadingHUD />}>
        <hemisphereLight args={room.hemi} />
        <directionalLight position={[8, 14, 6]} intensity={room.key} castShadow />
        <CameraPresetRig preset={sceneCameraPreset} focus={dronePos} />

        {showSky && <SkyEnvironment mode={sceneRoomMode} />}

        {showTerrain && <Terrain mode={sceneRoomMode} />}
        <GroundGrid mode={sceneRoomMode} />
        <LaunchPad position={initialPosition} />
        {antiAirConfig.enabled && interceptorBatteries.map((battery, index) => (
          <SamBatteryMarker
            key={`${battery.name}-${index}`}
            battery={battery}
            index={index}
            selected={sceneEditTarget?.kind === "battery" && sceneEditTarget.index === index}
            launchCount={launchCountsByBattery[index] ?? 0}
            onSelect={(batteryIndex) => selectSceneEditTarget({ kind: "battery", index: batteryIndex })}
            onMove={updateBattery}
          />
        ))}
        <MissionEditPlane defaultAltitude={defaultAltitude} onAdd={addWaypoint} />
        <FriendlyDrones
          drones={friendlyDrones}
          selectedTarget={sceneEditTarget}
          onSelect={(index) => selectSceneEditTarget({ kind: "friendly", index })}
          onMove={updateFriendlyDrone}
        />
        <Zones
          zones={zones}
          selectedTarget={sceneEditTarget}
          onSelect={(index) => selectSceneEditTarget({ kind: "zone", index })}
          onMove={updateZone}
        />
        <Enemies
          enemies={enemies}
          selectedTarget={sceneEditTarget}
          onSelect={(index) => selectSceneEditTarget({ kind: "enemy", index })}
          onMove={updateEnemy}
        />
        <PlannedPath waypoints={waypoints} />
        {simResult?.reroute_events?.length ? (
          <ReplannedPath waypoints={simResult.replanned_waypoints} />
        ) : null}
        <Waypoints
          waypoints={waypoints}
          selectedWaypointIndex={selectedWaypointIndex}
          reached={waypointReached}
          onSelect={selectWaypoint}
          onMove={updateWaypoint}
        />

        {simResult && <FlownPath pos={replayPath} />}
        {simResult && defensiveRow ? (
          <DefensiveEscapeMarker row={defensiveRow} dronePos={dronePos} />
        ) : null}
        {simResult?.interceptor_hist?.length ? (
          <Interceptors
            hist={simResult.interceptor_hist}
            frame={simFrame}
            target={dronePos}
          />
        ) : null}
        {simResult && showRadarSweep && (
          <RadarSweep dronePos={dronePos} range={8} />
        )}
        {simResult ? (
          <>
            {shotDown ? (
              <ShotDownDrone
                start={dronePos}
                startYaw={droneYaw}
                startVel={impactVel}
                tSinceImpact={tSinceImpact}
              />
            ) : (
              <Drone position={dronePos} yaw={droneYaw} />
            )}
            {!shotDown
              && simResult.estimator_kind === "ins_gps"
              && simResult.pos_cov_diag
              && simResult.pos_cov_diag[renderFrame] && (
                <UncertaintyEllipsoid
                  position={dronePos}
                  posVar={simResult.pos_cov_diag[renderFrame]}
                  gpsDenied={Boolean(simResult.gps_denied?.[renderFrame])}
                />
              )}
            {showParticles && (
              <>
                {!shotDown && <Contrail dronePos={dronePos} />}
                {!shotDown && (
                  <RotorWash dronePos={dronePos} droneYaw={droneYaw} active />
                )}
                {shotDown && (
                  <WreckageSmoke position={wreckagePos} active={true} />
                )}
                <InterceptBurst center={lastInterceptCenter} trigger={interceptCount} />
              </>
            )}
            {currentReroute && (
              <Html
                position={[dronePos[0], dronePos[2] + 1.05, -dronePos[1]]}
                center
                distanceFactor={10}
                style={{ pointerEvents: "none" }}
              >
                <div className="rounded border border-amber/45 bg-bg/80 px-2 py-1 font-mono text-[10px] uppercase tracking-wider text-amber shadow-lg shadow-amber/10 whitespace-nowrap">
                  {currentReroute.message} | {currentReroute.threat_name}
                </div>
              </Html>
            )}
            {defensiveActive && (
              <Html
                position={[dronePos[0], dronePos[2] + (currentReroute ? 1.48 : 1.05), -dronePos[1]]}
                center
                distanceFactor={10}
                style={{ pointerEvents: "none" }}
              >
                <div className="rounded border border-amber/45 bg-bg/85 px-2 py-1 font-mono text-[10px] uppercase tracking-wider text-amber shadow-lg shadow-amber/10 whitespace-nowrap">
                  MISSILE WARNING | {currentDefensiveEvent?.mode?.toUpperCase() ?? "EVADE"}
                </div>
              </Html>
            )}
          </>
        ) : (
          <EditableDrone position={initialPosition} onMove={setInitialPosition} />
        )}

        <OrbitControls
          makeDefault
          enableDamping
          dampingFactor={0.08}
          target={[2.5, 1.5, -2.5]}
          maxPolarAngle={Math.PI / 2 - 0.05}
          minDistance={3}
          maxDistance={50}
        />

        {showPostFX && <PostFX />}
      </Suspense>
    </Canvas>
  );
}
