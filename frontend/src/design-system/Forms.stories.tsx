import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { CircleHelp, PackageSearch, Shirt } from "lucide-react";

import { FormField } from "./FormField";
import { Input } from "./Input";
import { Select } from "./Select";
import { Button, FilterToolbar, Pagination, StatusBadge, Tooltip } from "./index";
import styles from "./Forms.stories.module.css";

const meta = {
  title: "Design System/Form controls",
  parameters: { layout: "padded" },
} satisfies Meta;

export default meta;
type Story = StoryObj<typeof meta>;

export const FieldStates: Story = {
  render: () => <div className="storybook-form">
    <FormField hint="支持款号、Seller SKU、ASIN 或商品名称。" label="搜索商品">
      <Input placeholder="输入商品信息" type="search" />
    </FormField>
    <FormField label="处理状态" required>
      <Select defaultValue="review">
        <option value="all">全部状态</option>
        <option value="review">等待审核</option>
        <option value="published">已发布</option>
      </Select>
    </FormField>
    <FormField error="月份不能早于当前发布数据范围。" label="统计月份">
      <Input defaultValue="2025-01" type="month" />
    </FormField>
    <FormField hint="当前账号无权修改此字段。" label="站点">
      <Input disabled value="Amazon US · America/Los_Angeles" readOnly />
    </FormField>
    <FormField label="较长中文标签用于验证窄屏换行与信息层级">
      <Input placeholder="控件保持完整宽度和可见焦点" />
    </FormField>
    <FormField hint="只读字段仍可聚焦和复制。" label="来源编号"><Input readOnly value="DEMO-IMPORT-2026" /></FormField>
    <FormField label="不可用的处理状态"><Select disabled defaultValue="review"><option value="review">等待审核</option></Select></FormField>
  </div>,
};

const DEMO_RECORDS = [
  { code: "DEMO-01", name: "暖灰直筒长裤", pending: true },
  { code: "DEMO-02", name: "浅蓝府绸衬衫", pending: false },
  { code: "DEMO-03", name: "米白针织开衫", pending: true },
  { code: "DEMO-04", name: "深蓝棉质衬衫", pending: false },
  { code: "DEMO-05", name: "炭灰休闲长裤", pending: true },
  { code: "DEMO-06", name: "薄荷绿短袖衬衫", pending: false },
];

function ReviewControlsExample() {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  const [onlyPending, setOnlyPending] = useState(false);
  const [page, setPage] = useState(1);
  const records = DEMO_RECORDS.filter(record => `${record.code} ${record.name}`.toLowerCase().includes(query.trim().toLowerCase())
    && (status === "all" || record.pending === (status === "pending")) && (!onlyPending || record.pending));
  const totalPages = Math.max(1, Math.ceil(records.length / 2));
  return <section aria-label="小组件交互样板" className={styles.panel}>
    <header className={styles.header}><div><div className={styles.eyebrow}><span>商品主档</span><span className={styles.demo}>演示数据</span></div><h2>商品审核</h2><p>找到需要补全的商品，让来源字段与标准目录保持一致。</p></div>
      <Tooltip content="搜索与处理状态共同筛选结果；仅看待处理会进一步缩小范围，筛选变化后从第一页开始。"><Button aria-label="筛选说明" className={styles.help} icon={<CircleHelp />} variant="quiet" /></Tooltip>
    </header>
    <div className={styles.filters}><FilterToolbar hasAdditionalFilters={status !== "all"} matchingCount={records.length} onOnlyPendingChange={value => { setOnlyPending(value); setPage(1); }} onQueryChange={value => { setQuery(value); setPage(1); }} onReset={() => { setQuery(""); setStatus("all"); setOnlyPending(false); setPage(1); }} onlyPending={onlyPending} pendingLabel="仅看待处理示例" placeholder="搜索款号或商品名称" query={query} searchLabel="搜索示例商品" totalCount={DEMO_RECORDS.length}>
      <FormField label="示例处理状态"><Select onChange={event => { setStatus(event.target.value); setPage(1); }} value={status}><option value="all">全部状态</option><option value="pending">待处理</option><option value="complete">已核对</option></Select></FormField>
    </FilterToolbar></div>
    <div aria-hidden="true" className={styles.columns}><span>商品 / 款号</span><span>处理状态</span></div>
    <ul aria-label="示例商品结果" className={styles.results}>{records.slice((page - 1) * 2, page * 2).map(record => <li key={record.code}><span aria-hidden="true" className={styles.productIcon}><Shirt /></span><div><strong>{record.name}</strong><span className={styles.productMeta}><span>{record.code}</span><span className={styles.separator}>·</span><span>{record.pending ? "标准字段待补全" : "标准字段已核对"}</span></span></div><StatusBadge label={record.pending ? "待处理" : "已核对"} tone={record.pending ? "warn" : "good"} /></li>)}</ul>
    {records.length === 0 && <div className={styles.empty} role="status"><PackageSearch aria-hidden="true" /><strong>没有匹配的示例商品</strong><p>试试其他款号或名称，或重置筛选查看全部商品。</p></div>}
    <footer className={styles.footer}><Pagination itemLabel="示例商品" onPageChange={setPage} page={page} totalItems={records.length} totalPages={totalPages} /><p>仅使用虚构商品，无真实数据写入。</p></footer>
  </section>;
}

export const ReviewControls: Story = { render: () => <ReviewControlsExample /> };


export const GlobalDefaults: Story = {
  render: () => <section className={styles.panel} aria-label="全局样式与公共组件">
    <header className={styles.header}><div><div className={styles.eyebrow}><span>Design System / 表单</span><span className={styles.demo}>虚构数据</span></div><h2>表单与操作规范</h2><p>统一基础字段与组件状态，让填写、核对和反馈保持一致。</p></div></header>
    <div className={styles.defaultsGrid}>
      <fieldset className={styles.defaultsGroup}><legend>基础字段</legend><p className={styles.groupHint}>旧表单沿用全局默认值，保持原生交互。</p>
        <label className="ui-field">原生名称字段<input aria-label="原生名称字段" placeholder="输入商品名称" /></label>
        <label className="ui-field">原生处理状态<select aria-label="原生处理状态" defaultValue="pending"><option value="pending">待处理</option><option value="done">已处理</option></select></label>
        <label className="ui-field">只读来源<input aria-label="只读来源" readOnly value="DEMO-2026" /><span className={styles.groupHint}>可选中并复制，来源编号不允许修改。</span></label>
        <label className="ui-field">原生错误状态<input aria-label="原生错误状态" aria-invalid="true" aria-describedby="native-field-error" defaultValue="示例" /><span className={styles.nativeError} id="native-field-error">请输入有效的名称。</span></label>
      </fieldset>
      <fieldset className={styles.defaultsGroup}><legend>公共组件</legend><p className={styles.groupHint}>复用现有 Input、FormField 和 Button 适配组件。</p>
        <FormField label="组件错误状态" error="请输入有效的名称。"><Input aria-label="组件错误状态" aria-invalid="true" defaultValue="示例" /></FormField>
        <label className="ui-field">旧表单中的公共输入<Input aria-label="旧表单中的公共输入" placeholder="组件保持自身样式" /></label>
        <div className={styles.readonlyNote}><strong>状态表达</strong><p>只读使用浅底色，错误使用边框和文字提示；焦点仅在当前操作控件上显示。</p></div>
      </fieldset>
    </div>
    <footer className={styles.defaultsFooter}><label className={styles.nativeChoice}><input type="checkbox" /> 保留原生勾选行为</label><div className={styles.defaultActions}><button type="button">原生操作</button><Button>公共操作</Button><Button disabled>暂不可用</Button></div></footer>
    <details className={styles.defaultsDisclosure}><summary>操作说明</summary><p>基础样式提供默认值，公共组件管理自己的焦点、禁用和错误状态。</p></details>
  </section>,
};
