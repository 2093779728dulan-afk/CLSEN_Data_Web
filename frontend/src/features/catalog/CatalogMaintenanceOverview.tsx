import { ArrowRight, Files, History, ListChecks, PackageSearch, ShieldCheck } from "lucide-react";
import { LinkButton, StatusBadge } from "../../design-system";
import type { CurrentCatalog } from "./catalogApi";
import styles from "./CatalogMaintenanceOverview.module.css";

export function CatalogMaintenanceOverview({ catalog }: { catalog: CurrentCatalog | null }) {
  return <section className={styles.panel} aria-label="批量维护总览">
    <header className={styles.heading}><div><span className={styles.eyebrow}>商品主档 · 维护工作台</span><h2>批量维护</h2><p>{catalog ? `当前生效目录 V${catalog.version_number}。多商品修订在这里生成候选；单商品名称和分类请在商品卡维护。` : "目录尚未初始化。请先确认来源报告已发布，再生成首份候选。"}</p></div><StatusBadge label={catalog ? `已生效 V${catalog.version_number}` : "尚未初始化"} tone={catalog ? "good" : "warn"} /></header>
    <div className={styles.body}>
      {catalog ? <div className={styles.current}><ShieldCheck aria-hidden="true" /><div><h3>当前生效依据</h3><dl className={styles.baseline}><div><dt>目录版本</dt><dd>V{catalog.version_number}</dd></div><div><dt>目录记录</dt><dd>#{catalog.catalog_version_id}</dd></div><div><dt>发布修订</dt><dd>{catalog.catalog_publication_revision}</dd></div></dl></div></div> : <section className={styles.first} aria-label="首个目录前置"><div className={styles.subheading}><Files aria-hidden="true" /><h3>首次建立目录</h3></div><ol className={styles.prerequisites}>
        <li><strong>发布来源报告</strong><p>先在每日核验中导入、审核并发布来源报告。</p><LinkButton variant="quiet" icon={<ArrowRight />} to="/">返回每日数据查看发布情况</LinkButton></li>
        <li><strong>确认范围与快照</strong><p>在下方确认来源账号范围，并建立首次退货快照；生效快照建立后再生成候选。</p></li>
        <li><strong>建立审核草稿</strong><p>选择在线审核（无需文件），或下载修改后上传 XLSX。</p></li>
        <li><strong>核对首个批准版本</strong><p>保存、校验并批准后，返回商品页查看首个目录版本。</p></li>
      </ol></section>}
      <section aria-label="维护流程"><div className={styles.subheading}><ListChecks aria-hidden="true" /><h3>从候选到生效</h3></div><ol className={styles.workflow}>
        <li><span className={styles.step}>1</span><div><strong>生成候选</strong><p>来源报告与准备状态就绪后，建立审核草稿。</p></div></li>
        <li><span className={styles.step}>2</span><div><strong>审核与校验</strong><p>在线审核不需要上传文件；只有离线修改才需要下载并上传 XLSX。</p></div></li>
        <li><span className={styles.step}>3</span><div><strong>批准后生效</strong><p>所有变更须校验、批准后生效。</p></div></li>
      </ol><p className={styles.note}>下方准备状态决定是否可以生成候选；已生效目录不代表新的来源资料已就绪。</p></section>
    </div>
    {catalog && <footer className={styles.footer}><LinkButton icon={<PackageSearch />} to="/catalog">查看已生效商品</LinkButton><LinkButton variant="quiet" icon={<History />} to="/catalog/versions">查看批准记录</LinkButton></footer>}
  </section>;
}
