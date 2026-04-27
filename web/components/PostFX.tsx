"use client";

import { EffectComposer, Bloom, Vignette, SSAO } from "@react-three/postprocessing";
import { BlendFunction } from "postprocessing";

/**
 * Post-processing pipeline — applied on top of the scene's normal render.
 *
 *  Bloom    — makes emissive materials (waypoint octahedrons, bandit
 *             bodies, rotor LEDs, intercept bursts) actually glow.
 *             Thresholded so the grid + terrain don't smear.
 *  SSAO     — screen-space ambient occlusion. Adds subtle contact
 *             shadows where geometry meets geometry (drone body on
 *             launch pad, bandits vs. terrain) to sell depth.
 *  Vignette — slight darkening toward the corners for a cinematic feel
 *             without losing tactical readability near the centre.
 *
 * The composer is gated from the store at the call-site, so flipping the
 * toggle off is a zero-cost detach.
 */
export function PostFX({ intensity = "normal" }: { intensity?: "normal" | "cinematic" }) {
  const isCinematic = intensity === "cinematic";

  return (
    <EffectComposer multisampling={0} enableNormalPass>
      {/* Bloom on anything above the luminance threshold.  emissiveIntensity
          on the existing materials already sits around 0.45–0.7, so a 0.9
          threshold picks them up while leaving the HDRI sky alone. */}
      <Bloom
        intensity={isCinematic ? 0.7 : 0.45}
        luminanceThreshold={0.85}
        luminanceSmoothing={0.2}
        mipmapBlur
        radius={0.72}
      />

      {/* SSAO — keep sample count modest so mid-range GPUs still hit 60 fps. */}
      <SSAO
        intensity={isCinematic ? 0.35 : 0.22}
        radius={0.16}
        samples={16}
        rings={4}
        distanceThreshold={1.0}
        distanceFalloff={0.15}
        rangeThreshold={0.003}
        rangeFalloff={0.01}
        blendFunction={BlendFunction.MULTIPLY}
      />

      <Vignette
        eskil={false}
        offset={isCinematic ? 0.25 : 0.2}
        darkness={isCinematic ? 0.55 : 0.4}
      />
    </EffectComposer>
  );
}
