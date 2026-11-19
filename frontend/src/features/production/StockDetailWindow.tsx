import { useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { Button } from "../../design-system";
import styles from "./SkuAcrossWarehouses.module.css";

import { StockWindowContainer } from "./stockOverview";

/** Keep the original forms mounted when minimized, with one native modal/focus scope. */
export function StockDetailWindow({ open, title, closeLabel, dismissDisabled, onClose, returnFocus, viewKey, compact = false, children }: {
  open: boolean; compact?: boolean; title: string; closeLabel: string; dismissDisabled: boolean;
  onClose: () => void; returnFocus: HTMLElement | null; viewKey: string; children: ReactNode;
}) {
  const [element, setElement] = useState<HTMLDialogElement | null>(null);
  const titleId = useId();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  useEffect(() => () => { if (returnFocus?.isConnected) returnFocus.focus({ preventScroll: true }); }, [returnFocus]);
  useLayoutEffect(() => { if (bodyRef.current) bodyRef.current.scrollTop = 0; }, [viewKey]);
  useLayoutEffect(() => {
    if (!element) return;
    if (open && !element.open) element.showModal();
    else if (!open && element.open) {
      element.close();
      if (returnFocus?.isConnected) returnFocus.focus({ preventScroll: true });
    }
  }, [open, returnFocus, element]);
  useLayoutEffect(() => {
    if (!open) return;
    const body = document.body;
    const previous = { overflow: body.style.overflow, paddingRight: body.style.paddingRight };
    const gap = Math.max(0, window.innerWidth - document.documentElement.clientWidth);
    const padding = Number.parseFloat(getComputedStyle(body).paddingRight) || 0;
    body.style.overflow = "hidden";
    if (gap) body.style.paddingRight = `${padding + gap}px`;
    return () => { body.style.overflow = previous.overflow; body.style.paddingRight = previous.paddingRight; };
  }, [open]);
  useLayoutEffect(() => { if (open) headingRef.current?.focus({preventScroll:true}); }, [open, viewKey]);
  return createPortal(<dialog ref={setElement} className={styles.detailWindow} data-compact={compact||undefined} aria-labelledby={titleId}
    onCancel={event => { event.preventDefault(); if (!dismissDisabled) onClose(); }}>
    <header className={styles.windowHeader}><h2 ref={headingRef} tabIndex={-1} id={titleId}>{title}</h2>
      <Button variant="quiet" aria-label={closeLabel} disabled={dismissDisabled} icon={<X size={20} />} onClick={onClose} />
    </header>
    <StockWindowContainer.Provider value={element}><div ref={bodyRef} className={styles.windowBody} data-stock-window-scroll>{children}</div></StockWindowContainer.Provider>
  </dialog>, document.body);
}
