import type { ReactNode } from "react";
import { Dialog } from "../../design-system";
import styles from "./QualityMovementWizard.module.css";
import operationStyles from "./OrderWorkbench.module.css";

export function ProductionOperationDialog({ title, description, close, blocked, children, contentClassName="" }: { title: string; description: ReactNode; close: () => void; blocked?: boolean; children: ReactNode; contentClassName?:string }) {
  return <Dialog open title={title} description={<span className={styles.srOnly}>{description}</span>} closeLabel={`关闭${title}`} size="large" closeOnOutsideClick={false} contentClassName={`${styles.dialog} ${operationStyles.operationDialog} ${contentClassName}`} onOpenChange={open => { if (!open) close(); }}>{blocked === undefined ? children : <fieldset className={`${styles.form} ${styles.fields}`} disabled={blocked}>{blocked && <p role="status">资料尚未重新读取成功，操作已暂停，当前输入保留。</p>}{children}</fieldset>}</Dialog>;
}
