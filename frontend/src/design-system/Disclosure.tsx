import { Children, cloneElement, isValidElement, type ComponentPropsWithRef, type ReactElement } from "react";
import styles from "./Disclosure.module.css";

/** Native keyboard/toggle behavior and mounted content, with an explicit text action. */
export function Disclosure({ children, className = "", ...props }: ComponentPropsWithRef<"details">) {
  return <details {...props} className={`${styles.root} ${className}`}>
    {Children.map(children, child => {
      if (!isValidElement(child) || child.type !== "summary") return child;
      const summary = child as ReactElement<ComponentPropsWithRef<"summary">>;
      return cloneElement(summary, { className: `${styles.summary} ${summary.props.className || ""}` },
        summary.props.children,
        <span className={styles.action} aria-hidden="true"><span className={styles.show}>查看</span><span className={styles.hide}>收起</span></span>,
      );
    })}
  </details>;
}
