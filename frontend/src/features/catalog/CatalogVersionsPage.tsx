import { CatalogReadError } from "./CatalogReadFailure";
import { catalogReadError } from "./catalogReadError";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { listCatalogVersions } from "./catalogApi";

function text(value: unknown): string {
  return typeof value === "string" || typeof value === "number" ? String(value) : "—";
}

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
  if (!versions) return <p role="status">正在读取目录版本…</p>;
  return <section className="catalog-panel"><h2>目录版本</h2><p>这里只列出已批准版本；审核草稿不会出现在这里。</p>{versions.length === 0 && <p>尚无已批准目录版本。<Link to="/catalog/maintenance">前往批量维护完成初始化</Link></p>}<div className="catalog-table-scroll"><table><thead><tr><th>版本</th><th>风险</th><th>批准时间</th><th>基础版本</th></tr></thead><tbody>{versions.map((version, index) => <tr key={text(version.id) === "—" ? index : text(version.id)}><td>V{text(version.version_number)}</td><td>{text(version.risk)}</td><td>{text(version.approved_at)}</td><td>{version.base_catalog_version_id === null ? "首次" : text(version.base_catalog_version_id)}</td></tr>)}</tbody></table></div></section>;
}
