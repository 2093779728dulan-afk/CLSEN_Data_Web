import { CircleCheck, CircleDashed, CircleX, TriangleAlert } from "lucide-react";

import styles from "./StatusBadge.module.css";

export type StatusTone = "good" | "warn" | "bad" | "quiet";
export type StatusBadgeProps = { label: string; tone: StatusTone };

const icons = {
  bad: CircleX,
  good: CircleCheck,
  quiet: CircleDashed,
  warn: TriangleAlert,
} as const;

export function StatusBadge({ label, tone }: StatusBadgeProps) {
  const Icon = icons[tone];

  return (
    <span className={`${styles.badge} ${styles[tone]}`}>
      <Icon aria-hidden="true" />
      <span>{label}</span>
    </span>
  );
}
