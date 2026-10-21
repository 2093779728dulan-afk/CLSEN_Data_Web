import { LayoutGroup, motion, useReducedMotion } from "motion/react";
import { useId, useLayoutEffect, useRef, useState } from "react";
import { NavLink } from "react-router-dom";

import styles from "./RouteNavigation.module.css";

export type RouteNavigationItem = { end?: boolean; label: string; to: string };
export type RouteNavigationProps = { ariaLabel: string; items: RouteNavigationItem[] };

/** Adapts Motion's shared underline example while retaining native route links. */
export function RouteNavigation({ ariaLabel, items }: RouteNavigationProps) {
  const groupId = useId();
  const nav = useRef<HTMLElement>(null);
  const reducedMotion = useReducedMotion();
  const [duration, setDuration] = useState(0);
  useLayoutEffect(() => {
    if (nav.current) {
      // Motion requires seconds; the shared CSS token remains the source of timing.
      const token = getComputedStyle(nav.current).getPropertyValue("--motion-content-enter");
      setDuration(Number.parseFloat(token) / 1000 || 0);
    }
  }, []);

  return <LayoutGroup id={groupId}>
    <motion.nav ref={nav} layoutScroll aria-label={ariaLabel} className={styles.nav}>
      {items.map(item => <NavLink className={styles.link} end={item.end} key={item.to} to={item.to}
        onFocus={event => event.currentTarget.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "instant" })}>
        {({ isActive }) => <>
          <span>{item.label}</span>
          {isActive && <motion.span aria-hidden="true" className={styles.indicator}
            initial={false} layoutId="underline"
            transition={{ type: "tween", duration: reducedMotion ? 0 : duration, ease: [0.2, 0, 0, 1] }} />}
        </>}
      </NavLink>)}
    </motion.nav>
  </LayoutGroup>;
}
