import { motion, useReducedMotion } from "motion/react";
import { useMemo, type ReactNode } from "react";

import styles from "./PageTransition.module.css";

/** Motion's enter pattern; the route owner retains its existing remount boundary. */
export function PageTransition({ children }: { children: ReactNode }) {
  const reducedMotion = useReducedMotion();
  const { duration, distance } = useMemo(() => {
    // Client-rendered app: read shared tokens before the first animation frame.
    const tokens = getComputedStyle(document.documentElement);
    return {
      duration: Number.parseFloat(tokens.getPropertyValue("--motion-content-enter")) / 1000 || 0,
      distance: Number.parseFloat(tokens.getPropertyValue("--space-2")) || 0,
    };
  }, []);

  return <motion.div className={styles.page} initial={reducedMotion ? false : { opacity: 0, y: distance }}
    animate={{ opacity: 1, y: 0 }} transition={{ duration: reducedMotion ? 0 : duration, ease: [0.2, 0, 0, 1] }}>
    {children}
  </motion.div>;
}
