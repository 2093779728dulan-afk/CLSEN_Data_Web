import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { CatalogCategoryEditor } from "./CatalogCategoryEditor";
import { listCatalogCategories, updateCatalogCategory } from "./catalogApi";
vi.mock("./catalogApi", () => ({ listCatalogCategories: vi.fn(), updateCatalogCategory: vi.fn(), createCatalogCategory: vi.fn() }));
it("saves an edited code against the same category identity", async () => {
  vi.mocked(listCatalogCategories).mockResolvedValue([{ category_id: 7, code: "SHIRT", display_name: "衬衫", aliases: [], status: "enabled" }]);
  const user = userEvent.setup();
  render(<CatalogCategoryEditor />);
  await user.click(screen.getByRole("button", { name: "管理分类" }));
  await user.click(await screen.findByRole("button", { name: "编辑 衬衫" }));
  const field = await screen.findByRole("textbox", { name: "分类 7 代码" });
  await user.clear(field);
  await user.type(field, "shirt_new");
  await user.click(screen.getByRole("button", { name: "保存修改" }));
  await waitFor(() => expect(updateCatalogCategory).toHaveBeenCalledWith(expect.objectContaining({ category_id: 7, code: "SHIRT_NEW" })));
});

it("rejects spaces in code with a Chinese inline explanation", async () => {
  vi.mocked(listCatalogCategories).mockResolvedValue([]);
  const user = userEvent.setup();
  render(<CatalogCategoryEditor />);
  await user.click(screen.getByRole("button", { name: "管理分类" }));
  await user.type(await screen.findByRole("textbox", { name: "分类代码" }), "Mini dress");
  await user.type(screen.getByRole("textbox", { name: "分类名称" }), "短款连衣裙");
  await user.click(screen.getByRole("button", { name: "创建分类" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("不能含空格");
});

it("keeps unsaved edits when switching categories and cancels without a write", async () => {
  vi.mocked(listCatalogCategories).mockResolvedValue([{ category_id: 7, code: "DRESS", display_name: "连衣裙", aliases: [], status: "enabled" }, { category_id: 8, code: "DRESS_MINI", display_name: "短款连衣裙", parent_category_id: 7, aliases: [], status: "enabled" }]);
  const user = userEvent.setup();
  render(<CatalogCategoryEditor />);
  await user.click(screen.getByRole("button", { name: "管理分类" }));
  await user.click(await screen.findByRole("button", { name: "编辑 短款连衣裙" }));
  expect(screen.getByRole("combobox", { name: "上级分类" })).toHaveValue("7");
  await user.type(screen.getByRole("textbox", { name: "分类名称" }), "修改");
  await user.click(screen.getByRole("button", { name: "编辑 连衣裙" }));
  expect(screen.getByRole("alert")).toHaveTextContent("尚未保存");
  expect(screen.getByRole("textbox", { name: "分类名称" })).toHaveValue("短款连衣裙修改");
  await user.click(screen.getByRole("button", { name: "取消修改" }));
  expect(screen.getByRole("textbox", { name: "分类名称" })).toHaveValue("短款连衣裙");
  await user.click(screen.getByRole("button", { name: "编辑 连衣裙" }));
  expect(screen.getByRole("textbox", { name: "分类名称" })).toHaveValue("连衣裙");
});

it("uses a separate folder toggle without changing the selected category", async () => {
  vi.mocked(listCatalogCategories).mockResolvedValue([{ category_id: 7, code: "DRESS", display_name: "连衣裙", aliases: [], status: "enabled" }, { category_id: 8, code: "DRESS_MINI", display_name: "短款连衣裙", parent_category_id: 7, aliases: [], status: "enabled" }]);
  const user = userEvent.setup();
  render(<CatalogCategoryEditor />);
  await user.click(screen.getByRole("button", { name: "管理分类" }));
  expect(await screen.findByRole("button", { name: "编辑 短款连衣裙" })).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "收起 连衣裙" }));
  expect(screen.queryByRole("button", { name: "编辑 短款连衣裙" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "展开 连衣裙" })).toHaveAttribute("aria-expanded", "false");
  await user.click(screen.getByRole("button", { name: "编辑 连衣裙" }));
  expect(screen.getByRole("textbox", { name: "分类名称" })).toHaveValue("连衣裙");
});

it("opens the matching parent when searching for a subcategory", async () => {
  vi.mocked(listCatalogCategories).mockResolvedValue([{ category_id: 7, code: "DRESS", display_name: "连衣裙", aliases: [], status: "enabled" }, { category_id: 8, code: "DRESS_MINI", display_name: "短款连衣裙", parent_category_id: 7, aliases: [], status: "enabled" }]);
  const user = userEvent.setup();
  render(<CatalogCategoryEditor />);
  await user.click(screen.getByRole("button", { name: "管理分类" }));
  await user.click(screen.getByRole("button", { name: "收起 连衣裙" }));
  await user.type(screen.getByRole("textbox", { name: "查找分类" }), "DRESS_MINI");
  expect(await screen.findByRole("button", { name: "编辑 短款连衣裙" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "收起 连衣裙" })).toHaveAttribute("aria-expanded", "true");
});
