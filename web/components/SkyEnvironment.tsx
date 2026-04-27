"use client";

import { Environment } from "@react-three/drei";

/**
 * HDRi sky + image-based lighting.
 *
 * Swaps the flat radial-gradient background for a real environment map
 * loaded from drei's Poly Haven mirror.  Beyond the pretty skybox, the
 * map also drives the scene's specular reflections — the drone chassis,
 * waypoint octahedrons, and bandit bodies pick up real IBL highlights
 * without any extra lighting config.
 *
 * Each room mode gets a preset that matches its vibe:
 *   range    -> dawn      (warm golden hour, clear range feel)
 *   night    -> night     (dark indigo sky, blue fill light)
 *   analysis -> warehouse (neutral industrial cubemap, even exposure)
 */

type SceneRoomMode = "range" | "night" | "analysis";

const PRESET_BY_MODE: Record<SceneRoomMode, "dawn" | "night" | "warehouse"> = {
  range: "dawn",
  night: "night",
  analysis: "warehouse",
};

export function SkyEnvironment({
  mode,
  showBackground = true,
}: {
  mode: SceneRoomMode;
  showBackground?: boolean;
}) {
  return (
    <Environment
      preset={PRESET_BY_MODE[mode]}
      background={showBackground}
      // Slight blur softens the horizon so the skybox reads as atmosphere,
      // not a photographic panorama.
      backgroundBlurriness={0.18}
      environmentIntensity={0.9}
    />
  );
}
