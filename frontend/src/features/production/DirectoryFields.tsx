import { Disclosure } from "../../design-system";
import { useEffect, useRef, useState } from "react";
import { Warehouse } from "lucide-react";
import { Button, FormField, Input, LinkButton } from "../../design-system";
import { useLoad } from "./useProductionApi";
import { ReadState } from "./WorkbenchFields";

import { type Destination, type DirectoryPage } from "./directoryTypes";
import styles from "./DirectoryFields.module.css";

export function DestinationField({ value, onChange, required = false, defaultFba = false, onDefault, compact = false }:  { value: Destination; onChange: (value: Destination) => void; required?: boolean; defaultFba?: boolean; compact?:boolean; onDefault?: (value: Destination) => void }) {
  const capability = useLoad<{ directory_supported?: boolean }>("/api/production/workbench");
  const [query, setQuery] = useState(""); const [page, setPage] = useState(1);
  const directory = useLoad<DirectoryPage>(`/api/production/warehouses?status=ACTIVE&q=${encodeURIComponent(query)}&page=${page}`, 0, capability.value?.directory_supported === true);
  const [fbaRefresh,setFbaRefresh] = useState(0);
  const defaultSelected = useRef(false);
  const {value:fbaValue,current:fbaCurrent,error:fbaError} = useLoad<DirectoryPage>("/api/production/warehouses?status=ACTIVE&type=FBA&page=1", fbaRefresh, defaultFba && capability.value?.directory_supported === true);
  const fbaPlaces = fbaValue?.items.filter(place=>place.type === "FBA" && place.status === "ACTIVE") || [];
  const places = defaultFba ? [...(directory.value?.items||[]),...fbaPlaces.filter(place=>!directory.value?.items.some(item=>item.id===place.id))] : directory.value?.items || [];
  useEffect(()=>{
    if(!defaultFba || defaultSelected.current || value.destination || value.destination_id || !fbaCurrent || fbaError || fbaValue?.total!==1)return;
    const candidates=fbaValue.items.filter(place=>place.type === "FBA" && place.status === "ACTIVE");if(candidates.length!==1)return;
    defaultSelected.current=true;
    const place=candidates[0]!;const next={destination:place.name,destination_id:place.id,destination_type:"WAREHOUSE"};
    (onDefault||onChange)(next);
  },[defaultFba,value.destination,value.destination_id,fbaCurrent,fbaError,fbaValue,onDefault,onChange]);
  function changeDestination(next:Destination){defaultSelected.current=true;onChange(next);}
  const searchInput=<Input aria-label="查找收货仓或地点" type="search" placeholder="查找仓库名称或编号" value={query} onChange={e => { defaultSelected.current=true; setQuery(e.target.value); setPage(1); }} />;
  const managementLink=<LinkButton variant="secondary" icon={<Warehouse size={16}/>} to="/production/warehouses">管理仓库及地点</LinkButton>;
  return <div className={compact?styles.compact:undefined}><div className={styles.heading}><p>{defaultFba ? "目的仓库 / 地点" : required ? "本批实际收货仓 / 地点" : "计划收货仓 / 收货地点（可选）"}</p>{capability.value?.directory_supported && !compact && managementLink}</div>
    {capability.value?.directory_supported && <>{!compact&&searchInput}<select aria-label="选择收货仓或地点" value={value.destination_id || ""} onChange={e => { const place = places.find(w => w.id === e.target.value); changeDestination(place ? { destination: place.name, destination_id: place.id, destination_type: place.type === "LOCATION" ? "LOCATION" : "WAREHOUSE" } : { destination: "", destination_id: null, destination_type: null }); }}><option value="">{required ? "填写文字地点 / 选择档案" : "暂未确定 / 填写文字地点"}</option>{value.destination_id && !places.some(w => w.id === value.destination_id) && <option value={value.destination_id}>{value.destination}</option>}{places.map(w => <option key={w.id} value={w.id}>{w.name}</option>)}</select>{compact&&<Disclosure className={styles.searchDetails}><summary>查找或管理地点</summary>{searchInput}{managementLink}</Disclosure>}{directory.value && directory.value.total > 50 && <div><Button variant="quiet" disabled={page === 1} onClick={() => { defaultSelected.current=true; setPage(p => p - 1); }}>上一页</Button> {page} / {Math.ceil(directory.value.total / 50)} <Button variant="quiet" disabled={page * 50 >= directory.value.total} onClick={() => { defaultSelected.current=true; setPage(p => p + 1); }}>下一页</Button></div>}</>}
    <FormField className={compact&&value.destination_id?styles.selectedDestination:undefined} label={required ? "本批实际发货目的地" : "计划发货目的地"} required={required}><Input required={required} readOnly={!!value.destination_id} maxLength={255} value={value.destination} placeholder={required ? "输入本批明确收货地点" : "可以暂未确定"} onChange={e => changeDestination({ destination: e.target.value, destination_id: null, destination_type: null })} />
  </FormField>{directory.error && <ReadState error={directory.error} />}{defaultFba && !value.destination && fbaValue && fbaValue.total > 1 && <p><small>有多个FBA仓库，请选择本批具体目的仓。</small></p>}{defaultFba && fbaError && <ReadState error={fbaError}/>} {defaultFba && fbaError && <Button variant="secondary" onClick={()=>setFbaRefresh(value=>value+1)}>重新读取FBA仓库</Button>}{!value.destination_id && value.destination && <small>文字地点，尚未关联仓库档案。</small>}</div>;
}
