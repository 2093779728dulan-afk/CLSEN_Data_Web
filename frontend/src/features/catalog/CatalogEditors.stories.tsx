import type { Meta, StoryObj } from "@storybook/react-vite";
import { useMemo, useState } from "react";
import { MemoryRouter } from "react-router-dom";
import { userEvent, within } from "storybook/test";
import { CatalogCategoryEditor, type CatalogCategoryServices } from "./CatalogCategoryEditor";
import { CatalogChangeReview, type CatalogChangeServices } from "./CatalogChangeReview";
import { CatalogLayout } from "./CatalogLayout";
import type { CatalogCategory, CatalogStyle } from "./catalogApi";

type Scenario = "editing" | "preview" | "preparing" | "prepare-failure" | "approval-failure" | "refresh-failure" | "categories" | "unsaved" | "loading" | "read-failure" | "empty" | "save-failure" | "saved";
const categories: CatalogCategory[] = [
  { category_id: 7, code: "DRESS", display_name: "连衣裙", aliases: ["裙装"], status: "enabled" },
  { category_id: 8, code: "DRESS_MINI", display_name: "短款连衣裙", parent_category_id: 7, aliases: ["Mini dress"], status: "enabled" },
  { category_id: 9, code: "SHIRT", display_name: "衬衫", aliases: [], status: "enabled" },
  { category_id: 10, code: "ARCHIVE", display_name: "历史分类", aliases: [], status: "disabled" },
];
const style: CatalogStyle = { style_id: 1001, style_code: "DEMO-01", standard_name: "示例府绸衬衫", revision: 3, category_id: 9, category_code: "SHIRT", category_name: "衬衫", category_recorded: true, status: "enabled", variant_count: 3, seller_sku_count: 6, source_summary: { first_seen_date: "2026-07-01", latest_seen_date: "2026-09-30", observation_count: 26, source_report_count: 3 } };
const delay = () => new Promise<void>(resolve => window.setTimeout(resolve, 280));

function EditorsPage({ scenario = "editing" }: { scenario?: Scenario }) {
  const [notice, setNotice] = useState("");
  const isCategory = ["categories", "unsaved", "loading", "read-failure", "empty", "save-failure", "saved"].includes(scenario);
  const services = useMemo(() => {
    let reads = 0;
    let writes = 0;
    let rows = categories.map(item => ({ ...item, aliases: [...item.aliases] }));
    const read = async () => {
      if (scenario === "loading") return new Promise<CatalogCategory[]>(() => undefined);
      await delay();
      if (scenario === "read-failure" && reads++ === 0) throw new Error("Synthetic read failure");
      return scenario === "empty" ? [] : rows;
    };
    const category: CatalogCategoryServices = {
      list: read,
      create: async (code, display_name, aliases, parent_category_id) => { await delay(); const saved: CatalogCategory = { category_id: 11, code, display_name, aliases, parent_category_id, status: "enabled" }; rows = [...rows, saved]; return saved; },
      update: async value => { await delay(); if (scenario === "save-failure" && writes++ === 0) throw new Error("Synthetic save failure"); rows = rows.map(item => item.category_id === value.category_id ? value : item); return value; },
    };
    const change: CatalogChangeServices = {
      categories: read,
      prepare: async (value, revision, name, categoryId) => {
        if (scenario === "preparing") return new Promise(() => undefined);
        await delay();
        if (scenario === "prepare-failure" && writes++ === 0) throw new Error("示例：目录修订已变化，请核对后重新生成预览。");
        const categoryValue = rows.find(item => item.category_id === categoryId);
        return { style_id: value.style_id, style_code: value.style_code, draft_id: 41, draft_revision: 1, status: "draft", base_catalog_publication_revision: revision, before: { standard_name: value.standard_name, category: { category_id: value.category_id, code: value.category_code, display_name: value.category_name } }, after: { standard_name: name, category: { category_id: categoryId, code: categoryValue?.code ?? null, display_name: categoryValue?.display_name ?? null, parent_name: rows.find(item => item.category_id === categoryValue?.parent_category_id)?.display_name } } };
      },
      approve: async () => { await delay(); if (scenario === "approval-failure" && writes++ === 0) throw new Error("示例：批准未完成，草稿已保留。"); return { catalog_version_id: 5, catalog_publication_revision: 5 }; },
    };
    return { category, change };
  }, [scenario]);
  const onApproved = async () => { await delay(); if (scenario === "refresh-failure") throw new Error("示例：批准后读取失败，请在商品详情刷新；这里不代表批准未提交。"); setNotice("示例目录已更新，重新打开仍是虚构商品。实际刷新由商品详情页提供。"); };
  return <MemoryRouter><CatalogLayout canManage>
    <h2>{isCategory ? "分类字典管理样板" : "商品修改与批准样板"}</h2>
    {isCategory ? <CatalogCategoryEditor services={services.category} /> : <CatalogChangeReview style={style} catalogPublicationRevision={4} onApproved={onApproved} services={services.change} />}
    {notice && <p role="status">{notice}</p>}
    <p>数据与操作均为虚构样例，不请求实际 API。分类保存与商品批准是独立操作，权限由实际页面提供。</p>
  </CatalogLayout></MemoryRouter>;
}

const meta = {
  title: "Pages/Catalog Editors", component: EditorsPage, parameters: { layout: "fullscreen" },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const scenario = args.scenario ?? "editing";
    const isCategory = ["categories", "unsaved", "loading", "read-failure", "empty", "save-failure", "saved"].includes(scenario);
    await userEvent.click(canvas.getByRole("button", { name: isCategory ? "管理分类" : "修改名称 / 分类" }));
    if (isCategory) {
      if (["loading", "read-failure", "empty"].includes(scenario)) return;
      await canvas.findByRole("button", { name: "编辑 短款连衣裙" });
      if (scenario === "categories") return;
      await userEvent.click(canvas.getByRole("button", { name: "编辑 短款连衣裙" }));
      await userEvent.clear(canvas.getByRole("textbox", { name: "分类名称" }));
      await userEvent.type(canvas.getByRole("textbox", { name: "分类名称" }), "示例短款连衣裙");
      if (scenario === "unsaved") { await userEvent.click(canvas.getByRole("button", { name: "编辑 连衣裙" })); return; }
      await userEvent.click(canvas.getByRole("button", { name: "保存修改" }));
      return;
    }
    await canvas.findByRole("option", { name: "衬衫（SHIRT）" });
    if (scenario === "editing") return;
    await userEvent.clear(canvas.getByRole("textbox", { name: "标准商品名称" }));
    await userEvent.type(canvas.getByRole("textbox", { name: "标准商品名称" }), "示例浅蓝府绸衬衫");
    await userEvent.click(canvas.getByRole("button", { name: "生成变更预览" }));
    if (["preparing", "prepare-failure"].includes(scenario)) return;
    await canvas.findByRole("table", { name: "变更预览" });
    if (scenario !== "preview") await userEvent.click(canvas.getByRole("button", { name: "批准并生成新目录版本" }));
  },
} satisfies Meta<typeof EditorsPage>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Editing: Story = { args: { scenario: "editing" } };
export const Preview: Story = { args: { scenario: "preview" } };
export const Preparing: Story = { args: { scenario: "preparing" } };
export const PrepareFailure: Story = { args: { scenario: "prepare-failure" } };
export const ApprovalFailure: Story = { args: { scenario: "approval-failure" } };
export const RefreshFailure: Story = { args: { scenario: "refresh-failure" } };
export const Categories: Story = { args: { scenario: "categories" } };
export const Unsaved: Story = { args: { scenario: "unsaved" } };
export const Loading: Story = { args: { scenario: "loading" } };
export const ReadFailure: Story = { args: { scenario: "read-failure" } };
export const Empty: Story = { args: { scenario: "empty" } };
export const SaveFailure: Story = { args: { scenario: "save-failure" } };
export const Saved: Story = { args: { scenario: "saved" } };
