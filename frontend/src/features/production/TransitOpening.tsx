import { Table } from "../../design-system";
import { units } from "./types";

export type TransitOpeningRow = { sku_id: string; sku_label: string; units: string; snapshot_on: string; source_filename: string };

export function TransitOpening({ rows }: { rows?: TransitOpeningRow[] }) {
  if (!rows?.length) return null;
  return <section aria-label="期初在途">
    <h3>{rows[0]!.snapshot_on} · 期初在途</h3>
    <Table aria-label="期初在途明细"><thead><tr><th>SKU</th><th>在途</th></tr></thead>
      <tbody>{rows.map(row => <tr key={row.sku_id} title={row.source_filename}><th scope="row">{row.sku_label}</th><td>{units(row.units)}</td></tr>)}</tbody>
      <tfoot><tr><th scope="row">合计</th><td>{units(rows.reduce((total, row) => total + BigInt(row.units), 0n).toString())}</td></tr></tfoot>
    </Table>
  </section>;
}
