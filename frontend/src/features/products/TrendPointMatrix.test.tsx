import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TrendPointMatrix } from "./TrendPointMatrix";

describe("TrendPointMatrix",()=>{it("uses exact server values and explicit missing/undefined copy",()=>{render(<TrendPointMatrix labels={new Map([["a","红色"],["b","蓝色"]])} metric="conversion" series={[{key:"a",points:[{date:"2026-08-01",denominator:2,null_reason:null,numerator:1,source_completeness:"complete",value:"0.500000",value_state:"observed"}]},{key:"b",points:[{date:"2026-08-01",denominator:0,null_reason:"undefined_denominator",numerator:0,source_completeness:"complete",value:null,value_state:"undefined_denominator"}]}]}/>);expect(screen.getByText("0.500000")).toBeVisible();expect(screen.getByText("分母为 0")).toBeVisible();});});
