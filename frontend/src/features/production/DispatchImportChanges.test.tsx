import { expect, it } from "vitest";
import { dispatchImportChanges } from "./dispatchImportDiff";
import type { OperationImportPreview } from "./OperationTableImport";
import type { Source } from "./types";

const imported = {source_rows:[
  {row:2,sku_code:"A",units:"8"}, {row:3,sku_code:"B",units:"6"}, {row:4,sku_code:"C",units:"2"},
]} as OperationImportPreview;
const options = [{value:"1",label:"A"},{value:"2",label:"B"},{value:"3",label:"C"}];
const source = (import_row:number,sku_id:string,actual_units:string):Source => ({import_row,sku_id,actual_units,allocations:[]});

it("compares by source row after removal and records quantities, replacements and additions", () => {
  const changed = dispatchImportChanges(imported,[source(2,"1","5"),source(4,"2","2"),{sku_id:"3",actual_units:"1",allocations:[]}],options);
  expect(changed.map(change => change.kind)).toEqual(["修改数量","移除商品","更换商品","新增商品"]);
  expect(changed[0]).toMatchObject({row:"第2行",before:"A · 8件",after:"A · 5件"});
  expect(changed[2]).toMatchObject({row:"第4行",before:"C · 2件",after:"B · 2件"});
});

it("keeps unmatched original codes and clears edits when restored to original values", () => {
  const sources = [source(2,"1","8"),source(3,"2","6"),{...source(4,"","2"),import_code:"C"}];
  expect(dispatchImportChanges(imported,sources,options)).toEqual([]);
  expect(dispatchImportChanges(imported,[{sku_id:"",actual_units:"",allocations:[]}],options)).toHaveLength(3);
});
