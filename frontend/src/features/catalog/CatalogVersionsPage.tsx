import { CatalogReadError } from "./CatalogReadFailure";
import { catalogReadError } from "./catalogReadError";
import { useEffect, useState } from "react";
import { CatalogVersionsView } from "./CatalogVersionsView";

import { listCatalogVersions } from "./catalogApi";

export function CatalogVersionsPage() {
  const [versions, setVersions] = useState<Array<Record<string, unknown>>>();
  const [error, setError] = useState<ReturnType<typeof catalogReadError>>();
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    setError(undefined);
    setVersions(undefined);
    let active = true;
    void listCatalogVersions().then((value) => { if (active) setVersions(value.versions); }).catch((reason: unknown) => { if (active) setError(catalogReadError(reason, "无法读取目录版本，请检查连接后重试。")); });
    return () => { active = false; };
  }, [attempt]);
  if (error) return <CatalogReadError failure={error} onRetry={() => setAttempt(value => value + 1)} />;
  return <CatalogVersionsView versions={versions} onReload={() => setAttempt(value => value + 1)} />;
}
