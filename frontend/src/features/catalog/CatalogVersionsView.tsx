import { FileCheck2, GitBranch, RefreshCw } from "lucide-react";
import { Button, EmptyState, LinkButton, Skeleton, StatusBadge, Table } from "../../design-system";
import styles from "./CatalogVersionsView.module.css";

function text(value: unknown): string { return typeof value === "string" || typeof value === "number" ? String(value) : "—"; }

export function CatalogVersionsView({ versions, onReload }: { versions?: Array<Record<string, unknown>>; onReload: () => void }) {
  if (!versions) return <section className={styles.loading} aria-label="目录版本记录" aria-busy="true"><div className={styles.loadingTitle}><FileCheck2 aria-hidden="true" /><h2>目录版本</h2></div><p role="status">正在读取目录版本…</p><Skeleton lines={4} /></section>;
  return <section className={styles.panel} aria-label="目录版本记录">
    <header className={styles.heading}>
      <div><span className={styles.eyebrow}>商品主档 · 批准记录</span><h2>目录版本</h2><p>这里只列出已批准版本；审核草稿不会出现在这里。</p></div>
      <Button icon={<RefreshCw />} onClick={onReload}>重新读取版本</Button>
    </header>
    <div className={styles.body}>{versions.length === 0 ? <EmptyState icon={<FileCheck2 />} title="尚无已批准目录版本" description="完成候选校验与批准后，新的目录版本会出现在这里。" action={<LinkButton to="/catalog/maintenance">前往批量维护完成初始化</LinkButton>} /> : <>
      <p className={styles.mobileHint}>可横向滚动查看完整批准记录。</p>
      <Table className={styles.table} title="已批准目录记录" description={`共 ${versions.length} 个版本。基础版本用于追溯修订来源，不表示草稿已生效。`}>
        <thead><tr><th scope="col">版本</th><th scope="col">风险</th><th scope="col">批准时间</th><th scope="col">基础版本</th></tr></thead>
        <tbody>{versions.map((version, index) => <tr key={text(version.id) === "—" ? index : text(version.id)}>
          <td><div className={styles.version}><FileCheck2 aria-hidden="true" /><div><strong>V{text(version.version_number)}</strong><span>目录记录 #{text(version.id)}</span></div></div></td>
          <td><StatusBadge label={version.risk === "normal" ? "正常" : text(version.risk)} tone={version.risk === "normal" ? "good" : "quiet"} /></td>
          <td className={styles.date}>{text(version.approved_at)}</td><td>{version.base_catalog_version_id === null ? <StatusBadge label="首次" tone="quiet" /> : <span className={styles.base}><GitBranch aria-hidden="true" /><span>{text(version.base_catalog_version_id) === "—" ? "—" : `目录记录 #${text(version.base_catalog_version_id)}`}</span></span>}</td>
        </tr>)}</tbody>
      </Table>
      <p className={styles.note}><GitBranch aria-hidden="true" /><span>基础版本按目录记录编号追溯；列表顺序沿用读取结果，不据此判断当前生效版本。</span></p>
    </>}</div>
  </section>;
}
