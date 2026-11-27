import { Disclosure } from "../../design-system";
import { Check } from "lucide-react";
import type { ReactNode } from "react";
import { Button } from "../../design-system";
import styles from "./QualityMovementWizard.module.css";

export function GuidedOperationLayout({ step, steps, summaries, contextTitle, context, title, lead, reference, busy, unknown, go, children, actions, footerNote, wide=false }: {
  step: number;
  steps: string[];
  summaries: string[];
  contextTitle: string;
  context: ReactNode;
  title: string;
  lead: string;
  reference?: ReactNode;
  busy: boolean;
  unknown: boolean;
  go: (step: number) => void;
  children: ReactNode;
  actions: ReactNode;
  footerNote: string;
  wide?:boolean;
}) {
  return <>
    <div className={`${styles.layout} ${wide?styles.wide:""}`}>
      <aside className={styles.rail}>
        <ol aria-label="操作步骤" style={wide?{gridTemplateColumns:`repeat(${steps.length},minmax(0,1fr))`}:undefined}>{steps.map((label, index) => <li key={label} aria-current={step === index ? "step" : undefined} data-complete={index < step}>
          <Button type="button" variant="quiet" disabled={busy || unknown || index > step} onClick={() => go(index)}>
            <span><span className={styles.marker}>{index < step ? <Check size={16} aria-hidden="true" /> : index + 1}</span><span><strong>{label}</strong><small>{summaries[index]}</small>{index < step && <span className={styles.edit}>修改</span>}</span></span>
          </Button>
        </li>)}</ol>
      </aside>
      <main className={styles.main}>
        <header className={styles.stepHeader}><h2>{title}</h2><Disclosure className={styles.help} key={step}><summary>填写说明</summary><p>{lead}</p><p>{footerNote}</p>{!reference && <div><strong>{contextTitle}</strong>{context}</div>}</Disclosure></header>
        {reference}
        {children}
      </main>
    </div>
    <footer className={styles.footer}><div>{actions}</div></footer>
  </>;
}
