"use client";

import { useMemo } from "react";
import * as THREE from "three";

/**
 * Procedurally-generated rolling terrain under the tactical grid.
 *
 * A 60x60 m displaced plane, height driven by 2-octave value noise so it
 * reads as gentle hills without clipping through the waypoint layer (peaks
 * stay below ~0.5 m).  Vertex colors ramp from shadowed valley to sunlit
 * ridge + snow caps, tinted to match the room palette.  The infinite grid
 * still sits on top at y=0 as the tactical reference plane.
 */

// --- Deterministic value noise (no external dep) ----------------------- //
function hash2(x: number, y: number): number {
  // Quick-and-ugly pseudo-random hash, stable across re-renders.
  const n = Math.sin(x * 127.1 + y * 311.7) * 43758.5453;
  return n - Math.floor(n);
}

function smooth(t: number): number {
  return t * t * (3 - 2 * t);
}

function valueNoise(x: number, y: number): number {
  const xi = Math.floor(x), yi = Math.floor(y);
  const xf = x - xi,       yf = y - yi;
  const a = hash2(xi,     yi);
  const b = hash2(xi + 1, yi);
  const c = hash2(xi,     yi + 1);
  const d = hash2(xi + 1, yi + 1);
  const u = smooth(xf), v = smooth(yf);
  return (
    a * (1 - u) * (1 - v) +
    b * u * (1 - v) +
    c * (1 - u) * v +
    d * u * v
  );
}

function fbm(x: number, y: number): number {
  // 2 octaves is enough for gentle hills; higher smear is wasted at this scale.
  return 0.65 * valueNoise(x * 0.35, y * 0.35)
       + 0.35 * valueNoise(x * 0.9,  y * 0.9);
}

// --- Palette mapped per room mode -------------------------------------- //
const TERRAIN_PALETTES = {
  range:    { low: "#0a1a2a", mid: "#3d5c3a", high: "#5f7a4d", snow: "#c8dbef" },
  night:    { low: "#07101c", mid: "#1b2340", high: "#353e68", snow: "#95a4d9" },
  analysis: { low: "#0a1812", mid: "#2a4637", high: "#4c6a4c", snow: "#c4e6cf" },
} as const;

type TerrainMode = keyof typeof TERRAIN_PALETTES;

export function Terrain({ mode = "range" }: { mode?: TerrainMode }) {
  const geometry = useMemo(() => {
    const SIZE = 60;
    const SEG  = 120;
    const AMP  = 0.45;      // peak-to-trough amplitude in metres
    const geo  = new THREE.PlaneGeometry(SIZE, SIZE, SEG, SEG);
    geo.rotateX(-Math.PI / 2);       // lay flat in Y-up three-space

    const pos = geo.attributes.position as THREE.BufferAttribute;
    const colors = new Float32Array(pos.count * 3);
    const palette = TERRAIN_PALETTES[mode];
    const cLow  = new THREE.Color(palette.low);
    const cMid  = new THREE.Color(palette.mid);
    const cHigh = new THREE.Color(palette.high);
    const cSnow = new THREE.Color(palette.snow);

    for (let i = 0; i < pos.count; i++) {
      const x = pos.getX(i);
      const z = pos.getZ(i);
      // Distance-modulated falloff so the centre (tactical area) is
      // essentially flat and displacement ramps up toward the horizon.
      const rNorm = Math.min(1, Math.hypot(x, z) / (SIZE / 2));
      const falloff = smooth(Math.max(0, (rNorm - 0.08) / 0.92));
      const h = (fbm(x, z) - 0.5) * 2 * AMP * falloff;
      pos.setY(i, h);

      // Height -> colour ramp
      const norm = (h + AMP) / (2 * AMP);  // 0..1
      const c = new THREE.Color();
      if (norm < 0.35) {
        c.copy(cLow).lerp(cMid, norm / 0.35);
      } else if (norm < 0.75) {
        c.copy(cMid).lerp(cHigh, (norm - 0.35) / 0.4);
      } else {
        c.copy(cHigh).lerp(cSnow, (norm - 0.75) / 0.25);
      }
      colors[i * 3]     = c.r;
      colors[i * 3 + 1] = c.g;
      colors[i * 3 + 2] = c.b;
    }
    geo.setAttribute("color", new THREE.BufferAttribute(colors, 3));
    geo.computeVertexNormals();
    return geo;
  }, [mode]);

  return (
    <mesh
      geometry={geometry}
      position={[0, -0.08, 0]}
      receiveShadow
      // Terrain is purely decorative — never fight the edit plane for pointer events.
      raycast={() => null}
    >
      <meshStandardMaterial
        vertexColors
        roughness={0.92}
        metalness={0.02}
        flatShading={false}
      />
    </mesh>
  );
}
