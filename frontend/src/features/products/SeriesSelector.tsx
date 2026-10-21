import { Checkbox } from "../../design-system";
import css from "./ProductAnalytics.module.css";
import { useState } from "react";
import type { components } from "../../api/generated";

type AvailableSeries = components["schemas"]["AvailableSeries"];

export function SeriesSelector({ available, selected, onChange }: { available: readonly AvailableSeries[]; selected: readonly string[]; onChange: (keys: readonly string[]) => void }) {
  const [notice, setNotice] = useState("");
  const dimension = available[0]?.dimension;
  const noun = dimension === "color" ? "种颜色" : dimension === "size" ? "个尺码" : dimension === "sku" ? "个 SKU" : "项";
  const title = dimension === "color" ? "选择要对比的颜色" : dimension === "size" ? "选择要对比的尺码" : dimension === "sku" ? "选择要对比的 SKU" : "选择要显示的数据";
  const selectedCount = available.filter(item => selected.includes(item.key)).length;
  const countText = available.length > 0 && selectedCount === available.length
    ? `全部 ${available.length} ${noun}已选`
    : `已选 ${selectedCount} / ${available.length} ${noun}`;
  const toggle = (key: string, checked: boolean) => {
    if (checked) {
      if (selected.includes(key)) return;
      if (selected.length >= 8) { setNotice("同时最多对比 8 项，请先取消一项。"); return; }
      onChange([...selected, key]); setNotice("已加入比较。"); return;
    }
    if (selected.length <= 1 && available.length > 0) { setNotice("至少选择 1 项进行对比。"); return; }
    onChange(selected.filter((value) => value !== key)); setNotice("已移出比较。");
  };
  return <fieldset className={css["series-selector"]}><legend>{title} <span>{countText}{available.length > 8 ? " · 同时最多对比 8 项" : ""}</span></legend>
    {available.length === 0 ? <p>当前维度没有可选数据。</p> : <div className={css["series-selector__options"]}>{available.map((item) => <Checkbox key={item.key} label={item.label} checked={selected.includes(item.key)} disabled={!selected.includes(item.key) && selected.length >= 8} onChange={(event) => toggle(item.key, event.target.checked)} />)}</div>}
    <p aria-live="polite" className={css["analytics-live"]}>{notice}</p>
  </fieldset>;
}
