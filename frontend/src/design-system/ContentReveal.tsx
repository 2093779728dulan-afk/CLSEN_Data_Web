import { motion, useReducedMotion } from "motion/react";
import { useMemo, type ReactNode } from "react";

/** Motion enter pattern. Keep mounted during refresh to retain focus and layout. */
export function ContentReveal({ children, className }: { children: ReactNode; className?: string }) {
  const reduce = useReducedMotion();
  const duration = useMemo(() => Number.parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--motion-content-enter")) / 1000 || 0, []);
  return <motion.div className={className} initial={reduce ? false : { opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: reduce ? 0 : duration, ease: [0.2, 0, 0, 1] }}>{children}</motion.div>;
}
