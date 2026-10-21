import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SeriesSelector } from "./SeriesSelector";

const available=Array.from({length:9},(_,index)=>({active:true,dimension:"color" as const,key:`k${index}`,label:`颜色 ${index}`,sort_order:index,total:{} as never}));
describe("SeriesSelector",()=>{
  it("blocks a ninth series without changing the selected array",()=>{const change=vi.fn();render(<SeriesSelector available={available} onChange={change} selected={available.slice(0,8).map(item=>item.key)}/>);expect(screen.getByRole("checkbox",{name:"颜色 8"})).toBeDisabled();expect(screen.getByText("已选 8 / 9 种颜色 · 同时最多对比 8 项")).toBeVisible();expect(change).not.toHaveBeenCalled();});
  it("keeps at least one available series",()=>{const change=vi.fn();render(<SeriesSelector available={available.slice(0,2)} onChange={change} selected={["k0"]}/>);expect(screen.getByText("已选 1 / 2 种颜色")).toBeVisible();fireEvent.click(screen.getByRole("checkbox",{name:"颜色 0"}));expect(screen.getByText("至少选择 1 项进行对比。")).toBeInTheDocument();expect(change).not.toHaveBeenCalled();});
});
