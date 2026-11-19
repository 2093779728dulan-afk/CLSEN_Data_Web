import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import { StyleDisplayPicker } from './StyleDisplayPicker';

const styles = [{ id: '1', style_code: '1101', sku_count: 2 }, { id: '2', style_code: '1102', sku_count: 3 }];

it('can explicitly save all current styles from the default display', async () => {
  const save = vi.fn().mockResolvedValue(undefined);
  render(<StyleDisplayPicker styles={styles} selected={[]} busy={false} unknown={false} save={save} close={vi.fn()} onDirtyChange={vi.fn()} />);
  await userEvent.click(screen.getByRole('button', { name: '全选' }));
  await userEvent.click(screen.getByRole('button', { name: '保存展示款号' }));
  await waitFor(() => expect(save).toHaveBeenCalledWith(['1','2']));
});

it('saves selected stable style IDs and keeps all styles available for selection', async () => {
  const save = vi.fn().mockResolvedValue(undefined), close = vi.fn();
  render(<StyleDisplayPicker styles={styles} selected={[]} busy={false} unknown={false} save={save} close={close} onDirtyChange={vi.fn()} />);
  await userEvent.click(screen.getByRole('button', { name: '清空选择' }));
  expect(screen.getByRole('button', { name: '保存展示款号' })).toBeDisabled();
  await userEvent.click(screen.getByRole('checkbox', { name: /1101/ }));
  await userEvent.click(screen.getByRole('button', { name: '保存展示款号' }));
  await waitFor(() => expect(save).toHaveBeenCalledWith(['1']));
  expect(close).toHaveBeenCalledOnce();
});

it('retains draft selections when a concurrent save is rejected', async () => {
  const save = vi.fn().mockResolvedValue('设置已有新修订，输入已保留。');
  render(<StyleDisplayPicker styles={styles} selected={['1']} busy={false} unknown={false} save={save} close={vi.fn()} onDirtyChange={vi.fn()} />);
  await userEvent.click(screen.getByRole('checkbox', { name: /1102/ }));
  await userEvent.click(screen.getByRole('button', { name: '保存展示款号' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('输入已保留');
  expect(screen.getByRole('checkbox', { name: /1102/ })).toBeChecked();
});

it('protects unsaved selections when closing', async () => {
  const close = vi.fn();
  render(<StyleDisplayPicker styles={styles} selected={['1']} busy={false} unknown={false} save={vi.fn()} close={close} onDirtyChange={vi.fn()} />);
  await userEvent.click(screen.getByRole('checkbox', { name: /1102/ }));
  await userEvent.click(screen.getByRole('button', { name: '取消' }));
  expect(await screen.findByRole('dialog', { name: '还有未保存的展示款号' })).toBeVisible();
  expect(close).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole('button', { name: '放弃修改' }));
  expect(close).toHaveBeenCalledOnce();
});
