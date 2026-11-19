import {expect,it} from 'vitest';
import {skuSuggestion,reviewSuggestion} from './catalogReviewSuggestions';
import type {CatalogImportRow} from './catalogTypes';
it('suggests only the exact supported SKU order without correcting case or whitespace',()=>{expect(skuSuggestion('3104-White-S')).toEqual({style_code:'3104',color:'White',size:'S'});for(const code of ['3104-white-S','3104-S-White',' 3104-White-S','3104-White-s','QA-SOURCE-M'])expect(skuSuggestion(code)).toBeUndefined();});
it('prepares unique-source SKU fields but leaves ambiguous codes and existing decisions alone',()=>{const row={row_key:'s',projection_state:'included',payload:{}} as CatalogImportRow;expect(reviewSuggestion('skus',row,{s:{internal_display_sku:[{value:'3104-White-S',label:'原报告'}],standard_color:[{value:'White',label:'White'}],standard_size:[{value:'S',label:'S'}]}})).toMatchObject({internal_display_sku:'3104-White-S',standard_color:'White',standard_size:'S',code_status:'confirmed'});expect(reviewSuggestion('skus',row,{s:{internal_display_sku:[{value:'A',label:'A'},{value:'B',label:'B'}]}})).toBeUndefined();expect(reviewSuggestion('mappings',{...row,payload:{identity_decision:'excluded',target_sku_row_key:'s'}},{s:{target_sku_row_key:[{value:'s',label:'目标'}]}})).toBeUndefined();});
it('does not propose mappings without an existing valid target or across conflicts',()=>{const row={row_key:'m',row_origin:'system',section:'mappings',projection_state:'included',payload:{target_sku_row_key:'s'}} as CatalogImportRow;const options={m:{target_sku_row_key:[{value:'s',label:'已明确目标'}]}};expect(reviewSuggestion('mappings',row,options)).toMatchObject({identity_decision:'mapped'});expect(reviewSuggestion('mappings',{...row,payload:{}},options)).toBeUndefined();expect(reviewSuggestion('mappings',row,options,[{row_key:'m',section:'mappings',reason_code:'mapping_target_changed',severity:'error',field:null}])).toBeUndefined();});

it('suggests a stable target only from one exact fully specified review option',()=>{
 const row={row_key:'m',section:'mappings',row_origin:'system',projection_state:'included',payload:{seller_sku_preview:'3104-White-S'}} as CatalogImportRow;
 const choice={value:'stable-sku-row',label:'3104 · White · S',source:'已明确规格'};
 expect(reviewSuggestion('mappings',row,{m:{target_sku_row_key:[choice]}})).toMatchObject({target_sku_row_key:'stable-sku-row',identity_decision:'mapped'});
 expect(reviewSuggestion('mappings',row,{m:{target_sku_row_key:[choice,{...choice,value:'other'}]}})).toBeUndefined();
 expect(reviewSuggestion('mappings',row,{m:{target_sku_row_key:[{...choice,source:'当前审核候选'}]}})).toBeUndefined();
});
