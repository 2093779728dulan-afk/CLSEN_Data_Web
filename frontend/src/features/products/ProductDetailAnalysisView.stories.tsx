import { useState } from "react";
import { MemoryRouter } from "react-router-dom";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { ProductDetailAnalysisView } from "./ProductDetailAnalysisView";
import { detailFixture } from "./ProductDetailAnalysisView.fixtures";
import { parseProductDetailSearch, serializeProductDetailSearch, updateProductDetailView } from "./productDetailState";

type Scenario = "reference" | "read-only" | "partial" | "no-reports" | "empty-variants" | "loading" | "refreshing" | "read-failure" | "access-denied" | "color-failure";
function DetailStory({ scenario }: { scenario: Scenario }) {
  const [view, setView] = useState(parseProductDetailSearch(new URLSearchParams(`from=2026-08-22&to=2026-08-24${scenario === "color-failure" ? "&dimension=size&color_key=red-key" : ""}`), "2026-08-24"));
  const [failed, setFailed] = useState(scenario === "read-failure");
  const [colorFailed, setColorFailed] = useState(scenario === "color-failure");
  const data = detailFixture(view, scenario);
  const colors = detailFixture({ ...view, dimension: "color", series: [] }).available_series;
  const failure = failed ? { message: "示例读取失败，请按原条件重试。", retry: true } : scenario === "access-denied" ? { message: "当前账号没有读取此商品分析的权限。", retry: false } : undefined;
  return <MemoryRouter><ProductDetailAnalysisView view={view} displayedView={view} canonical={serializeProductDetailSearch(view).toString()} styleId="501" listTarget="/products?search=10001" response={scenario === "loading" || failure ? undefined : data} failure={failure}
    loading={scenario === "loading" || scenario === "refreshing"} refreshing={scenario === "refreshing"} labels={new Map(data.available_series.map(item => [item.key, item.label]))} selected={view.series.length ? view.series : data.series.map(item => item.key)}
    colorOptions={colorFailed ? [] : colors} colorError={colorFailed ? "颜色选项读取失败" : undefined} onColorRetry={() => setColorFailed(false)}
    update={change => setView(current => updateProductDetailView(current, change))} switchDimension={dimension => setView(current => updateProductDetailView(current, { dimension, color_key: dimension === "size" ? colors[0]?.key : null, series: [] }))} onRetry={() => setFailed(false)} />
  </MemoryRouter>;
}
const meta = { title: "Pages/Product Detail", component: DetailStory, parameters: { layout: "fullscreen" }, args: { scenario: "reference" } } satisfies Meta<typeof DetailStory>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Reference: Story = {};
export const ReadOnly: Story = { args: { scenario: "read-only" } };
export const Partial: Story = { args: { scenario: "partial" } };
export const NoReports: Story = { args: { scenario: "no-reports" } };
export const EmptyVariants: Story = { args: { scenario: "empty-variants" } };
export const Loading: Story = { args: { scenario: "loading" } };
export const Refreshing: Story = { args: { scenario: "refreshing" } };
export const ReadFailure: Story = { args: { scenario: "read-failure" } };
export const AccessDenied: Story = { args: { scenario: "access-denied" } };
export const ColorFailure: Story = { args: { scenario: "color-failure" } };
