import * as ToastPrimitive from "@radix-ui/react-toast";
import { CircleCheck, CircleX, Info, TriangleAlert, X } from "lucide-react";
import type { ReactNode } from "react";

import styles from "./Toast.module.css";

type ToastKind = "info" | "success" | "warning" | "danger";

export type ToastAction = {
  label: string;
  onSelect: () => void;
};

export type ToastProps = {
  action?: ToastAction;
  children?: ReactNode;
  duration?: number;
  kind: ToastKind;
  onOpenChange: (open: boolean) => void;
  open: boolean;
  title: string;
};

export type ToastProviderProps = {
  children: ReactNode;
  label?: string;
};

const KIND_META = {
  info: { Icon: Info, label: "信息" },
  success: { Icon: CircleCheck, label: "成功" },
  warning: { Icon: TriangleAlert, label: "警告" },
  danger: { Icon: CircleX, label: "错误" },
} satisfies Record<ToastKind, { Icon: typeof Info; label: string }>;

export function ToastProvider({ children, label = "通知" }: ToastProviderProps) {
  return <ToastPrimitive.Provider swipeDirection="right">
    {children}
    <ToastPrimitive.Viewport className={styles.viewport} label={label} />
  </ToastPrimitive.Provider>;
}

export function Toast({ action, children, duration = 5000, kind, onOpenChange, open, title }: ToastProps) {
  const { Icon, label } = KIND_META[kind];
  return <ToastPrimitive.Root
    className={`${styles.toast} ${styles[kind]}`}
    duration={duration}
    onOpenChange={onOpenChange}
    open={open}
    type={kind === "danger" ? "foreground" : "background"}
  >
    <Icon aria-hidden="true" className={styles.icon} />
    <div className={styles.copy}>
      <span className={styles.kind}>{label}</span>
      <ToastPrimitive.Title className={styles.title}>{title}</ToastPrimitive.Title>
      {children != null ? <ToastPrimitive.Description className={styles.description}>{children}</ToastPrimitive.Description> : null}
    </div>
    {action ? <ToastPrimitive.Action altText={action.label} asChild>
      <button className={styles.action} onClick={action.onSelect} type="button">{action.label}</button>
    </ToastPrimitive.Action> : null}
    <ToastPrimitive.Close aria-label="关闭通知" className={styles.close}>
      <X aria-hidden="true" />
    </ToastPrimitive.Close>
  </ToastPrimitive.Root>;
}
