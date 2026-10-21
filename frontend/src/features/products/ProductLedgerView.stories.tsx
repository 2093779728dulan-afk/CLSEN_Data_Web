import { useState } from "react";
import { MemoryRouter } from "react-router-dom";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { ProductLedgerView } from "./ProductLedgerView";
import { ledgerCategories, ledgerFixture } from "./ProductLedgerView.fixtures";
import { parseProductLedgerSearch, serializeProductLedgerSearch, updateProductLedgerView } from "./productLedgerState";
import type { AnalyticsFailure } from "./analyticsError";

type Scenario = "reference" | "partial" | "empty" | "no-reports" | "zero-values" | "loading" | "refreshing" | "read-failure" | "access-denied" | "setup-required";
function LedgerStory({ scenario }: { scenario: Scenario }) {
  const [view, setView] = useState(parseProductLedgerSearch(new URLSearchParams("from=2026-07-25&to=2026-08-24"), "2026-08-24"));
  const [draft, setDraft] = useState({ from: view.from, to: view.to, search: view.search });
  const [showNames, setShowNames] = useState(false);
  const [failed, setFailed] = useState(scenario === "read-failure");
  const data = ledgerFixture(scenario);
  data.sort = view.sort; data.direction = view.direction; data.page = view.page; data.page_size = view.page_size;
  const failure: AnalyticsFailure | undefined = failed ? { message: "示例读取失败，请按原条件重试。", retry: true } : scenario === "access-denied" ? { message: "当前账号没有读取产品分析的权限。", retry: false } : scenario === "setup-required" ? { message: "商品主档尚未初始化。请先生成候选，审核款式映射并批准目录。", retry: false, setup: true } : undefined;
  return <MemoryRouter initialEntries={["/products"]}><ProductLedgerView today="2026-08-24" view={view} canonical={serializeProductLedgerSearch(view).toString()} categories={ledgerCategories} draft={draft} response={scenario === "loading" || failure ? undefined : data} failure={failure}
    loading={scenario === "loading" || scenario === "refreshing"} refreshing={scenario === "refreshing"} showNames={showNames}
    onDraftChange={change => setDraft(current => ({ ...current, ...change }))} onShowNamesChange={setShowNames}
    onSubmit={event => { event.preventDefault(); setView(current => updateProductLedgerView(current, draft)); }} onUpdate={change => setView(current => updateProductLedgerView(current, change))} onRetry={() => setFailed(false)} />
  </MemoryRouter>;
}
const meta = { title: "Pages/Product Ledger", component: LedgerStory, parameters: { layout: "fullscreen" }, args: { scenario: "reference" } } satisfies Meta<typeof LedgerStory>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Reference: Story = {};
export const Partial: Story = { args: { scenario: "partial" } };
export const Empty: Story = { args: { scenario: "empty" } };
export const NoReports: Story = { args: { scenario: "no-reports" } };
export const ZeroValues: Story = { args: { scenario: "zero-values" } };
export const Loading: Story = { args: { scenario: "loading" } };
export const Refreshing: Story = { args: { scenario: "refreshing" } };
export const ReadFailure: Story = { args: { scenario: "read-failure" } };
export const AccessDenied: Story = { args: { scenario: "access-denied" } };
export const SetupRequired: Story = { args: { scenario: "setup-required" } };
