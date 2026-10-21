import type { ReactNode } from "react";

export type StatusMessageProps = {
  kind: "info" | "success" | "warning" | "danger";
  title: string;
  children?: ReactNode;
  action?: ReactNode;
};

export function StatusMessage({ kind, title, children, action }: StatusMessageProps) {
  return (
    <section className={`ui-status ui-status--${kind}`} role={kind === "danger" ? "alert" : "status"}>
      <div>
        <strong>{title}</strong>
        {children != null ? <span className="ui-status__body">{children}</span> : null}
      </div>
      {action != null ? <div className="ui-status__action">{action}</div> : null}
    </section>
  );
}
