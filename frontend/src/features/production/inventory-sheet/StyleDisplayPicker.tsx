import { useEffect, useState, type FormEvent } from 'react';
import { Button, Checkbox, Dialog, Input } from '../../../design-system';
import { ProductionConfirmDialog } from '../ProductionConfirmDialog';
import type { DisplayStyle } from './model';

type Props = {
  styles: DisplayStyle[]; selected: string[]; busy: boolean; unknown: boolean;
  save: (ids: string[]) => Promise<string | undefined>;
  close: () => void; onDirtyChange: (dirty: boolean) => void;
};

export function StyleDisplayPicker({ styles, selected, busy, unknown, save, close, onDirtyChange }: Props) {
  const initial = selected.length ? selected : styles.map(style => style.id);
  const [ids, setIds] = useState<string[]>(initial);
  const [touched, setTouched] = useState(false);
  const [query, setQuery] = useState('');
  const [error, setError] = useState('');
  const [confirmClose, setConfirmClose] = useState(false);
  const dirty = ids.length !== initial.length || ids.some(id => !initial.includes(id)) || (!selected.length && touched);
  const shown = styles.filter(style => style.style_code.toLowerCase().includes(query.trim().toLowerCase()));
  useEffect(() => { onDirtyChange(dirty); return () => onDirtyChange(false); }, [dirty, onDirtyChange]);
  function requestClose() { if (dirty) setConfirmClose(true); else close(); }
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!ids.length || busy || !dirty) return;
    try {
      const failure = await save(ids);
      if (failure) setError(failure); else close();
    } catch (failure) { setError(failure instanceof Error ? failure.message : '保存失败，输入已保留。'); }
  }
  return <>
    <Dialog open title="设置首页展示款号" size="large" closeOnOutsideClick={false} dismissDisabled={busy || unknown} onOpenChange={open => { if (!open) requestClose(); }}>
      <form className="sheet-style-picker" onSubmit={event => { void submit(event); }}>
        <Input type="search" aria-label="搜索展示款号" placeholder="搜索款号" value={query} disabled={busy || unknown} onChange={event => setQuery(event.target.value)} />
        <div className="style-picker-actions"><Button disabled={busy || unknown} onClick={() => { setTouched(true); setIds(styles.map(style => style.id)); }}>全选</Button><Button disabled={busy || unknown} onClick={() => { setTouched(true); setIds([]); }}>清空选择</Button><span>已选 {ids.length} / {styles.length} 款</span></div>
        <div className="style-picker-list" role="group" aria-label="可展示款号">{shown.map(style => <Checkbox key={style.id}
          label={<span className="style-picker-identity"><strong>{style.style_code}</strong></span>}
          checked={ids.includes(style.id)} disabled={busy || unknown} onChange={event => { setTouched(true); setIds(current => event.target.checked ? [...current, style.id] : current.filter(id => id !== style.id)); }}
        />)}{!shown.length && <p>没有匹配款号。</p>}</div>
        {!ids.length && <p role="status">请选择至少一个款号。</p>}
        {error && <p role="alert" className="export-error">{error}</p>}
        <div className="style-picker-actions"><Button type="submit" variant="primary" loading={busy} disabled={!dirty || !ids.length}>{unknown ? '核实保存结果' : '保存展示款号'}</Button><Button disabled={busy || unknown} onClick={requestClose}>取消</Button></div>
      </form>
    </Dialog>
    <ProductionConfirmDialog open={confirmClose} title="还有未保存的展示款号" description="继续选择，或放弃本次选择后关闭。" onOpenChange={setConfirmClose}>
      <Button onClick={() => setConfirmClose(false)}>继续选择</Button><Button variant="danger" onClick={close}>放弃修改</Button>
    </ProductionConfirmDialog>
  </>;
}
