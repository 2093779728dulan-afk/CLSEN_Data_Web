import * as Dialog from "@radix-ui/react-dialog";
import { ArrowUpRight, X } from "lucide-react";
import { Link } from "react-router-dom";
import { Button, Tooltip } from "../../design-system";
import type { StyleLedgerResponse } from "./productAnalyticsTypes";
import css from "./ProductIdentityCell.module.css";

type Props = {
  row: StyleLedgerResponse["rows"][number];
  showName: boolean;
  detailUrl: string;
  ledgerUrl: string;
};

export function ProductIdentityCell({ row, showName, detailUrl, ledgerUrl }: Props) {
  return <Dialog.Root>
    <Tooltip content={<span className={css.preview}><strong>款号 {row.style_code}</strong><span>{row.standard_name}</span><small>点击查看商品信息</small></span>} side="right">
      <Dialog.Trigger asChild><Button variant="quiet" type="button" className={css.trigger} aria-label={`查看款号 ${row.style_code} 商品信息`}>
        <span>{row.style_code}<ArrowUpRight size={14} aria-hidden="true" /></span>
        {showName && <span className={css.name}>{row.standard_name}</span>}
      </Button></Dialog.Trigger>
    </Tooltip>
    <Dialog.Portal>
      <Dialog.Overlay className={css.overlay} />
      <Dialog.Content className={css.drawer}>
        <header className={css.header}>
          <div><p>商品信息</p><Dialog.Title>款号 {row.style_code}</Dialog.Title></div>
          <Dialog.Close className={css.close} aria-label="关闭商品信息"><X size={20} /></Dialog.Close>
        </header>
        <Dialog.Description className={css.description}>已批准商品主档中的标准名称与当前款式信息。</Dialog.Description>
        <section className={css.identity}><h3>标准商品名称</h3><p>{row.standard_name}</p></section>
        <dl className={css.facts}>
          <div><dt>实际变体</dt><dd>{row.sku_count} 个 SKU</dd></div>
          <div><dt>颜色与尺码</dt><dd>{row.color_count} 色 · {row.size_count} 码</dd></div>
          <div><dt>来源标题</dt><dd>{row.source_title_count} 个</dd></div>
          <div><dt>最近发布</dt><dd>{row.latest_report_date ?? "无发布"}</dd></div>
        </dl>
        <footer className={css.footer}><Link to={detailUrl} state={{ focusId: `style-${row.style_id}`, ledgerUrl }}>进入款式详情 <ArrowUpRight size={16} aria-hidden="true" /></Link><p>查看经营趋势及颜色、尺码明细</p></footer>
      </Dialog.Content>
    </Dialog.Portal>
  </Dialog.Root>;
}
