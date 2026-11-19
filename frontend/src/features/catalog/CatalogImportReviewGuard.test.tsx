import { render,waitFor,cleanup } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach,it,expect,vi } from 'vitest';
import { CatalogImportReview } from './CatalogImportReview';
import type {CatalogImportSummary} from './catalogTypes';
const api=vi.hoisted(()=>({command:vi.fn()}));
vi.mock('./catalogApi',async original=>({...await original<typeof import('./catalogApi')>(),catalogCommand:api.command}));
afterEach(()=>{cleanup();vi.resetAllMocks();});
const imported={import_id:1,status:'in_review',source_kind:'online',workflow_revision:2,permissions:{can_validate:true,can_edit:false}} as CatalogImportSummary;
const rows={styles:[],skus:[],mappings:[],exceptions:[],evidence:[]};
it('propagates workflow busy state from the review into the outer wizard',async()=>{
 const guard=vi.fn();api.command.mockImplementation(()=>new Promise(()=>undefined));
 render(<MemoryRouter><CatalogImportReview embedded imported={imported} rowsBySection={rows} onGuardChange={guard} onReload={vi.fn()} onSaved={vi.fn()} onWorkflowChanged={vi.fn()}/></MemoryRouter>);
 await waitFor(()=>expect(guard).toHaveBeenLastCalledWith(expect.objectContaining({busy:true})));
});
it('allows leaving after a read-only refresh failure without reporting an uncertain write',async()=>{
 const guard=vi.fn();render(<MemoryRouter><CatalogImportReview embedded imported={imported} rowsBySection={rows} error="读取中断" onGuardChange={guard} onReload={vi.fn()} onSaved={vi.fn()} onWorkflowChanged={vi.fn()}/></MemoryRouter>);
 await waitFor(()=>expect(guard).toHaveBeenLastCalledWith({dirty:false,busy:false,unknown:false}));
});
