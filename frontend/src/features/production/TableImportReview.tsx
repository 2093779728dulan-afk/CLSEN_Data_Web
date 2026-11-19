import { LinkButton, Table } from "../../design-system";
import { tableChanges, type TableBaseline, type ImportRow } from "./tableImportDiff";
export type { TableBaseline, ImportRow } from "./tableImportDiff";

export function TableImportReview({ baseline, rows }: { baseline?: TableBaseline; rows: ImportRow[] }) {
  if (!baseline) return null;
  const changes = tableChanges(baseline.rows, rows);
  return <section aria-label="原表修改核对">
    <h3>原表修改核对{changes.length ? ` · ${changes.length}处` : ""}</h3>
    <p>{baseline.filename} <LinkButton variant="quiet" reloadDocument download to={`/api/production/table-baselines/${baseline.id}/original`}>查看原表</LinkButton></p>
    {changes.length ? <Table aria-label="原表与当前填写对照"><thead><tr><th>商品 / 原表行</th><th>修改项</th><th>原表</th><th>本次</th></tr></thead><tbody>{changes.map((change, i) => <tr key={i}><th scope="row">{change.label}{change.row && <small> · 第{change.row}行</small>}</th><td>{change.field}</td><td>{change.before}</td><td>{change.after}</td></tr>)}</tbody></Table> : <p>与原表一致，无人工修改。</p>}
  </section>;
}
