import { Table } from "../../design-system";
import type { OperationImportPreview } from "./OperationTableImport";
import type { Source } from "./types";

import { dispatchImportChanges } from "./dispatchImportDiff";
import styles from "./Production.module.css";

export function DispatchImportChanges({imported,sources,options}:{imported:OperationImportPreview;sources:Source[];options:{value:string;label:string}[]}) {
  const changes = dispatchImportChanges(imported,sources,options);
  return <section className={styles.dispatchReviewChanges} aria-label="导入后修改记录">
    <h3>原表修改核对</h3>
    <p>{imported.filename} · {changes.length ? `${changes.length}处修改` : "与原表一致"}</p>
    {changes.length > 0 && <Table aria-label="原表与当前填写对照"><thead><tr><th>原表位置</th><th>修改内容</th><th>原表</th><th>当前填写</th></tr></thead><tbody>
      {changes.map(change => <tr key={change.key}><td>{change.row}</td><td>{change.kind}</td><td>{change.before}</td><td>{change.after}</td></tr>)}
    </tbody></Table>}
  </section>;
}
