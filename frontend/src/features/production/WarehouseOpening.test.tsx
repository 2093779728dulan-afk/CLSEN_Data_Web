import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { cleanup } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { AuthzGenerationProvider } from '../../app/AuthzGenerationContext';
import { WarehouseOpeningDialog } from './WarehouseOpening';
const api=vi.hoisted(()=>({read:vi.fn<(path:string)=>Promise<unknown>>(),write:vi.fn<(path:string,options:{body:Record<string,unknown>})=>Promise<unknown>>()}));
vi.mock('../../api/client',async original=>({...await original<typeof import('../../api/client')>(),requestApi:api.read,writeApi:api.write}));
beforeEach(()=>{api.read.mockImplementation((path:string)=>Promise.resolve(path.includes('/skus?')?{items:[{sku_id:'11',code:'1112-Black-L',label:'1112 Black L'}]}:{opening_enabled:true,scopes:[]}));api.write.mockReset();});
afterEach(cleanup);
function mount(){const saved=vi.fn(),close=vi.fn();render(<AuthzGenerationProvider boundary={{principalId:1,roles:["admin"],siteId:1,siteConfigVersionId:1}} onRevoked={()=>undefined}><RouterProvider router={createMemoryRouter([{path:'*',element:<WarehouseOpeningDialog warehouseId="1" name="广州成品仓" saved={saved} close={close}/>}])}/></AuthzGenerationProvider>);return{saved,close};}
it('requires explicit zero, previews before confirming and retains warehouse identity',async()=>{
 const {saved}=mount();const user=userEvent.setup();const field=await screen.findByRole('textbox',{name:'1112-Black-L合格期初'});expect(field).toHaveValue('');await user.type(screen.getByLabelText(/^期初截止日期/),'2026-10-01');await user.type(screen.getByLabelText(/^期初依据/),'虚构空仓从零开始');await user.click(screen.getByRole('button',{name:'本仓全部规格设为零期初'}));api.write.mockResolvedValueOnce({preview:true}).mockResolvedValueOnce({revision:'1'});await user.click(screen.getByRole('button',{name:'预览期初库存'}));await screen.findByText('预览通过，尚未建账');expect(saved).not.toHaveBeenCalled();await user.click(screen.getByRole('button',{name:'确认期初库存'}));await waitFor(()=>expect(saved).toHaveBeenCalledTimes(1));expect(api.write.mock.calls[1]![1].body).toMatchObject({warehouse_id:'1',owner_id:'1',lines:[{sku_id:'11',quality:'QUALIFIED',units:'0'},{sku_id:'11',quality:'PENDING',units:'0'},{sku_id:'11',quality:'DEFECTIVE',units:'0'}]});
});
it('blocks closing dirty input until explicitly discarded',async()=>{
 const {close}=mount();await screen.findByLabelText('1112-Black-L合格期初');const user=userEvent.setup();await user.click(screen.getByRole('button',{name:'本仓全部规格设为零期初'}));await user.click(screen.getByRole('button',{name:'关闭对话框'}));expect(close).not.toHaveBeenCalled();expect(screen.getByRole('dialog',{name:'还有未保存的期初内容'})).toBeVisible();await user.click(screen.getByRole('button',{name:'放弃并关闭'}));expect(close).toHaveBeenCalledTimes(1);
});
