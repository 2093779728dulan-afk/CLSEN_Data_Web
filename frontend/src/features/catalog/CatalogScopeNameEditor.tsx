import { useEffect, useRef, useState, type FormEvent } from "react";
import { ApiRequestError, commandApi, requestApi, StableOperationKeyStore } from "../../api/client";
import { Button, Dialog, FormField, Input, StatusMessage } from "../../design-system";
import css from "./CatalogSetupView.module.css";

type NameState = { scope_id:number; display_name:string; revision:number; can_rename:boolean };
type Guard = { dirty:boolean; busy:boolean; unknown:boolean };

export function CatalogScopeNameEditor({name,saved,onGuardChange}:{name:string;saved:()=>void;onGuardChange:(guard:Guard)=>void}) {
  const [open,setOpen]=useState(false);
  const [current,setCurrent]=useState<NameState>();
  const [displayName,setDisplayName]=useState(name);
  const [reason,setReason]=useState("");
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const [pending,setPending]=useState<{body:Record<string,unknown>;token:string}>();
  const keys=useRef(new StableOperationKeyStore());
  const path="/api/catalog/source-scope/display-name";
  const dirty=open&&(displayName!==(current?.display_name||name)||!!reason);
  useEffect(()=>onGuardChange({dirty,busy,unknown:!!pending}),[dirty,busy,pending,onGuardChange]);
  useEffect(()=>{
    if(!open)return;
    const controller = new AbortController();
    setCurrent(undefined);
    setError("");
    void requestApi<NameState>(path,{signal:controller.signal}).then(value=>{
      if (!controller.signal.aborted) {
        setCurrent(value);
        setDisplayName(value.display_name);
        setReason("");
      }
    }).catch(()=>{if(!controller.signal.aborted)setError("店铺信息读取失败，请关闭后重新打开。");});
    return()=>controller.abort();
  },[open]);
  async function submit(event:FormEvent) {
    event.preventDefault();
    if (!current?.can_rename || busy) return;
    const body=pending?.body||{scope_id:current.scope_id,expected_revision:current.revision,display_name:displayName.trim(),reason:reason.trim()};
    const token=pending?.token||keys.current.forCommand("rename",path,body);
    setBusy(true);
    setError("");
    try{
      await commandApi<NameState>(path,{...body,operation_token:token},token);
      keys.current.complete("rename", token);
      setPending(undefined);
      setOpen(false);
      setReason("");
      saved();
    }catch(value){
      if(!(value instanceof ApiRequestError)||value.status>=500||value.status===408)setPending({body,token});
      else setPending(undefined);
      setError(value instanceof Error?value.message:"名称保存未完成，请核实后继续。");
    } finally {
      setBusy(false);
    }
  }
  return <>
    <Button variant="quiet" onClick={()=>setOpen(true)}>更正店铺名称</Button>
    <Dialog open={open} title="更正店铺名称" dismissDisabled={busy||!!pending} closeOnOutsideClick={false} onOpenChange={setOpen}>
      <form className={css.form} onSubmit={event=>void submit(event)}>
        <fieldset disabled={!current||busy||!!pending} className={css.fields}>
          <FormField label="店铺名称" required><Input required maxLength={128} value={displayName} onChange={event=>setDisplayName(event.target.value)}/></FormField>
          <FormField label="更正原因" required><Input required maxLength={1000} value={reason} onChange={event=>setReason(event.target.value)}/></FormField>
        </fieldset>
        {error&&<StatusMessage kind="danger" title={error}/>}
        <div className={css.footer}>
          <Button disabled={busy || !!pending} onClick={() => setOpen(false)}>取消</Button>
          <Button variant="primary" type="submit" disabled={!current || busy}>{pending ? "核实更名结果" : "保存名称"}</Button>
        </div>
      </form>
    </Dialog>
  </>;
}
