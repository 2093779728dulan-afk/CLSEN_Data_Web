import * as DialogPrimitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { useEffect, useRef, type ReactNode } from "react";

import styles from "./Dialog.module.css";

export type DialogProps = {
  children: ReactNode;
  accessibleLabel?: string;
  dismissDisabled?: boolean;
  contentClassName?: string;
  closeLabel?: string;
  description?: ReactNode;
  eyebrow?: ReactNode;
  onOpenChange: (open: boolean) => void;
  open: boolean;
  size?: "medium" | "large";
  presentation?: "dialog" | "drawer";
  title: ReactNode;
};

export function Dialog({
  children,
  accessibleLabel,
  dismissDisabled = false,
  contentClassName = "",
  closeLabel = "关闭对话框",
  description,
  eyebrow,
  onOpenChange,
  open,
  size = "medium",
  presentation = "dialog",
  title,
}: DialogProps) {
  const returnFocusRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (open && document.activeElement instanceof HTMLElement) {
      returnFocusRef.current = document.activeElement;
    }
  }, [open]);

  return (
    <DialogPrimitive.Root onOpenChange={open => { if (!dismissDisabled || open) onOpenChange(open); }} open={open}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className={styles.overlay} />
        <DialogPrimitive.Content
          {...(accessibleLabel ? { "aria-labelledby": undefined, "aria-label": accessibleLabel } : {})}
          onEscapeKeyDown={event => { if (dismissDisabled) event.preventDefault(); }}
          onPointerDownOutside={event => { if (dismissDisabled) event.preventDefault(); }}
          className={`${styles.content} ${styles[size]} ${presentation === "drawer" ? styles.drawer : ""} ${contentClassName}`}
          onCloseAutoFocus={(event) => {
            if (!returnFocusRef.current) return;
            event.preventDefault();
            returnFocusRef.current.focus();
          }}
        >
          <header className={styles.header}>
            <div>
              {eyebrow != null ? <p className={styles.eyebrow}>{eyebrow}</p> : null}
              <DialogPrimitive.Title className={styles.title}>{title}</DialogPrimitive.Title>
              {description != null ? <DialogPrimitive.Description className={styles.description}>{description}</DialogPrimitive.Description> : null}
            </div>
            <DialogPrimitive.Close disabled={dismissDisabled} aria-label={closeLabel} className={styles.close}>
              <X aria-hidden="true" />
            </DialogPrimitive.Close>
          </header>
          <div className={styles.body}>{children}</div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
