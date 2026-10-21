import type { Meta, StoryObj } from "@storybook/react-vite";
import { Link, MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { CatalogLayout } from "./CatalogLayout";
import { CatalogMaintenanceOverview } from "./CatalogMaintenanceOverview";
import type { CurrentCatalog } from "./catalogApi";

type Scenario = "reference" | "uninitialized" | "first-version" | "long-identifiers";
const catalog: CurrentCatalog = { catalog_version_id: 104, version_number: 4, catalog_publication_revision: 7, styles: [], skus: [] };
function Workspace({ scenario }: { scenario: Scenario }) {
  const location = useLocation();
  const value = scenario === "uninitialized" ? null : scenario === "first-version" ? { ...catalog, catalog_version_id: 101, version_number: 1, catalog_publication_revision: 1 } : scenario === "long-identifiers" ? { ...catalog, catalog_version_id: 1234567890123, version_number: 1234567890123, catalog_publication_revision: 1234567890123 } : catalog;
  return <CatalogLayout canManage><Routes>
    <Route path="/catalog/maintenance" element={<div className="catalog-stack"><CatalogMaintenanceOverview catalog={value} /></div>} />
    <Route path="*" element={<section><h2>虚构关联结果</h2><p>目标路径：{location.pathname}</p><Link to="/catalog/maintenance">返回批量维护总览</Link></section>} />
  </Routes><p>版本与记录均为虚构。这里只展示总览及导航，不请求实际 API，不确认来源、建立快照或生成候选；刷新重置。</p></CatalogLayout>;
}
function OverviewStory({ scenario = "reference" }: { scenario?: Scenario }) { return <MemoryRouter initialEntries={["/catalog/maintenance"]}><Workspace scenario={scenario} /></MemoryRouter>; }
const meta = { title: "Patterns/Catalog Maintenance Overview", component: OverviewStory, parameters: { layout: "fullscreen" } } satisfies Meta<typeof OverviewStory>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Reference: Story = { args: { scenario: "reference" } };
export const Uninitialized: Story = { args: { scenario: "uninitialized" } };
export const FirstVersion: Story = { args: { scenario: "first-version" } };
export const LongIdentifiers: Story = { args: { scenario: "long-identifiers" } };
