import { motion, useReducedMotion } from "motion/react";
import { useMemo, type ReactNode } from "react";

import styles from "./PageTransition.module.css";

/** Keep new content visible immediately; the route owner retains its remount boundary. */
export function PageTransition({ children }: { children: ReactNode }) {
  const reducedMotion = useReducedMotion();
  const { duration } = useMemo(() => {
    // Client-rendered app: read shared tokens before the first animation frame.
    const tokens = getComputedStyle(document.documentElement);
    return {
      duration: Number.parseFloat(tokens.getPropertyValue("--motion-content-enter")) / 1000 || 0,
    };
  }, []);

  return <motion.div className={styles.page} initial={false}
    animate={{ opacity: 1, y: 0 }} transition={{ duration: reducedMotion ? 0 : duration, ease: [0.2, 0, 0, 1] }}>
    {children}
  </motion.div>;
}
