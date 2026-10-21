import { expect, type Page } from "@playwright/test";

export async function openStory(page: Page, storyId: string): Promise<void> {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto(`/iframe.html?id=${storyId}&viewMode=story`);
  // The first story can still be compiling after the Vite server responds.
  await expect(page.locator("#storybook-root")).toBeVisible({ timeout: 15_000 });
  await page.evaluate(async () => document.fonts.ready);
  await expect.poll(() => page.evaluate(() => getComputedStyle(document.body).fontFamily))
    .toContain("Noto Sans SC Variable");
  // A CSS family name and fonts.ready also succeed after a failed font request.
  // Require the bundled face to load before comparing against its baseline.
  await page.evaluate(async () => {
    const faces = await document.fonts.load('16px "Noto Sans SC Variable"', "商品 DEMO");
    if (faces.length === 0 || faces.some(face => face.status !== "loaded")) {
      throw new Error("Storybook's bundled Noto Sans SC font did not load.");
    }
  });
}

export async function prepareInteractiveStory(page: Page, storyId: string): Promise<void> {
  if (storyId.startsWith("patterns-coverage-reconciliation--")) await expect(page.getByRole("region", { name: "六桶指标对账", exact: true })).toBeVisible();
  if (storyId.startsWith("patterns-product-ledger-metric-help--")) {
    await page.getByRole("button", { name: /--(returns|report-date)$/.test(storyId) ? "本期退货量与同期退销比说明" : "销售额与占比说明", exact: true }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
  }
  if (storyId.startsWith("patterns-trend-point-matrix--")) {
    if (storyId.endsWith("--empty")) await expect(page.getByRole("heading", { name: "暂无每日明细", exact: true })).toBeVisible();
    else await expect(page.getByRole("region", { name: "趋势每日点矩阵", exact: true })).toBeVisible();
  }
  if (storyId.startsWith("patterns-product-trend-chart--")) await expect(page.getByRole("region", { name: "趋势每日点矩阵", exact: true })).toBeVisible();
  if (storyId.startsWith("patterns-metric-value--")) await expect(page.getByRole("list", { name: "经营指标示例", exact: true })).toBeVisible();
  if (storyId.startsWith("patterns-safe-source-reference--")) await expect(page.getByRole("list", { name: "来源引用示例", exact: true })).toBeVisible();
  if (storyId === "pages-product-detail--reference" || storyId === "pages-product-detail--read-only") {
    const alias = page.locator("summary").filter({ hasText: /个来源别名/ }).first();
    await expect(alias).toBeVisible();
    await alias.click();
    await expect(alias.locator("..").locator(".safe-source-ref").first()).toBeVisible();
  }
  if (storyId.startsWith("patterns-table-header--")) await expect(page.getByRole("table", { name: "虚构报表", exact: true })).toBeVisible();
  if (storyId === "pages-published-detail-ledger--column-settings") await page.getByRole("button", { name: "列设置", exact: true }).click();
  if (storyId === "pages-date-workbench--column-settings" || storyId === "pages-published-detail-ledger--column-settings") await expect(page.getByRole("region", { name: "列设置", exact: true })).toBeVisible();
  if (storyId.startsWith("patterns-column-settings--")) {
    await expect(page.getByRole("region", { name: "列设置", exact: true })).toBeVisible();
    if (storyId.endsWith("--filtered-empty")) await page.getByRole("searchbox", { name: "搜索列", exact: true }).fill("不存在的列");
  }
  if (storyId.startsWith("patterns-catalog-maintenance-overview--")) await expect(page.getByRole("region", { name: "批量维护总览", exact: true })).toBeVisible();
  if (storyId.startsWith("patterns-catalog-unmatched-sources--")) await expect(page.getByRole("region", { name: "待归属来源核对", exact: true })).toBeVisible();
  if (storyId.startsWith("patterns-catalog-versions--")) {
    await expect(page.getByRole("region", { name: "目录版本记录", exact: true })).toBeVisible();
    if (storyId.endsWith("--refresh-failure")) {
      await page.getByRole("button", { name: "重新读取版本", exact: true }).click();
      await expect(page.getByRole("alert")).toContainText("无法读取目录版本");
    }
  }
  if (storyId.startsWith("patterns-catalog-read-feedback--")) await expect(page.getByRole("region", { name: "目录读取反馈", exact: true })).toBeVisible();
  if (storyId.startsWith("patterns-catalog-section-editors--")) {
    await expect(page.getByRole("region", { name: "当前分类编辑区", exact: true })).toBeVisible();
    if (/--(save-failure|refresh-failure)$/.test(storyId)) {
      await page.getByLabel("demo-styles-2 standard_name", { exact: true }).fill("虚构修改名称");
      await page.getByRole("button", { name: "保存当前分类修改（1行）", exact: true }).click();
      await expect(page.getByRole("alert")).toContainText(storyId.endsWith("--save-failure") ? "编辑内容已保留" : "草稿已保存，但最新明细读取失败");
    }
  }
  if (storyId.startsWith("patterns-catalog-pending-candidates--")) {
    if (storyId.endsWith("--empty")) await expect(page.getByText("当前商品没有候选批次", { exact: true })).toBeVisible();
    else await expect(page.getByRole("region", { name: "新变体与 Seller SKU 候选", exact: true })).toBeVisible();
  }
  if (storyId.startsWith("patterns-catalog-import-history--")) {
    await expect(page.getByRole("region", { name: "已有审核批次", exact: true })).toBeVisible();
  }
  if (storyId.startsWith("patterns-catalog-workbook--")) {
    await expect(page.getByRole("region", { name: "目录工作簿", exact: true })).toBeVisible();
  }
  if (storyId.startsWith("patterns-catalog-issue-summary--")) {
    await expect(page.getByRole("complementary", { name: "商品审核问题", exact: true })).toBeVisible();
  }
  if (storyId.startsWith("patterns-catalog-source-evidence--")) {
    if (storyId.endsWith("--loading")) await expect(page.getByRole("region", { name: "安全来源证据", exact: true })).toHaveAttribute("aria-busy", "true");
    else if (storyId.endsWith("--read-failure")) await expect(page.getByRole("alert")).toContainText("来源证据暂时不可用");
    else if (storyId.endsWith("--empty")) await expect(page.getByRole("heading", { name: "暂无来源证据", exact: true })).toBeVisible();
    else {
      const row = page.getByRole("listitem", { name: "来源 3", exact: true }); await expect(row).toBeVisible();
      if (/--(revealing|reveal-failure|revealed|boundary-change|long-identifier)$/.test(storyId)) {
        await row.getByRole("button", { name: "查看完整标识", exact: true }).click();
        if (storyId.endsWith("--revealing")) await expect(row.getByRole("button", { name: "正在校验权限", exact: true })).toBeDisabled();
        else if (storyId.endsWith("--reveal-failure")) await expect(row.getByRole("alert")).toContainText("权限未通过");
        else await expect(row.locator("output")).toBeVisible();
      }
    }
  }
  if (storyId.startsWith("patterns-catalog-identity-owners--") && !storyId.endsWith("--read-only")) {
    await page.getByRole("button", { name: "查看归属与冲突", exact: true }).click();
    if (storyId.endsWith("--loading")) {
      await expect(page.getByRole("region", { name: "身份归属与审核恢复", exact: true })).toHaveAttribute("aria-busy", "true");
    } else if (storyId.endsWith("--read-failure")) {
      await expect(page.getByRole("alert")).toContainText("归属读取暂时失败");
    } else {
      await expect(page.getByRole("region", { name: "身份归属", exact: true })).toBeVisible();
    }
    if (/--(restore-saving|restore-failure|refresh-failure|restored)$/.test(storyId)) {
      await page.getByRole("textbox", { name: "恢复审核原因", exact: true }).fill("虚构来源复核依据");
      await page.getByRole("button", { name: "恢复到待审核", exact: true }).click();
      if (storyId.endsWith("--restore-saving")) await expect(page.getByRole("textbox", { name: "恢复审核原因", exact: true })).toBeDisabled();
      else if (storyId.endsWith("failure")) await expect(page.getByRole("alert")).toContainText("示例");
      else await expect(page.getByText("草稿已恢复到待审核", { exact: true })).toBeVisible();
    }
  }
  if (storyId.startsWith("patterns-catalog-workflow-forms--")) {
    if (/--(reference|high-risk)$/.test(storyId)) {
      await page.getByRole("button", { name: "生成批准预览", exact: true }).click();
      await expect(page.getByRole("textbox", { name: "批准原因", exact: true })).toBeVisible();
    }
    if (/--(reference|rebase|saving|failure|blocked)$/.test(storyId)) {
      await page.getByText("高级操作 · 调整目录基准", { exact: true }).click();
      if (!storyId.endsWith("--blocked")) await page.getByRole("textbox", { name: "替代导出编号（export ID）", exact: true }).fill("8002");
    }
    if (/--(saving|failure)$/.test(storyId)) {
      await page.getByRole("button", { name: "调整到新基准", exact: true }).click();
      if (storyId.endsWith("--saving")) await expect(page.getByText("正在执行操作，请等待结果…", { exact: true })).toBeVisible();
      else await expect(page.getByRole("alert")).toContainText("输入内容已保留");
    }
  }
  if (/^pages-date-workbench--(cell-|save-failure)/.test(storyId)) {
    const cell = page.getByRole("textbox", { name: "Title，第 1 行", exact: true });
    await cell.focus();
    await expect(cell).toBeFocused();
  }
  if (storyId === "patterns-draft-data-table--filter-empty") {
    await page.getByRole("searchbox", { name: "搜索当前页", exact: true }).fill("no-matching-fictional-row");
    await expect(page.getByText("当前筛选没有匹配行", { exact: true })).toBeVisible();
  }
  if (storyId.startsWith("patterns-note-revision--")) {
    await page.getByRole("button", { name: "修订备注", exact: true }).click();
    const form = page.getByRole("form", { name: "备注修订 fictional-note-1", exact: true });
    await expect(form).toBeVisible();
    if (storyId.endsWith("--empty")) await form.getByRole("textbox").fill("");
    if (/--(saving|save-failure)$/.test(storyId)) {
      await form.getByRole("textbox").fill("虚构新修订依据");
      await form.getByRole("button", { name: "保存新修订", exact: true }).click();
      if (storyId.endsWith("--saving")) await expect(form.getByRole("textbox")).toBeDisabled();
      else await expect(form.getByRole("alert")).toContainText("修订内容已保留");
    }
  }

  if (storyId.startsWith("patterns-issue-review--")) {
    const panel = page.getByRole("region", { name: "校验问题", exact: true });
    await expect(panel).toBeVisible();
    if (/--(saving|save-failure)$/.test(storyId)) {
      await panel.getByRole("textbox", { name: "审核说明", exact: true }).fill("虚构审核依据");
      await panel.getByRole("button", { name: "确认警告", exact: true }).click();
      if (storyId.endsWith("--saving")) await expect(panel.getByRole("textbox")).toBeDisabled();
      else await expect(panel.getByRole("alert")).toContainText("说明已保留");
    }
  }

  if (storyId.startsWith("patterns-row-review--")) {
    const state = storyId.split("--")[1]!;
    const add = ["reference", "nullable", "no-source", "add-saving", "add-failure"].includes(state);
    if (state === "no-source") { await expect(page.getByRole("button", { name: "新增纠错行", exact: true })).toBeDisabled(); return; }
    await page.getByRole("button", { name: add ? "新增纠错行" : /管理第 1 行状态/, exact: add }).click();
    const drawer = page.getByRole("dialog", { name: add ? "新增纠错行" : "行状态操作", exact: true });
    if (state.startsWith("add-")) {
      await drawer.getByRole("textbox", { name: "新增行字段 sku", exact: true }).fill("A-02");
      await drawer.getByRole("textbox", { name: "新增行字段 sales", exact: true }).fill("55.10");
      await drawer.getByRole("button", { name: "保存新增行", exact: true }).click();
    }
    if (state.startsWith("state-")) await drawer.getByRole("button", { name: "排除这一行", exact: true }).click();
    if (state.startsWith("note-")) {
      await drawer.getByRole("button", { name: "修订备注", exact: true }).click();
      if (state === "note-failure") await drawer.getByRole("button", { name: "保存新修订", exact: true }).click();
    }
    if (state.endsWith("failure")) await expect(drawer.getByRole("alert")).toContainText("内容保留");
    if (state.endsWith("saving")) await expect(drawer.getByRole("button", { name: add ? "关闭新增纠错行" : "关闭行状态操作", exact: true })).toBeDisabled();
    if (!state.startsWith("note-")) await drawer.getByRole("region", { name: add ? "新增纠错行内容" : "行状态操作内容", exact: true }).locator("..").evaluate(el => { el.scrollTop = 0; });
  }

  if (storyId.startsWith("patterns-field-review--")) {
    const field = storyId.endsWith("--integer") ? "quantity" : storyId.endsWith("--long-text") ? "title" : "sales";
    await page.getByRole("button", { name: new RegExp(`${field}，当前值`) }).click();
    const drawer = page.getByRole("dialog", { name: "字段对照", exact: true });
    await expect(drawer).toBeVisible();
    if (/--(saving|save-failure)$/.test(storyId)) {
      await drawer.getByRole("button", { name: "保存字段修改", exact: true }).click();
      if (storyId.endsWith("--saving")) await expect(drawer.getByRole("textbox", { name: "当前值", exact: true })).toBeDisabled();
      else await expect(drawer.getByRole("alert")).toContainText("编辑内容保留");
    }
    if (/--note-(editing|failure)$/.test(storyId)) {
      await drawer.getByRole("button", { name: "修订备注", exact: true }).click();
      if (storyId.endsWith("--note-failure")) {
        await drawer.getByRole("button", { name: "保存新修订", exact: true }).click();
        await expect(drawer.getByRole("alert")).toContainText("编辑内容保留");
      }
    }
    if (!/--note-(editing|failure)$/.test(storyId)) await drawer.getByRole("region", { name: "字段对照内容", exact: true }).locator("..").evaluate(el => { el.scrollTop = 0; });
  }
  if (/^patterns-publication-confirmation--(return-(building|retrying|ready|superseded)|submitting|failure)$/.test(storyId)) {
    const dialog = page.getByRole("dialog", { name: "发布确认", exact: true });
    await dialog.getByRole("button", { name: "确认发布", exact: true }).click();
    if (storyId.endsWith("--failure")) await expect(dialog.getByRole("alert")).toContainText("说明已保留");
    else await expect(dialog.getByRole("textbox", { name: "发布说明", exact: true })).toBeDisabled();
  }
  if (storyId === "patterns-merge-decision-matrix--hidden-fields") {
    await page.getByRole("article", { name: "重复记录 1", exact: true }).getByText("查看两行的全部字段", { exact: true }).click();
  }

  if (/^pages-workspace-shell--navigation(-failure)?$/.test(storyId) && (page.viewportSize()?.width ?? 1280) <= 860) {
    await page.getByRole("button", { name: "打开主导航", exact: true }).click();
    await expect(page.getByRole("dialog", { name: "工作区导航", exact: true })).toBeVisible();
  }
  if (/^pages-import-evidence--revision-(editing|failure|saving)$/.test(storyId)) {
    await page.getByRole("button", { name: "修订备注", exact: true }).click();
    await expect(page.getByRole("textbox", { name: "修订备注 demo-batch-note-1", exact: true })).toBeVisible();
    if (!storyId.endsWith("--revision-editing")) {
      await page.getByRole("button", { name: "保存新修订", exact: true }).click();
      if (storyId.endsWith("--revision-failure")) await expect(page.getByRole("alert")).toContainText("内容已保留");
      else await expect(page.getByRole("button", { name: "正在保存新修订", exact: true })).toBeDisabled();
    }
  }
  if (storyId === "pages-draft-review--publication-failure") {
    const dialog = page.getByRole("dialog", { name: "发布确认", exact: true });
    await dialog.getByRole("button", { name: "确认发布", exact: true }).click();
    await expect(dialog.getByRole("alert")).toContainText("发布指针已变化");
  }
  if (storyId.startsWith("pages-catalog-editors--")) {
    const state = storyId.split("--")[1] ?? "";
    if (state === "editing") await expect(page.getByRole("button", { name: "生成变更预览", exact: true })).toBeEnabled();
    else if (state === "preview") await expect(page.getByRole("table", { name: "变更预览", exact: true })).toBeVisible();
    else if (state === "preparing") await expect(page.getByRole("button", { name: "正在生成预览", exact: true })).toBeDisabled();
    else if (["prepare-failure", "approval-failure", "refresh-failure", "unsaved", "read-failure", "save-failure"].includes(state)) await expect(page.getByRole("alert")).toBeVisible();
    else if (state === "loading") await expect(page.getByRole("status", { name: "正在读取分类", exact: true })).toBeVisible();
    else if (state === "empty") await expect(page.getByText("尚无分类，从右侧新建", { exact: true })).toBeVisible();
    else if (state === "saved") await expect(page.getByText("分类已保存", { exact: true })).toBeVisible();
    else await expect(page.getByRole("button", { name: "编辑 短款连衣裙", exact: true })).toBeVisible();
  }
  if (storyId.startsWith("pages-catalog-style-detail--") && /--(aliases-loading|aliases-failure|evidence|evidence-failure)$/.test(storyId)) {
    const variant = page.getByRole("article", { name: "变体 DEMO-01-BLUE-S", exact: true });
    await variant.getByRole("button", { name: "展开 Seller SKU", exact: true }).click();
    if (storyId.endsWith("--aliases-loading")) await expect(variant.getByRole("status", { name: "正在读取关联 Seller SKU" })).toBeVisible();
    else if (storyId.endsWith("--aliases-failure")) await expect(variant.getByRole("alert")).toBeVisible();
    else {
      await expect(variant.getByRole("table")).toBeVisible();
      await variant.getByRole("button", { name: "查看来源明细", exact: true }).click();
      if (storyId.endsWith("--evidence-failure")) await expect(variant.getByRole("alert")).toBeVisible();
      else await expect(variant.getByText("来源文件：demo-returns.csv", { exact: true })).toBeVisible();
    }
  }
  if (storyId.includes("catalog-product-list--quick-view")) {
    await page.getByRole("button", { name: "快速查看 DEMO-01", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "商品快速查看" });
    await expect(dialog).toBeVisible();
    if (storyId.endsWith("--quick-view-loading")) await expect(dialog.getByRole("status", { name: "正在读取商品详情" })).toBeVisible();
    else if (storyId.endsWith("--quick-view-failure")) await expect(dialog.getByRole("alert")).toBeVisible();
    else await expect(dialog.getByRole("table", { name: "商品快速查看变体" })).toBeVisible();
  }
  if (storyId.endsWith("catalog-import-review--pending-changes")) {
    await expect(page.locator("details[open] ins").filter({ hasText: "示例 · 暖灰直筒长裤" })).toBeVisible();
    await expect(page.getByRole("button", { name: "保存当前分类修改（2行）", exact: true })).toBeEnabled();
  }
  if (storyId.endsWith("catalog-import-review--save-failure") || storyId.endsWith("catalog-import-review--refresh-failure")) {
    await page.getByLabel("demo-style-1 standard_name", { exact: true }).fill("示例审核名称");
    await page.getByRole("button", { name: "保存当前分类修改（1行）", exact: true }).click();
    await expect(page.getByText(storyId.endsWith("--save-failure") ? /编辑内容已保留/ : /草稿已保存，但最新明细读取失败/)).toBeVisible();
  }
  if (storyId.endsWith("dialog-interaction")) {
    await page.getByRole("button", { name: "打开发布确认" }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
  }
  if (storyId.endsWith("composite-interactions")) {
    await page.getByRole("tab", { name: "产品总表" }).click();
    await page.getByRole("button", { name: "更多操作" }).click();
    await expect(page.getByRole("menu")).toBeVisible();
  }
}

export function screenshotName(storyId: string, viewportName: string): string {
  return `${storyId.replace("design-system-", "")}-${viewportName}.png`;
}
