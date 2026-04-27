import type { Transition, Variants } from "framer-motion";

export { AnimatePresence, motion, useReducedMotion } from "framer-motion";

export const springSnappy: Transition = {
  type: "spring",
  stiffness: 320,
  damping: 22,
  mass: 0.6,
};

export const springSoft: Transition = {
  type: "spring",
  stiffness: 180,
  damping: 24,
  mass: 0.8,
};

export const easeOutFast: Transition = {
  duration: 0.18,
  ease: [0.22, 1, 0.36, 1],
};

export const overlayFade: Variants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: easeOutFast },
  exit: { opacity: 0, transition: { duration: 0.12, ease: "easeIn" } },
};

export const paletteReveal: Variants = {
  hidden: { opacity: 0, scale: 0.96, y: -6 },
  visible: { opacity: 1, scale: 1, y: 0, transition: springSnappy },
  exit: { opacity: 0, scale: 0.97, y: -4, transition: { duration: 0.1 } },
};

export const panelReveal: Variants = {
  hidden: { opacity: 0, y: 8 },
  visible: { opacity: 1, y: 0, transition: springSoft },
  exit: { opacity: 0, y: 6, transition: { duration: 0.12 } },
};
