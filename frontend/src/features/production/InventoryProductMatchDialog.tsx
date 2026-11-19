import { useEffect, useState, type RefObject } from "react";
import { Link } from "react-router-dom";
import { ApiRequestError, requestApi } from "../../api/client";
import { RequestGate } from "../../api/requestGate";
import { useAuthzGeneration } from "../../app/AuthzGenerationContext";
import { Button, Dialog, FormField, StatusMessage } from "../../design-system";
import type { Edit, ProductLink, Review } from "./InventoryReviewDialog";
import type { StockRow } from "./InventorySnapshotPage";
import { inventoryColor, inventorySizes } from "./inventoryPreparation";
import { units } from "./types";
import styles from "./Production.module.css";

type Match = {
  status: "matched" | "not_found" | "ambiguous" | "disabled" | "source_incomplete" | "catalog_unavailable";
  review_id: string; review_revision: number; catalog_version_id: string | null; catalog_publication_revision: string | null;
  source: { source_key: string; cell: string; style_code: string; color: string; size: string; units: string | null };
  association_saved: boolean; saved_association?: ProductLink | null; association_current?: boolean; posting_enabled: false;
  candidates: { style_id: string; sku_id: string; style_code: string; standard_name: string; standard_color: string; standard_size: string; code: string | null; active: boolean }[];
};
const messages: Record<Match["status"], string> = {
  matched: "已找到相同规格的商品",
  not_found: "当前本地商品中未找到相同规格",
  ambiguous: "找到多个相同规格，需进一步核对",
  disabled: "对应商品已停用",
  source_incomplete: "来源款号或颜色需要先核对",
  catalog_unavailable: "当前站点尚无已批准的商品目录",
};
function firstSize(row: StockRow) {
  return inventorySizes.find(size => row.quantities[size]?.state === "LITERAL" && row.quantities[size]?.units !== "0") || "M";
}

export function InventoryProductMatchDialog({ review, rows, onClose, onRefresh, onEdit, returnFocusTarget }: {
  review: Review; rows: StockRow[]; onClose: () => void; onRefresh?: () => void; onEdit?: (edit: Edit) => void; returnFocusTarget: RefObject<HTMLButtonElement | null>;
}) {
  const [sourceKey, setSourceKey] = useState(rows[0]!.source_key);
  const [size, setSize] = useState<string>(firstSize(rows[0]!));
  const [result, setResult] = useState<Match>();
  const [error, setError] = useState<{ message: string; stale: boolean }>();
  const [attempt, setAttempt] = useState(0);
  const { generation, registerSensitivePurge } = useAuthzGeneration();
  useEffect(() => registerSensitivePurge(() => { setResult(undefined); onClose(); }), [registerSensitivePurge, onClose]);
  useEffect(() => {
    const gate = new RequestGate();
    const ticket = gate.begin([review.review_id, review.revision, sourceKey, size, attempt], generation);
    setResult(undefined); setError(undefined);
    const params = new URLSearchParams({ expected_revision: String(review.revision), source_key: sourceKey, size });
    void requestApi<Match>(`/api/production/inventory-reviews/${review.review_id}/product-match?${params}`, { signal: ticket.signal })
      .then(value => { if (ticket.isCurrent()) setResult(value); })
      .catch(reason => {
        if (ticket.isCurrent()) setError({ message: reason instanceof Error && /[\u3400-\u9fff]/.test(reason.message) ? reason.message : "商品对应暂时无法读取，请稍后重试。", stale: reason instanceof ApiRequestError && reason.status === 409 });
      });
    return () => gate.dispose();
  }, [review.review_id, review.revision, sourceKey, size, attempt, generation]);
  return <Dialog contentClassName={styles.productionDialog} open title="库存商品对应" description="按所选款号、颜色和尺码查看当前已批准的商品。" size="large" onOpenChange={open => { if (!open) onClose(); }} returnFocusTarget={returnFocusTarget}>
    <div className={styles.inventoryEvidence}>
    <div className={styles.fields}>
      <FormField label="来源颜色"><select value={sourceKey} onChange={event => { setSourceKey(event.target.value); setSize(firstSize(rows.find(row => row.source_key === event.target.value)!)); }}>{rows.map(row => <option key={row.source_key} value={row.source_key}>{row.style_code} · {inventoryColor(row) || "颜色待核"} · 第{row.source_row}行</option>)}</select></FormField>
      <FormField label="尺码"><select value={size} onChange={event => setSize(event.target.value)}>{inventorySizes.map(value => <option key={value} value={value}>{value}</option>)}</select></FormField>
    </div>
    {result?.saved_association && <StatusMessage kind={result.association_current ? "success" : "warning"} title="已保存商品对应"><p>{result.saved_association.code || "正式SKU待补"} · 商品规格身份 #{result.saved_association.sku_id} · 保存时目录版本{result.saved_association.catalog_version_id}</p>{!result.association_current && <p>与当前目录不再一致或商品已停用，请重新核对；原对应不会自动改绑。</p>}{review.can_manage && onEdit && <Button variant="quiet" onClick={() => { onEdit({ mode: "product", rows: [rows.find(row => row.source_key === sourceKey)!], product: { size, value: null, label: "解除对应" }, returnFocusTarget: returnFocusTarget.current }); onClose(); }}>解除此尺码对应</Button>}</StatusMessage>}
    {error ? <StatusMessage kind="danger" title="商品对应读取未完成">{error.message}<Button onClick={() => { if (error.stale) { onClose(); if (onRefresh) onRefresh(); else window.location.reload(); } else setAttempt(value => value + 1); }}>{error.stale ? "刷新库存资料" : "重新读取"}</Button></StatusMessage> : !result ? <StatusMessage kind="info" title="正在核对商品…" /> : <>
      <p>来源：{result.source.style_code} · {result.source.color} / {result.source.size}，数量{result.source.units === null ? "待核" : units(result.source.units) + "件"}（{result.source.cell || "未记录单元格"}）</p>
      <StatusMessage kind={result.status === "matched" ? "success" : "warning"} title={messages[result.status]}>{result.status === "not_found" ? "保留库存原文，后续核对商品覆盖；不按近似颜色或拼接SKU自动建档。" : result.status === "matched" ? "规格相符，可打开商品详情继续核对。" : "当前结果保留待处理，不自动选择或创建商品。"}</StatusMessage>
      {result.candidates.map(candidate => <section className={styles.panel} key={candidate.sku_id} aria-label={"对应商品 " + (candidate.code || "正式SKU待补")}>
        <strong>{candidate.code || "正式SKU待补"}</strong>
        <p>{candidate.style_code} · {candidate.standard_color} / {candidate.standard_size} · {candidate.standard_name || "名称待补"}</p>
        <p className={styles.reviewHint}>商品规格身份 #{candidate.sku_id} · 目录版本{result.catalog_version_id} · {candidate.active ? "已启用" : "已停用"}</p>
        {review.can_manage && onEdit && result.status === "matched" && !result.association_current && <Button onClick={() => { onEdit({ mode: "product", rows: [rows.find(row => row.source_key === sourceKey)!], product: { size, value: { sku_id: candidate.sku_id, catalog_version_id: result.catalog_version_id!, catalog_publication_revision: result.catalog_publication_revision! }, label: (candidate.code || "正式SKU待补") + " · " + candidate.standard_color + " / " + candidate.standard_size }, returnFocusTarget: returnFocusTarget.current }); onClose(); }}>确认此尺码商品对应</Button>}
        <Link to={`/catalog/styles/${candidate.style_id}`}>查看商品详情</Link>
      </section>)}
    </>}
    <p className={styles.reviewHint}>{result?.association_saved ? "已保存的对应保留在核对单中；库存账仍未启用。" : "尚未保存正式关联；有管理权限时可确认此尺码对应。"} 保存对应不会更改库存数量。</p>
    <div className={styles.dialogActions}><Button variant="secondary" onClick={onClose}>关闭</Button></div>
    </div>
  </Dialog>;
}
