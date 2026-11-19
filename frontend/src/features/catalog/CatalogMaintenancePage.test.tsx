import { render, screen, cleanup, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { CatalogMaintenancePage } from "./CatalogMaintenancePage";
const api=vi.hoisted(()=>({current:vi.fn(),read:vi.fn()}));
vi.mock('./catalogApi',()=>({getCurrentCatalog:api.current}));
vi.mock('../../api/client',()=>({requestApi:api.read}));
vi.mock('./CatalogGuidedFlow',()=>({CatalogGuidedFlow:({onClosed}:{onClosed:()=>void})=><><button>开始准备流程</button><button onClick={onClosed}>模拟完成操作</button></>}));
afterEach(()=>{cleanup();vi.resetAllMocks();});
it('keeps the preparation entry and history available without an initialized catalog',async()=>{
 api.current.mockResolvedValue(null);api.read.mockResolvedValue({items:[],has_next:false});
 render(<MemoryRouter><CatalogMaintenancePage/></MemoryRouter>);
 expect(await screen.findByText('尚未建立目录')).toBeVisible();expect(screen.getByRole('button',{name:'开始准备流程'})).toBeEnabled();
 expect(await screen.findByText('暂无审核批次')).toBeVisible();expect(screen.queryByRole('navigation',{name:'审核批次分页'})).not.toBeInTheDocument();
});
it('recovers a failed catalog read and retains the approved version and history links',async()=>{
 api.current.mockRejectedValueOnce(Error('读取失败')).mockResolvedValue({version_number:4});api.read.mockResolvedValue({items:[{import_id:7,source_kind:'xlsx',workflow_revision:3,status:'needs_attention'}],has_next:false});
 render(<MemoryRouter><CatalogMaintenancePage/></MemoryRouter>);
 await userEvent.click(await screen.findByRole('button',{name:'重新读取'}));expect(await screen.findByText('当前目录 V4')).toBeVisible();
 expect(await screen.findByRole('link',{name:'批次 #7 · 继续审核'})).toHaveAttribute('href','/catalog/imports/7');
});

it('refreshes the unified version and batch list after a task closes',async()=>{
 api.current.mockResolvedValueOnce({version_number:1}).mockResolvedValue({version_number:2});api.read.mockResolvedValue({items:[],has_next:false});
 render(<MemoryRouter><CatalogMaintenancePage/></MemoryRouter>);await screen.findByText('当前目录 V1');await waitFor(()=>expect(api.read).toHaveBeenCalledTimes(1));
 await userEvent.click(screen.getByRole('button',{name:'模拟完成操作'}));expect(await screen.findByText('当前目录 V2')).toBeVisible();await waitFor(()=>expect(api.read).toHaveBeenCalledTimes(2));
});
