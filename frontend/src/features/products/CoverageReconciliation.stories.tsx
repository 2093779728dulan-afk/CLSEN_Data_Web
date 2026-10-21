import type { Meta, StoryObj } from "@storybook/react-vite";
import { MemoryRouter } from "react-router-dom";
import { CoverageReconciliation } from "./CoverageReconciliation";
import { ledgerFixture } from "./ProductLedgerView.fixtures";
import css from "./CoverageReconciliation.module.css";

type Scenario = "reference" | "partial" | "no-reports" | "zero-values" | "unmatched" | "long-values";
function CoverageStory({ scenario = "reference" }: { scenario?: Scenario }) {
  const data = ledgerFixture(scenario);
  if (scenario === "partial") Object.assign(data.coverage.business, { identity_status: "partial", identity_decision_rate: "0.800000", mapping_rate: "0.800000" });
  if (scenario === "unmatched") {
    Object.assign(data.coverage.business, { identity_status: "partial", identity_decision_rate: "0.500000", mapping_rate: "0.500000", eligible_rows: 2, unique_rows: 2, unmatched_rows: 1 });
    data.reconciliation.source_totals = { units: 4, sales: "240.00", returns: 0, sessions: 20, conversion_numerator: 4, conversion_denominator: 20 };
    data.reconciliation.unmatched_totals = { ...data.reconciliation.mapped_totals };
  }
  if (scenario === "long-values") {
    data.reconciliation.source_totals = { ...data.reconciliation.source_totals, sales: "123456789012345678901234567890.12" };
    data.reconciliation.mapped_totals = { ...data.reconciliation.source_totals };
  }
  return <MemoryRouter><main className={css.story}><h1>覆盖与对账样板</h1><p>全部数据为虚构；直接复用实际产品总表的组件。不请求实际 API。</p><CoverageReconciliation coverage={data.coverage} reconciliation={data.reconciliation} from="2026-07-25" to="2026-08-24" returnBasis="report_date" /></main></MemoryRouter>;
}
const meta = { title: "Patterns/Coverage Reconciliation", component: CoverageStory, parameters: { layout: "fullscreen" } } satisfies Meta<typeof CoverageStory>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Reference: Story = { args: { scenario: "reference" } };
export const Partial: Story = { args: { scenario: "partial" } };
export const NoReports: Story = { args: { scenario: "no-reports" } };
export const ZeroValues: Story = { args: { scenario: "zero-values" } };
export const Unmatched: Story = { args: { scenario: "unmatched" } };
export const LongValues: Story = { args: { scenario: "long-values" } };
