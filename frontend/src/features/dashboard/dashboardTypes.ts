import type { ReturnBreakdown, ReturnDashboard } from "../../api/generated";

export type PublishedReturnBreakdown = ReturnBreakdown;

export type PublishedReturnDashboard = ReturnDashboard;

export type ReturnBasis = PublishedReturnDashboard["basis"];
