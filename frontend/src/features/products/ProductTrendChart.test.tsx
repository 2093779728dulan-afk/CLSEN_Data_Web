import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ProductTrendChart } from "./ProductTrendChart";

const point=(date:string,value:number|string|null,state:"observed"|"zero"|"missing_report"="observed")=>({date,denominator:null,null_reason:value===null?"missing_report" as const:null,numerator:null,source_completeness:value===null?"partial" as const:"complete" as const,value,value_state:state});
describe("ProductTrendChart",()=>{
  it("keeps series color and dash stable when selections or available ordering change",()=>{
    const a={key:"a",points:[point("2026-01-01",1),point("2026-01-02",2)]};
    const b={key:"b",points:[point("2026-01-01",2),point("2026-01-02",3)]};
    const {container,rerender}=render(<ProductTrendChart labels={new Map([["b","B"],["a","A"]])} metric="units" series={[a,b]}/>);
    const original=container.querySelectorAll("polyline")[1]!;
    const color=original.getAttribute("stroke");const dash=original.getAttribute("stroke-dasharray");
    rerender(<ProductTrendChart labels={new Map([["a","A"],["b","B"]])} metric="units" series={[b]}/>);
    expect(container.querySelector("polyline")).toHaveAttribute("stroke",color);
    expect(container.querySelector("polyline")).toHaveAttribute("stroke-dasharray",dash);
    expect(screen.getByRole("button",{name:"B"}).querySelector("line")).toHaveAttribute("stroke",color);
    rerender(<ProductTrendChart labels={new Map([["a","A"],["b","B"]])} metric="units" series={[b,a]}/>);
    expect(container.querySelector("polyline")).toHaveAttribute("stroke",color);
  });
  it("measures tall tooltips and moves them inside the viewport",()=>{
    const {container}=render(<ProductTrendChart labels={new Map([["a","A"]])} metric="units" series={[{key:"a",points:[point("2026-01-01",1),point("2026-01-02",2)]}]}/>);
    const svg=screen.getByRole("img",{name:/产品每日趋势/});
    const box={left:0,top:650,width:760,height:292,right:760,bottom:942,x:0,y:650,toJSON:()=>({})};
    vi.spyOn(svg,"getBoundingClientRect").mockReturnValue(box);
    vi.spyOn(container.querySelector("figure")!,"getBoundingClientRect").mockReturnValue(box);
    const measure=vi.spyOn(HTMLDivElement.prototype,"getBoundingClientRect").mockReturnValue({...box,top:700,height:260,bottom:960,width:280});
    try{
      fireEvent(svg,new MouseEvent("pointermove",{bubbles:true,clientX:740,clientY:670}));
      expect(screen.getByRole("tooltip")).toHaveStyle({top:`${window.innerHeight-260-8-700}px`});
      fireEvent.scroll(window);
      expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    }finally{measure.mockRestore();}
  });
  it("groups only coincident points, excludes distinct or missing values, and clears stale tooltips",()=>{
    const series=[{key:"a",points:[point("2026-01-01",0,"zero"),point("2026-01-02",2)]},{key:"b",points:[point("2026-01-01",0,"zero"),point("2026-01-02",3)]},{key:"c",points:[point("2026-01-01",null,"missing_report"),point("2026-01-02",4)]}];
    const {container,rerender}=render(<ProductTrendChart labels={new Map([["a","A"],["b","B"],["c","C"]])} metric="units" series={series}/>);
    const svg=screen.getByRole("img",{name:/产品每日趋势/});
    const box={left:0,top:0,width:760,height:292,right:760,bottom:292,x:0,y:0,toJSON:()=>({})};
    vi.spyOn(svg,"getBoundingClientRect").mockReturnValue(box);
    vi.spyOn(container.querySelector("figure")!,"getBoundingClientRect").mockReturnValue(box);
    fireEvent.click(screen.getByRole("button",{name:"A"}));
    fireEvent(svg,new MouseEvent("pointermove",{bubbles:true,clientX:92,clientY:250}));
    const tip=within(screen.getByRole("tooltip"));
    expect(tip.getByText("A")).toBeVisible();expect(tip.getByText("B")).toBeVisible();expect(tip.getAllByText("0")).toHaveLength(2);expect(tip.queryByText("C")).not.toBeInTheDocument();expect(tip.getByText(/2 个重合点/)).toBeVisible();
    fireEvent.change(screen.getByRole("slider"),{target:{value:"1"}});
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    fireEvent(svg,new MouseEvent("pointermove",{bubbles:true,clientX:740,clientY:20}));
    expect(within(screen.getByRole("tooltip")).getByText("4")).toBeVisible();
    expect(within(screen.getByRole("tooltip")).queryByText("3")).not.toBeInTheDocument();
    rerender(<ProductTrendChart labels={new Map()} metric="units" series={[...series]}/>);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });
  it("shows the hovered point's exact value near the right edge and dismisses on leave",()=>{
    const {container}=render(<ProductTrendChart labels={new Map([["a","示例商品"]])} metric="sales" series={[{key:"a",points:[point("2026-01-01","1234.10"),point("2026-01-02","1235.20")]}]}/>);
    const svg=screen.getByRole("img",{name:/产品每日趋势/});
    const box={left:0,top:0,width:760,height:292,right:760,bottom:292,x:0,y:0,toJSON:()=>({})};
    vi.spyOn(svg,"getBoundingClientRect").mockReturnValue(box);
    vi.spyOn(container.querySelector("figure")!,"getBoundingClientRect").mockReturnValue(box);
    fireEvent(svg,new MouseEvent("pointermove",{bubbles:true,clientX:740,clientY:20}));
    expect(svg.querySelector(":scope > title")).toBeNull();
    expect(svg).toHaveAccessibleDescription(/缺失点不连线/);
    expect(screen.getAllByRole("tooltip")).toHaveLength(1);
    expect(screen.getByRole("tooltip")).toHaveTextContent("2026-01-02销售额（报告原币）示例商品1,235.20");
    expect(screen.getByRole("tooltip")).toHaveStyle({left:"472px"});
    fireEvent.pointerLeave(svg);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });
  it("renders exact axes and an accessible non-color legend",()=>{render(<ProductTrendChart labels={new Map([["a","红色"]])} metric="units" series={[{key:"a",points:[point("2026-01-01",-1),point("2026-01-02",0,"zero")]}]}/>);expect(screen.getByRole("img",{name:/产品每日趋势/})).toBeVisible();expect(screen.getByRole("button",{name:"红色"})).toBeVisible();expect(screen.getAllByText("-1").length).toBeGreaterThan(0);expect(screen.getByText("01-01")).toBeVisible();expect(screen.getByText("01-02")).toBeVisible();});
  it("breaks a line at null gaps",()=>{const {container}=render(<ProductTrendChart labels={new Map([["a","A"]])} metric="units" series={[{key:"a",points:[point("2026-01-01",1),point("2026-01-02",null,"missing_report"),point("2026-01-03",2)]}]}/>);expect(container.querySelectorAll("circle")).toHaveLength(2);expect(container.querySelectorAll("polyline")).toHaveLength(0);});
  it("formats decimal coordinates without converting business values to floating point",()=>{render(<ProductTrendChart labels={new Map([["a","A"]])} metric="sales" series={[{key:"a",points:[point("2026-01-01","1234.10"),point("2026-01-02","1235.20")]}]}/>);expect(screen.getAllByText("1,235.20").length).toBeGreaterThan(0);expect(screen.getAllByText("1,234.10").length).toBeGreaterThan(0);});
  it("inspects exact daily values and distinguishes missing reports from zero", () => {
    const { container } = render(<ProductTrendChart labels={new Map([["a", "A"], ["b", "B"]])} metric="sales" series={[
      {key:"a",points:[point("2026-01-01","1234.10"),point("2026-01-02",null,"missing_report")]},
      {key:"b",points:[point("2026-01-01","0.00","zero"),point("2026-01-02","2.00")]},
    ]} />);
    const values = within(container.querySelector("dl")!);
    expect(values.getByText("无报表")).toBeVisible();
    fireEvent.change(screen.getByRole("slider",{name:"查看日期"}),{target:{value:"0"}});
    expect(values.getByText("1,234.10")).toBeVisible();
    expect(values.getByText("0.00")).toBeVisible();
    expect(values.queryByText("无报表")).not.toBeInTheDocument();
    expect(screen.getByRole("slider")).toHaveAttribute("aria-valuetext","2026-01-01");
  });
  it("toggles series emphasis and point markers without changing the supplied series", () => {
    const { container } = render(<ProductTrendChart labels={new Map([["a","A"],["b","B"]])} metric="units" series={[
      {key:"a",points:[point("2026-01-01",1),point("2026-01-02",2)]},
      {key:"b",points:[point("2026-01-01",3),point("2026-01-02",4)]},
    ]} />);
    fireEvent.click(screen.getByRole("button",{name:"A"}));
    expect(screen.getByRole("button",{name:"A"})).toHaveAttribute("aria-pressed","true");
    expect(container.querySelectorAll('g[opacity="0.18"]')).toHaveLength(1);
    fireEvent.click(screen.getByRole("button",{name:"恢复全部曲线"}));
    expect(container.querySelectorAll('g[opacity="0.18"]')).toHaveLength(0);
    fireEvent.click(screen.getByRole("checkbox",{name:"数据点"}));
    expect(container.querySelectorAll('circle[opacity="1"]')).toHaveLength(2);
    expect(container.querySelectorAll("polyline")).toHaveLength(2);
  });
  it("replays growth explicitly without restarting on daily inspection or changing geometry", () => {
    const {container}=render(<ProductTrendChart labels={new Map([["a","A"]])} metric="units" series={[{key:"a",points:[point("2026-01-01",1),point("2026-01-02",2)]}]} />);
    const line=container.querySelector("polyline")!;
    const geometry=line.getAttribute("points");
    fireEvent.change(screen.getByRole("slider"),{target:{value:"0"}});
    expect(container.querySelector("polyline")).toBe(line);
    fireEvent.click(screen.getByRole("button",{name:"重播动画"}));
    expect(container.querySelector("polyline")).not.toBe(line);
    expect(container.querySelector("polyline")).toHaveAttribute("points",geometry);
    expect(screen.getByRole("slider")).toHaveAttribute("aria-valuetext","2026-01-01");
  });
});
