import { CatalogSetup } from "./CatalogSetup";
import { CatalogMaintenanceOverview } from "./CatalogMaintenanceOverview";
import { Skeleton } from "../../design-system";
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
  if (catalog === undefined) return <div><p role="status">正在读取批量维护…</p><Skeleton lines={4} /></div>;
  return <div className="catalog-stack"><CatalogMaintenanceOverview catalog={catalog} /><CatalogSetup editable onGenerationReady={setGenerationReady} /><CatalogImportHistory /><CatalogExportPanel generationReady={generationReady} catalogPublicationRevision={catalog?.catalog_publication_revision ?? 0} /></div>;
}

