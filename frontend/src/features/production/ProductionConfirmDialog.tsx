import { Dialog, type DialogProps } from "../../design-system/Dialog";
import { useStockWindowContainer } from "./stockOverview";
import styles from "./Production.module.css";

/** Keep confirmations above both Radix forms and native inventory windows. */
export function ProductionConfirmDialog({ children, contentClassName = "", ...props }: DialogProps) {
  const container = useStockWindowContainer();
  return <Dialog {...props} portalContainer={container} closeOnOutsideClick={false}
    contentClassName={`${styles.productionDialog} ${styles.confirmationDialog} ${contentClassName}`}>
    <div className={styles.guardActions}>{children}</div>
  </Dialog>;
}
