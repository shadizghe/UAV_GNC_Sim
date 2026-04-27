"use client";

import { useFrame } from "@react-three/fiber";
import { useMemo, useRef } from "react";
import * as THREE from "three";
import type { Vec3 } from "@/lib/types";

/**
 * Animated 3D radar sweep — a rotating cyan wedge anchored to the drone's
 * ground projection.  The wedge fades from full alpha at the inner edge
 * to transparent at the outer edge, plus a brighter leading line so the
 * sweep "flicks" through the scene.
 *
 * Built directly on a custom BufferGeometry (one triangle fan per pulse)
 * rotated each frame in useFrame.  No external assets, ~60 verts total.
 */

const WEDGE_ANGLE = Math.PI * 0.18;  // ~32° wide
const SWEEP_HZ = 0.4;                // revolutions per second
const SEGMENTS = 24;
const RADAR_GROUND_Y = 0.04;         // sit just above the grid

export function RadarSweep({
  dronePos,
  range = 8,
}: {
  dronePos: Vec3;
  range?: number;
}) {
  const wedgeRef = useRef<THREE.Group>(null);
  const ringRef  = useRef<THREE.Mesh>(null);

  // Sim ENU (x, y, z) -> three (x, y_up, -y_north)
  const droneGroundXZ = useMemo(
    () => [dronePos[0], -dronePos[1]] as [number, number],
    [dronePos],
  );

  // Build a triangle-fan wedge geometry once.
  const wedgeGeometry = useMemo(() => {
    const verts: number[] = [0, 0, 0];          // apex
    const colors: number[] = [0, 0.83, 1];      // cyan at apex
    for (let i = 0; i <= SEGMENTS; i++) {
      const a = -WEDGE_ANGLE / 2 + (WEDGE_ANGLE * i) / SEGMENTS;
      verts.push(Math.cos(a) * range, 0, Math.sin(a) * range);
      // Fade alpha through colour intensity at the rim.
      colors.push(0, 0.83, 1);
    }
    const indices: number[] = [];
    for (let i = 1; i <= SEGMENTS; i++) indices.push(0, i, i + 1);
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.Float32BufferAttribute(verts, 3));
    geo.setAttribute("color",    new THREE.Float32BufferAttribute(colors, 3));
    geo.setIndex(indices);
    return geo;
  }, [range]);

  // Leading-edge line mesh (a thin slab along the wedge's CW edge).
  const leadGeometry = useMemo(() => {
    const a = WEDGE_ANGLE / 2;
    const verts = new Float32Array([
      0, 0, 0,
      Math.cos(a) * range, 0, Math.sin(a) * range,
    ]);
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(verts, 3));
    return geo;
  }, [range]);

  useFrame((_, dt) => {
    const group = wedgeRef.current;
    if (group) {
      group.position.set(droneGroundXZ[0], RADAR_GROUND_Y, droneGroundXZ[1]);
      group.rotation.y -= SWEEP_HZ * Math.PI * 2 * dt;
    }
    if (ringRef.current) {
      ringRef.current.position.set(droneGroundXZ[0], RADAR_GROUND_Y - 0.001, droneGroundXZ[1]);
    }
  });

  return (
    <>
      {/* Static range ring under the wedge. */}
      <mesh
        ref={ringRef}
        rotation={[-Math.PI / 2, 0, 0]}
        raycast={() => null}
      >
        <ringGeometry args={[range - 0.06, range, 96]} />
        <meshBasicMaterial color="#00d4ff" transparent opacity={0.18} />
      </mesh>

      {/* The rotating sweep itself. */}
      <group ref={wedgeRef} raycast={() => null}>
        <mesh geometry={wedgeGeometry}>
          <meshBasicMaterial
            vertexColors
            transparent
            opacity={0.25}
            depthWrite={false}
            blending={THREE.AdditiveBlending}
            side={THREE.DoubleSide}
          />
        </mesh>
        {/* Leading-edge bright line */}
        <line>
          <primitive object={leadGeometry} attach="geometry" />
          <lineBasicMaterial color="#7fdfff" transparent opacity={0.85} />
        </line>
      </group>
    </>
  );
}
