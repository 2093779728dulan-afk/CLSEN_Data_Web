import { useEffect, useState, type FormEvent } from 'react';
import { X } from 'lucide-react';
import { Button, Checkbox, Input, Table } from '../../../design-system';
import { num, stockAlert, type SheetSku, type StockSettings } from './model';

type Props = {
  label: string; items: SheetSku[]; cutoff: string; settings: StockSettings;
  save: (changes: StockSettings) => Promise<string | undefined>;
  close: () => void; onDirtyChange: (dirty: boolean) => void;
  confirmClose: boolean; keepEditing: () => void; discard: () => void;
  busy: boolean; unknown: boolean; canManage: boolean;
};

export function StockAlertPanel({ label, items, cutoff, settings, save, close, onDirtyChange,
  confirmClose, keepEditing, discard, busy, unknown, canManage }: Props) {
  const configurable = items.filter(item => item.alert.configurable);
  const [draft, setDraft] = useState<StockSettings>(() => Object.fromEntries(configurable.map(item => {
    const saved = stockAlert(item, cutoff, settings);
    return [item.sku_id, { threshold: saved.threshold, replenish: saved.replenish }];
  })));
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const valid = (value: string) => /^\d+$/.test(value) && BigInt(value) <= 9223372036854775807n;
  const dirty = configurable.some(item => {
    const saved = stockAlert(item, cutoff, settings);
    const value = draft[item.sku_id]!;
    return !valid(value.threshold) || BigInt(value.threshold).toString() !== saved.threshold || value.replenish !== saved.replenish;
  });
  useEffect(() => { onDirtyChange(dirty); return () => onDirtyChange(false); }, [dirty, onDirtyChange]);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || !dirty || !canManage) return;
    if (Object.values(draft).some(value => !valid(value.threshold))) { setError('提醒值请填写0或支持范围内的正整数。'); return; }
    try {
      const failure = await save(Object.fromEntries(Object.entries(draft).map(([key, value]) => [key, { ...value, threshold: BigInt(value.threshold).toString() }])));
      setError(failure ?? ''); setMessage(failure ? '' : '已保存');
    } catch (failure) { setError(failure instanceof Error ? failure.message : '读取最新修订失败，输入已保留。'); }
  }
  return <section className="detail-panel settings-panel" aria-label={`${label}库存提醒设置`}>
    <div className="detail-header"><h3>{label} · 美国FBA库存提醒</h3><Button variant="quiet" icon={<X size={18} />} aria-label="收起库存提醒设置" disabled={busy} onClick={close} /></div>
    <form onSubmit={event => void submit(event)}>
      <Table className="detail-table" aria-label="SKU库存提醒设置"><thead><tr><th>SKU</th><th>可售</th><th>提醒值</th><th>继续补货</th><th>状态</th></tr></thead>
        <tbody>{configurable.map(item => {
          const value = draft[item.sku_id]!;
          const preview = valid(value.threshold) ? { ...settings, [item.sku_id]: value } : settings;
          const alert = stockAlert(item, cutoff, preview);
          const labels: Record<string, string> = { normal: '正常', empty: '缺货', low: '低库存', 'sold-out': '售罄', unknown: '待核' };
          return <tr key={item.sku_id}><th>{item.sku}</th><td>{alert.available === null ? '—' : alert.available === 0n ? '' : num(alert.available)}</td>
            <td><Input type="text" inputMode="numeric" required aria-label={`${item.sku}提醒值`} disabled={busy || unknown || !canManage} value={value.threshold}
              onChange={event => { setDraft(current => ({ ...current, [item.sku_id]: { ...current[item.sku_id]!, threshold: event.target.value } })); setMessage(''); setError(''); }} /></td>
            <td><Checkbox label={<span className="sr-only">{item.sku}继续补货</span>} disabled={busy || unknown || !canManage} checked={value.replenish}
              onChange={event => { setDraft(current => ({ ...current, [item.sku_id]: { ...current[item.sku_id]!, replenish: event.target.checked } })); setMessage(''); setError(''); }} /></td>
            <td data-alert={alert.level}>{!valid(value.threshold) ? '待填写' : !value.replenish && alert.available !== null && alert.available > 0n ? '停止补货' : labels[alert.level]}</td></tr>;
        })}</tbody></Table>
      {!configurable.length && <p>当前商品尚未关联该FBA范围，提醒设置未就绪。</p>}
      <div className="alert-actions"><Button type="submit" loading={busy} disabled={!dirty || !canManage}>{unknown ? '核实保存结果' : '保存设置'}</Button>
        {message && <span role="status">{message}</span>}{error && <span role="alert" className="export-error">{error}</span>}</div>
    </form>
    {confirmClose && <div className="unsaved-actions" role="group" aria-label="处理未保存修改"><span>有未保存修改</span><Button onClick={keepEditing}>继续编辑</Button><Button variant="danger" onClick={discard}>放弃修改</Button></div>}
  </section>;
}
