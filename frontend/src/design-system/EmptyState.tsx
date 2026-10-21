import { Inbox } from "lucide-react";
import type { ReactNode } from "react";

import styles from "./StatePanel.module.css";

export type EmptyStateProps = {
  action?: ReactNode;
  description?: ReactNode;
  icon?: ReactNode;
  title: ReactNode;
};

export function EmptyState({ action, description, icon, title }: EmptyStateProps) {
  return <section className={styles.panel}>
    <span aria-hidden="true" className={styles.icon}>{icon ?? <Inbox />}</span>
    <div className={styles.copy}>
      <h3>{title}</h3>
      {description != null ? <p>{description}</p> : null}
    </div>
    {action != null ? <div className={styles.action}>{action}</div> : null}
  </section>;
}
