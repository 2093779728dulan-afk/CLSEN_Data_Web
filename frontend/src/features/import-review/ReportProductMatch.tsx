import { Disclosure } from "../../design-system";
import { useEffect, useState } from "react";
import { requestApi } from "../../api/client";
import { useAuthzGeneration } from "../../app/AuthzGenerationContext";
import { Button, StatusMessage, Table } from "../../design-system";

import { CatalogGuidedFlow } from "../catalog/CatalogGuidedFlow";

type Match = { matched: number; excluded: number; total: number; issues: { seller_sku: string; message: string }[] };

export function ReportProductMatch({ versionId, revision }: { versionId: number; revision: number }) {
  const { generation } = useAuthzGeneration();
  const [result, setResult] = useState<Match>();
  const [error, setError] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [repair, setRepair] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    setResult(undefined); setError(false);
    void requestApi<Match>(`/api/catalog/report-matching/${versionId}`, { signal: controller.signal }).then(value => {
      if (!controller.signal.aborted) setResult(value);
    }).catch(() => { if (!controller.signal.aborted) setError(true); });
    return () => controller.abort();
  }, [versionId, revision, generation, refresh]);
  useEffect(() => {
    const update = () => setRefresh(value => value + 1);
    window.addEventListener("focus", update);
    return () => window.removeEventListener("focus", update);
  }, []);
  if (error) return <StatusMessage kind="warning" title="商品关联尚未读取完成" action={<Button onClick={() => setRefresh(value => value + 1)}>重新读取</Button>} />;
  if (!result) return <p role="status">正在匹配报表商品…</p>;
  return <section aria-label="报表商品匹配">
    <p role="status">已匹配{result.matched}个商品{result.excluded > 0 && ` · 已排除${result.excluded}个`}{result.issues.length > 0 && ` · ${result.issues.length}个需处理`}</p>
    {result.issues.length > 0 && <Disclosure><summary>查看需处理商品</summary>
      <Table title="需处理商品"><thead><tr><th>Seller SKU</th><th>问题</th></tr></thead><tbody>{result.issues.map((item, index) => <tr key={index}><td>{item.seller_sku}</td><td>{item.message}</td></tr>)}</tbody></Table>
      <Button variant="secondary" onClick={() => setRepair(true)}>补充商品关联</Button><Button variant="quiet" onClick={() => setRefresh(value => value + 1)}>刷新匹配结果</Button>
    </Disclosure>}
    {repair && <CatalogGuidedFlow initialMode="product" autoOpen onClosed={() => { setRepair(false); setRefresh(value => value + 1); }} />}
  </section>;
}
