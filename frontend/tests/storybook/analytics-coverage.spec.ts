import { expect, test } from "@playwright/test";
import { openStory } from "./storybookGateSupport";

for (const width of [1280, 390]) {
  test(`coverage original ratios, six buckets, unavailable states and link scope at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const requests: string[] = [];
    await page.route(url => url.pathname.startsWith("/api/"), route => { requests.push(route.request().url()); return route.abort(); });
    await openStory(page, "patterns-coverage-reconciliation--reference");
    const region = page.getByRole("region", { name: "六桶指标对账", exact: true });
    const table = region.getByRole("table", { name: "六桶指标对账", exact: true });
    await expect(table.getByRole("rowheader")).toHaveText(["来源总量", "已映射", "未匹配", "已排除", "已确认重复", "待判定重复"]);
    await expect(table.locator("tbody tr").first().locator("td")).toHaveText(["2", "120.00", "0", "10", "2/10"]);
    await expect(page.getByRole("group", { name: "站点报表覆盖", exact: true })).toContainText("1.000000");
    await expect(page.getByRole("link", { name: "查看待归属及影响", exact: true })).toHaveCount(0);
    await openStory(page, "patterns-coverage-reconciliation--partial");
    await expect(page.getByRole("group", { name: "站点报表覆盖", exact: true })).toContainText("0.967742");
    await expect(page.getByRole("group", { name: "站点报表覆盖", exact: true })).toContainText("部分完成");
    await openStory(page, "patterns-coverage-reconciliation--no-reports");
    await expect(table.locator("tbody td")).toHaveText(Array(30).fill("不可计算"));
    await expect(page.getByRole("group", { name: "站点报表覆盖", exact: true })).toContainText("0/31 天");
    await expect(page.getByRole("group", { name: "站点报表覆盖", exact: true })).toContainText("不适用");
    await openStory(page, "patterns-coverage-reconciliation--zero-values");
    await expect(table.locator("tbody tr").first().locator("td")).toHaveText(["0", "0.00", "0", "0", "0/0"]);
    await openStory(page, "patterns-coverage-reconciliation--unmatched");
    const link = page.getByRole("link", { name: "查看待归属及影响", exact: true });
    const target = new URL((await link.getAttribute("href"))!, "http://127.0.0.1");
    expect(target.pathname).toBe("/catalog/unmatched"); expect(target.searchParams.get("return_basis")).toBe("report_date");
    expect(target.searchParams.get("from")).toBe("2026-07-25"); expect(target.searchParams.get("to")).toBe("2026-08-24");
    expect(target.searchParams.get("return_to")).toBe("/products?from=2026-07-25&to=2026-08-24&return_basis=report_date&fact_basis=current");
    await link.focus(); await expect(link).toBeFocused();
    await page.reload(); await expect(link).toHaveAttribute("href", target.pathname + target.search);
    await openStory(page, "patterns-coverage-reconciliation--long-values");
    await expect(table).toContainText("123,456,789,012,345,678,901,234,567,890.12");
    await region.scrollIntoViewIfNeeded(); await region.focus(); await expect(region).toBeFocused();
    if (width === 390) {
      const label = table.getByRole("rowheader", { name: "来源总量", exact: true }); const before = (await label.boundingBox())!;
      await page.keyboard.press("ArrowRight"); await expect.poll(() => region.evaluate(node => node.scrollLeft)).toBeGreaterThan(0);
      expect(Math.abs((await label.boundingBox())!.x - before.x)).toBeLessThanOrEqual(1);
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true); expect(requests).toEqual([]);
  });
  test(`all metric help definitions, keyboard dismiss, focus return and reload at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.route(url => url.pathname.startsWith("/api/"), route => route.abort());
    await openStory(page, "patterns-product-ledger-metric-help--all-metrics");
    for (const name of ["款式", "实际变体", "销量", "销售额与占比", "本期退货量与同期退销比", "会话", "转化率", "平均单价"]) {
      const trigger = page.getByRole("button", { name: `${name}说明`, exact: true });
      await trigger.focus(); await page.keyboard.press("Enter");
      const dialog = page.getByRole("dialog", { name, exact: true }); await expect(dialog).toBeVisible();
      await expect(dialog.getByRole("heading", { name: "数据来源", exact: true })).toBeVisible();
      await expect(dialog.getByRole("region", { name: "当前统计范围", exact: true })).toContainText("目录 V3");
      await page.keyboard.press("Escape"); await expect(dialog).toHaveCount(0); await expect(trigger).toBeFocused();
    }
    await openStory(page, "patterns-product-ledger-metric-help--report-date");
    const trigger = page.getByRole("button", { name: "本期退货量与同期退销比说明", exact: true }); await trigger.click();
    await expect(page.getByRole("dialog")).toContainText("退货按报表日期筛选");
    await expect(page.getByRole("dialog")).toContainText("目录快照");
    await page.getByRole("button", { name: "关闭指标说明", exact: true }).click(); await expect(trigger).toBeFocused();
    await trigger.click(); await expect(page.getByRole("dialog")).toBeVisible();
    await expect(page.getByRole("button", { name: "关闭指标说明", exact: true })).toBeFocused();
    await page.mouse.click(2, 2); await expect(page.getByRole("dialog")).toHaveCount(0); await expect(trigger).toBeFocused();
    await trigger.click(); await page.reload(); await expect(page.getByRole("dialog")).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}
