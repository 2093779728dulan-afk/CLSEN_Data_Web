import type { CatalogImportRow, CatalogRowIssue, CatalogSection } from "./catalogTypes";
import type { CatalogReviewOptionIndex } from "./catalogReviewOptions";

/** Suggestions preserve exact source spelling and never establish a mapping by themselves. */
export function skuSuggestion(source: string) {
 const match=/^([0-9]+)-([A-Z][A-Za-z]*(?: [A-Z][A-Za-z]*)*)-(XXS|XS|S|M|L|XL|XXL|XXXL|[2-9]XL|[0-9]+)$/.exec(source);
 return match ? {style_code:match[1]!,color:match[2]!,size:match[3]!} : undefined;
}
export function reviewSuggestion(section:CatalogSection,row:CatalogImportRow,options:CatalogReviewOptionIndex,issues:CatalogRowIssue[]=[]) {
 if(row.projection_state==='audit_only'||row.payload.reconfirm_required||issues.some(i=>i.row_key===row.row_key&&!['required','formal_code_decision_required','mapped_target_formal_code_required'].includes(i.reason_code)))return undefined;
 const p=row.payload;const choices=options[row.row_key];const patch:CatalogImportRow['payload']={};
 if(section==='skus'){
  for(const field of ['standard_color','standard_size'] as const){const values=choices?.[field];if(!p[field]&&values?.length===1)patch[field]=values[0]!.value;}
  const codes=row.display_sku_choice?.options??choices?.internal_display_sku;
  const unique=[...new Set(codes?.map(c=>c.value).filter(Boolean)??[])];
  if(!p.internal_display_sku&&(!p.code_status||p.code_status==='confirmed')&&unique.length===1){patch.internal_display_sku=unique[0]!;patch.code_status='confirmed';patch.code_evidence=typeof p.source_code_evidence==='string'&&p.source_code_evidence.trim()?p.source_code_evidence:'人工核对并采用本批唯一来源编码；原资料与行记录保留';}
  else if(p.internal_display_sku&&p.code_status==='confirmed'&&!p.code_evidence&&unique.length===1&&unique[0]===p.internal_display_sku)patch.code_evidence=typeof p.source_code_evidence==='string'&&p.source_code_evidence.trim()?p.source_code_evidence:'人工核对并采用本批唯一来源编码；原资料与行记录保留';
 }else if(section==='mappings'&&!p.identity_decision){
  const targets=choices?.target_sku_row_key??[];
  const spec=typeof p.seller_sku_preview==='string'?skuSuggestion(p.seller_sku_preview):undefined;
  const exact=spec?targets.filter(c=>c.source==='已明确规格'&&c.label===`${spec.style_code} · ${spec.color} · ${spec.size}`):[];
  const key=p.target_sku_row_key&&targets.some(c=>c.value===p.target_sku_row_key)?p.target_sku_row_key:!p.target_sku_row_key&&exact.length===1?exact[0]!.value:undefined;
  if(key){patch.target_sku_row_key=key;patch.identity_decision='mapped';patch.change_reason='人工核对并纳入本批已明确目标规格；原来源与核对证据保留';}
 }

 return Object.keys(patch).length?patch:undefined;
}
