import type { CSSProperties } from "react";

import styles from "./Skeleton.module.css";

export type SkeletonProps = {
  className?: string;
  height?: CSSProperties["height"];
  lines?: number;
};

export function Skeleton({ className, height, lines = 1 }: SkeletonProps) {
  const count = Math.max(1, Math.floor(lines));
  return <div aria-hidden="true" className={[styles.group, className].filter(Boolean).join(" ")}>
    {Array.from({ length: count }, (_, index) => <span
      className={styles.line}
      key={index}
      style={{ height, width: index === count - 1 && count > 1 ? "72%" : undefined }}
    />)}
  </div>;
}
