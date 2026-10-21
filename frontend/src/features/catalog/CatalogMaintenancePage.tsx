import { CatalogSetup } from "./CatalogSetup";
import { Link } from "react-router-dom";
import { useEffect, useState } from "react";

import { getCurrentCatalog, type CurrentCatalog } from "./catalogApi";
import { CatalogExportPanel } from "./CatalogExportPanel";
import { CatalogImportHistory } from "./CatalogImportHistory";

export function CatalogMaintenancePage() {
  const [catalog, setCatalog] = useState<CurrentCatalog | null>();
  const [generationReady, setGenerationReady] = useState(false);
  const [error, setError] = useState<string>();
  useEffect(() => {
    let active = true;
    void getCurrentCatalog().then((value) => { if (active) setCatalog(value); }).catch((reason: unknown) => {
      if (active) setError(reason instanceof Error ? reason.message : "无法读取当前目录。");
    });
    return () => { active = false; };
  }, []);
  if (error) return <p role="alert">{error}</p>;
  if (catalog === undefined) return <p role="status">正在读取批量维护…</p>;
  return <div className="catalog-stack"><section className="catalog-panel"><h2>批量维护</h2><p>{catalog ? `当前生效目录 V${catalog.version_number}。多商品修订在这里生成候选；单商品名称和分类请在商品卡维护。` : "目录尚未初始化。请先确认来源报告已发布，再生成首份候选。"}</p>{!catalog && <ol><li>先在每日核验中导入、审核并发布来源报告。<Link to="/">返回每日数据查看发布情况</Link></li><li>在下方确认来源账号范围，并建立首次退货快照；生效快照建立后再生成候选。</li><li>选择在线审核（无需文件），或下载修改后上传 XLSX。</li><li>保存、校验并批准后，返回商品页查看首个目录版本。</li></ol>}<p>在线审核不需要上传文件；只有离线修改才需要下载并上传 XLSX。所有变更须校验、批准后生效。</p></section><CatalogSetup editable onGenerationReady={setGenerationReady} /><CatalogImportHistory /><CatalogExportPanel generationReady={generationReady} catalogPublicationRevision={catalog?.catalog_publication_revision ?? 0} /></div>;
}

