import type { Config } from "tailwindcss";

/**
 * Dark ops-tactical theme — mirrors the Streamlit dashboard's PALETTE so
 * the new web app feels like a continuation of the same product, not a
 * different tool. Tokens are exposed as `bg-bg`, `text-cyan`, etc.
 */
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg:        "#0a0e1a",
        panel:     "#141a2e",
        "panel-2": "#1b2238",
        text:      "#e1e8f0",
        muted:     "#8aa0b8",
        cyan:      "#00d4ff",
        amber:     "#ffc107",
        green:     "#2ecc71",
        violet:    "#b388ff",
        pink:      "#ff4081",
        red:       "#ff5252",
        // semantic aliases for the entity types
        bandit:    "#ff5252",
        zone:      "#ffc107",
        nofly:     "#ff5252",
        threat:    "#ffc107",
      },
      fontFamily: {
        sans: ["Inter", "Segoe UI", "Helvetica", "Arial", "sans-serif"],
        mono: ["JetBrains Mono", "Consolas", "monospace"],
      },
      boxShadow: {
        card: "0 4px 16px -4px rgba(0, 0, 0, 0.55)",
        glow: "0 0 24px -6px rgba(0, 212, 255, 0.45)",
      },
      borderRadius: {
        lg: "0.625rem",
      },
    },
  },
  plugins: [],
};

export default config;
