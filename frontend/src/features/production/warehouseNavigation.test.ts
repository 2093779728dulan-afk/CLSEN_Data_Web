import { expect, it } from "vitest";
import { fbaView, warehouseTabs } from "./warehouseNavigation";
import type { DirectoryRecord } from "./directoryTypes";
it("uses FBA business/transport/profile and maps each legacy tab to real content",()=>{
  const record={type:"FBA"} as DirectoryRecord;
  expect(warehouseTabs(record).map(t=>t[1])).toEqual(["库存","运输","仓库资料"]);
  expect(["stock","records","adjust"].map(tab=>fbaView(new URLSearchParams({tab})))).toEqual(["balance","receipts","observation"]);
  expect(fbaView(new URLSearchParams({tab:"adjust",fba_view:"returns",owner:"7"}))).toBe("returns");
  expect(fbaView(new URLSearchParams({fba_view:"invalid"}))).toBe("balance");
});
it("retains physical warehouse history and explicit transport for unknown/uninitialized scopes",()=>{
  for(const type of ["FACTORY","OWN","THIRD_PARTY"]){expect(warehouseTabs({type,inventory_state:"READY"} as DirectoryRecord).map(t=>t[0])).toEqual(["stock","records","adjust","transit","profile"]);}
  expect(warehouseTabs({type:"LOCATION",inventory_state:"NOT_APPLICABLE"} as DirectoryRecord).map(t=>t[0])).toEqual(["transit","profile"]);
  expect(warehouseTabs({type:"OWN"} as DirectoryRecord).map(t=>t[0])).toContain("records");
  expect(warehouseTabs({type:"OWN",status:"INACTIVE",scopes:[{owner_id:"1"}]} as DirectoryRecord).map(t=>t[0])).toContain("adjust");
});
