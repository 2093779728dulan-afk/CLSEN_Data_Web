import { Button, EmptyState, ErrorState } from "../../design-system";
import styles from "./PublishedDetailLedgerPage.module.css";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { ApiRequestError } from "../../api/client";
import type { Principal } from "../../api/types";
import type { DataTableSort, SortCommand } from "../../components/data-table/DataTableHeader";
import {
  isPublicationScopeChangedError,
  loadPublishedRange,
  loadPublishedRows,
  loadPublishedSummaries,
} from "./publishedDetailsApi";
import {
  parsePublishedDetailsSearch,
  serializePublishedDetailsSearch,
  updatePublishedDetailsViewState,
} from "./publishedDetailsState";
import type {
  PublishedDetailsViewState,
  PublishedRowsResponse,
  PublishedSummaryResponse,
} from "./publishedDetailsTypes";
import {
  PublishedDateSummaries,
  type PublishedDateExpansion,
} from "./PublishedDateSummaries";
import { ReadonlyPublishedDataGrid } from "./ReadonlyPublishedDataGrid";
import { PublishedDetailLedgerView } from "./PublishedDetailLedgerView";


export type PublishedDetailLedgerPageProps = {
  principal: Principal;
  reportingTimezone: string;
  siteId: number;
  today: string;
};

type LoadedSummary = {
  key: string;
  response: PublishedSummaryResponse;
};

type SummaryFailure = {
  key: string;
  message: string;
};

type LoadedRows = {
  key: string;
  response: PublishedRowsResponse;
};

type RowsFailure = {
  key: string;
  message: string;
};

type ActiveRequest = {
  controller: AbortController;
  generation: number;
  key: string;
};

type ScopeToken = {
  key: string;
  value: string;
};

type RangeResolution =
  | { status: "idle" }
  | { ownerKey: string; status: "loading" }
  | { ownerKey: string; status: "empty" }
  | { message: string; ownerKey: string; status: "error" };

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
const CONFLICT_NOTICE = "发布数据已更新，正在重新读取";

function scopeKey(view: Pick<PublishedDetailsViewState, "from" | "reportType" | "to">): string {
  return `${view.reportType}\n${view.from}\n${view.to}`;
}

function summaryKey(view: Pick<PublishedDetailsViewState, "from" | "page" | "reportType" | "search" | "to">): string {
  return `${scopeKey(view)}\n${view.search}\n${view.page}`;
}

function expansionKey(view: PublishedDetailsViewState, reportDate: string): string {
  return `${scopeKey(view)}\n${view.search}\n${view.sortColumnId ?? ""}\n${view.direction}\n${reportDate}`;
}

function rowsKey(view: Pick<PublishedDetailsViewState, "direction" | "from" | "page" | "reportType" | "search" | "sortColumnId" | "to">): string {
  return `${scopeKey(view)}\n${view.search}\n${view.sortColumnId ?? ""}\n${view.direction}\n${view.page}`;
}

function rangeOwnerKey(view: PublishedDetailsViewState, rawSearch: string): string {
  return `${view.reportType}\n${rawSearch}`;
}

function isValidResolvedRange(from: string, to: string): boolean {
  return ISO_DATE.test(from) && ISO_DATE.test(to) && from <= to;
}

function dateWithinRange(value: string | undefined, from: string, to: string): boolean {
  return Boolean(value && ISO_DATE.test(value) && from <= value && value <= to);
}

function rollingRange(today: string, days: number): { from: string; to: string } {
  const date = new Date(`${today}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() - (days - 1));
  return { from: date.toISOString().slice(0, 10), to: today };
}

function safeSummaryError(error: unknown): string {
  return error instanceof ApiRequestError && error.status === 403
    ? "当前账号无法读取这个已发布范围。"
    : "无法读取已发布明细，请稍后重试。";
}

export function PublishedDetailLedgerPage({
  principal,
  reportingTimezone,
  siteId,
  today,
}: PublishedDetailLedgerPageProps) {
  const [searchParams, setSearchParams] = useSearchParams();
  const rawSearch = searchParams.toString();
  const view = useMemo(
    () => parsePublishedDetailsSearch(new URLSearchParams(rawSearch), today),
    [rawSearch, today],
  );
  const currentSummaryKey = summaryKey(view);
  const currentScopeKey = scopeKey(view);
  const currentRangeOwnerKey = rangeOwnerKey(view, rawSearch);
  const [loadedSummary, setLoadedSummary] = useState<LoadedSummary>();
  const [summaryFailure, setSummaryFailure] = useState<SummaryFailure>();
  const [summaryLoadingKey, setSummaryLoadingKey] = useState<string>();
  const [summaryReload, setSummaryReload] = useState(0);
  const [loadedRows, setLoadedRows] = useState<LoadedRows>();
  const [rowsFailure, setRowsFailure] = useState<RowsFailure>();
  const [rowsLoadingKey, setRowsLoadingKey] = useState<string>();
  const [rowsReload, setRowsReload] = useState(0);
  const [expansion, setExpansion] = useState<PublishedDateExpansion>();
  const [expansionReload, setExpansionReload] = useState(0);
  const [rangeResolution, setRangeResolution] = useState<RangeResolution>({ status: "idle" });
  const [conflictNotice, setConflictNotice] = useState<string>();
  const [dateDraft, setDateDraft] = useState({ from: view.from, to: view.to });
  const [dateError, setDateError] = useState<string>();
  const [searchDraft, setSearchDraft] = useState(view.search);
  const activeSummaryRef = useRef<ActiveRequest | undefined>(undefined);
  const activeRangeRef = useRef<ActiveRequest | undefined>(undefined);
  const activeExpansionRef = useRef<ActiveRequest | undefined>(undefined);
  const activeRowsRef = useRef<ActiveRequest | undefined>(undefined);
  const summaryGenerationRef = useRef(0);
  const rangeGenerationRef = useRef(0);
  const expansionGenerationRef = useRef(0);
  const rowsGenerationRef = useRef(0);
  const desiredSummaryOwnerRef = useRef<string | undefined>(undefined);
  const desiredRangeOwnerRef = useRef<string | undefined>(undefined);
  const desiredExpansionOwnerRef = useRef<string | undefined>(undefined);
  const desiredRowsOwnerRef = useRef<string | undefined>(undefined);
  const scopeTokenRef = useRef<ScopeToken | undefined>(undefined);
  const conflictRetryUsedRef = useRef(false);
  const setSearchParamsRef = useRef(setSearchParams);
  const currentViewRef = useRef(view);
  const currentRawSearchRef = useRef(rawSearch);
  setSearchParamsRef.current = setSearchParams;
  currentViewRef.current = view;
  currentRawSearchRef.current = rawSearch;

  const abortSummary = useCallback(() => {
    summaryGenerationRef.current += 1;
    desiredSummaryOwnerRef.current = undefined;
    activeSummaryRef.current?.controller.abort();
    activeSummaryRef.current = undefined;
    setSummaryLoadingKey(undefined);
  }, []);

  const abortExpansion = useCallback(() => {
    expansionGenerationRef.current += 1;
    desiredExpansionOwnerRef.current = undefined;
    activeExpansionRef.current?.controller.abort();
    activeExpansionRef.current = undefined;
    setExpansion(undefined);
  }, []);

  const abortRows = useCallback(() => {
    rowsGenerationRef.current += 1;
    desiredRowsOwnerRef.current = undefined;
    activeRowsRef.current?.controller.abort();
    activeRowsRef.current = undefined;
    setRowsLoadingKey(undefined);
  }, []);

  const abortRangeResolution = useCallback(() => {
    rangeGenerationRef.current += 1;
    desiredRangeOwnerRef.current = undefined;
    activeRangeRef.current?.controller.abort();
    activeRangeRef.current = undefined;
    setRangeResolution({ status: "idle" });
  }, []);

  const replaceWithAuthoritativeRange = useCallback((
    from: string,
    to: string,
    token: string,
  ): boolean => {
    if (!isValidResolvedRange(from, to)) {
      throw new Error("Invalid resolved published-details range.");
    }
    const current = currentViewRef.current;
    const rangeChanged = current.from !== from || current.to !== to;
    const authoritative = {
      ...current,
      expandedDate: dateWithinRange(current.expandedDate, from, to) ? current.expandedDate : undefined,
      from,
      page: rangeChanged ? 1 : current.page,
      to,
    };
    const canonical = serializePublishedDetailsSearch(authoritative);
    scopeTokenRef.current = { key: scopeKey(authoritative), value: token };
    if (rangeChanged) {
      abortExpansion();
      abortRows();
      setLoadedSummary(undefined);
      setLoadedRows(undefined);
      setSearchParamsRef.current(canonical, { replace: true });
      return false;
    }
    if (canonical.toString() !== currentRawSearchRef.current) {
      setSearchParamsRef.current(canonical, { replace: true });
    }
    return true;
  }, [abortExpansion, abortRows]);

  const handleScopeConflict = useCallback(() => {
    abortSummary();
    abortExpansion();
    abortRows();
    scopeTokenRef.current = undefined;
    setLoadedSummary(undefined);
    setLoadedRows(undefined);
    setExpansion(undefined);
    setSummaryLoadingKey(undefined);
    setConflictNotice(CONFLICT_NOTICE);
    const current = currentViewRef.current;
    const resetView = { ...current, expandedDate: undefined, page: 1 };
    const canonical = serializePublishedDetailsSearch(resetView);

    if (!conflictRetryUsedRef.current) {
      conflictRetryUsedRef.current = true;
      setSummaryFailure(undefined);
      setRowsFailure(undefined);
      const urlChanged = canonical.toString() !== currentRawSearchRef.current;
      if (urlChanged) {
        setSearchParamsRef.current(canonical, { replace: true });
      }
      if (!urlChanged || (current.mode === "summary" && summaryKey(resetView) === summaryKey(current))) {
        if (current.mode === "rows") setRowsReload((value) => value + 1);
        else setSummaryReload((value) => value + 1);
      }
      return;
    }

    const message = "发布数据持续变化，自动重新读取未完成。请手动重新读取。";
    if (resetView.mode === "rows") setRowsFailure({ key: rowsKey(resetView), message });
    else setSummaryFailure({ key: summaryKey(resetView), message });
  }, [abortExpansion, abortRows, abortSummary]);

  const commitView = useCallback((
    updates: Partial<PublishedDetailsViewState>,
    options: { preserveSummaryPage?: boolean; replace?: boolean } = {},
  ) => {
    abortRangeResolution();
    setDateError(undefined);
    const current = currentViewRef.current;
    let next = updatePublishedDetailsViewState(current, updates);
    if (options.preserveSummaryPage && current.mode === "summary" && next.mode === "summary") {
      next = { ...next, page: current.page };
    }
    const contextChanged = (
      next.from !== current.from
      || next.to !== current.to
      || next.reportType !== current.reportType
      || next.search !== current.search
      || next.mode !== current.mode
      || next.page !== current.page
    );
    if (next.mode !== "summary" || next.reportType !== current.reportType || next.from !== current.from || next.to !== current.to || next.page !== current.page) {
      next = { ...next, expandedDate: undefined };
    }
    if (scopeKey(next) !== scopeKey(current)) scopeTokenRef.current = undefined;
    const nextSummaryOwner = next.mode === "summary" ? summaryKey(next) : undefined;
    if (desiredSummaryOwnerRef.current !== nextSummaryOwner) abortSummary();
    const nextRowsOwner = next.mode === "rows" ? rowsKey(next) : undefined;
    if (desiredRowsOwnerRef.current !== nextRowsOwner) abortRows();
    const currentExpansionOwner = current.mode === "summary" && current.expandedDate
      ? expansionKey(current, current.expandedDate)
      : undefined;
    const nextExpansionOwner = next.mode === "summary" && next.expandedDate
      ? expansionKey(next, next.expandedDate)
      : undefined;
    if (contextChanged || currentExpansionOwner !== nextExpansionOwner) abortExpansion();
    setSearchParams(serializePublishedDetailsSearch(next), options.replace ? { replace: true } : undefined);
  }, [abortExpansion, abortRangeResolution, abortRows, abortSummary, setSearchParams]);

  useEffect(() => {
    setDateDraft({ from: view.from, to: view.to });
  }, [view.from, view.to]);

  useEffect(() => {
    setSearchDraft(view.search);
  }, [view.search]);

  const rangeBlocksSummary = (
    (rangeResolution.status === "loading" || rangeResolution.status === "empty")
    && rangeResolution.ownerKey === currentRangeOwnerKey
  );
  const desiredSummaryOwner = view.mode === "summary" && !rangeBlocksSummary
    ? currentSummaryKey
    : undefined;
  desiredSummaryOwnerRef.current = desiredSummaryOwner;
  const currentRowsKey = rowsKey(view);
  const desiredRowsOwner = view.mode === "rows" && !rangeBlocksSummary
    ? currentRowsKey
    : undefined;
  desiredRowsOwnerRef.current = desiredRowsOwner;
  const renderedRangeOwner = rangeResolution.status === "loading"
    && rangeResolution.ownerKey === currentRangeOwnerKey
    ? currentRangeOwnerKey
    : undefined;
  desiredRangeOwnerRef.current = renderedRangeOwner;

  useEffect(() => {
    if (rangeResolution.status !== "loading" || rangeResolution.ownerKey === currentRangeOwnerKey) return;
    abortRangeResolution();
  }, [abortRangeResolution, currentRangeOwnerKey, rangeResolution]);

  useEffect(() => {
    const sourceView = currentViewRef.current;
    if (sourceView.mode !== "summary" || rangeBlocksSummary) {
      abortSummary();
      return;
    }

    activeSummaryRef.current?.controller.abort();
    const controller = new AbortController();
    const requestKey = currentSummaryKey;
    const generation = summaryGenerationRef.current + 1;
    summaryGenerationRef.current = generation;
    desiredSummaryOwnerRef.current = requestKey;
    activeSummaryRef.current = { controller, generation, key: requestKey };
    const requestIsCurrent = () => {
      const current = currentViewRef.current;
      return !controller.signal.aborted
        && summaryGenerationRef.current === generation
        && activeSummaryRef.current?.generation === generation
        && activeSummaryRef.current.key === requestKey
        && desiredSummaryOwnerRef.current === requestKey
        && current.mode === "summary"
        && summaryKey(current) === requestKey;
    };
    setLoadedSummary(undefined);
    setSummaryFailure(undefined);
    setSummaryLoadingKey(requestKey);
    const token = scopeTokenRef.current?.key === currentScopeKey
      ? scopeTokenRef.current.value
      : undefined;

    void loadPublishedSummaries({
      from: sourceView.from,
      page: sourceView.page,
      pageSize: 25,
      reportType: sourceView.reportType,
      scopeToken: token,
      search: sourceView.search || undefined,
      to: sourceView.to,
    }, controller.signal).then((response) => {
      if (!requestIsCurrent()) return;
      if (!Array.isArray(response.summaries) || !response.scope_token) {
        throw new Error("Invalid published summary response.");
      }
      const accepted = replaceWithAuthoritativeRange(
        response.range.from_date,
        response.range.to_date,
        response.scope_token,
      );
      if (!accepted) return;
      setLoadedSummary({ key: requestKey, response });
      setSummaryFailure(undefined);
      setConflictNotice(undefined);
      conflictRetryUsedRef.current = false;
    }).catch((error: unknown) => {
      if (!requestIsCurrent()) return;
      if (isPublicationScopeChangedError(error)) {
        handleScopeConflict();
        return;
      }
      setSummaryFailure({ key: requestKey, message: safeSummaryError(error) });
    }).finally(() => {
      if (requestIsCurrent()) {
        activeSummaryRef.current = undefined;
        setSummaryLoadingKey((current) => current === requestKey ? undefined : current);
      }
    });

    return () => {
      controller.abort();
      if (activeSummaryRef.current?.generation === generation) activeSummaryRef.current = undefined;
    };
  }, [
    abortSummary,
    currentScopeKey,
    currentSummaryKey,
    handleScopeConflict,
    rangeBlocksSummary,
    replaceWithAuthoritativeRange,
    summaryReload,
    view.mode,
  ]);

  useEffect(() => {
    const sourceView = currentViewRef.current;
    if (sourceView.mode !== "rows" || rangeBlocksSummary) {
      abortRows();
      return;
    }

    activeRowsRef.current?.controller.abort();
    const controller = new AbortController();
    const requestKey = currentRowsKey;
    const generation = rowsGenerationRef.current + 1;
    rowsGenerationRef.current = generation;
    desiredRowsOwnerRef.current = requestKey;
    activeRowsRef.current = { controller, generation, key: requestKey };
    const requestIsCurrent = () => {
      const current = currentViewRef.current;
      return !controller.signal.aborted
        && rowsGenerationRef.current === generation
        && activeRowsRef.current?.generation === generation
        && activeRowsRef.current.key === requestKey
        && desiredRowsOwnerRef.current === requestKey
        && current.mode === "rows"
        && rowsKey(current) === requestKey;
    };
    setLoadedRows(undefined);
    setRowsFailure(undefined);
    setRowsLoadingKey(requestKey);
    const token = scopeTokenRef.current?.key === currentScopeKey
      ? scopeTokenRef.current.value
      : undefined;

    void loadPublishedRows({
      direction: sourceView.direction,
      from: sourceView.from,
      page: sourceView.page,
      pageSize: 25,
      reportType: sourceView.reportType,
      scopeToken: token,
      search: sourceView.search || undefined,
      sortColumnId: sourceView.sortColumnId,
      to: sourceView.to,
    }, controller.signal).then((response) => {
      if (!requestIsCurrent()) return;
      if (!Array.isArray(response.rows) || !Array.isArray(response.columns) || !response.scope_token) {
        throw new Error("Invalid published rows response.");
      }
      const accepted = replaceWithAuthoritativeRange(
        response.range.from_date,
        response.range.to_date,
        response.scope_token,
      );
      if (!accepted) return;
      setLoadedRows({ key: requestKey, response });
      setRowsFailure(undefined);
      setConflictNotice(undefined);
      conflictRetryUsedRef.current = false;
    }).catch((error: unknown) => {
      if (!requestIsCurrent()) return;
      if (isPublicationScopeChangedError(error)) {
        handleScopeConflict();
        return;
      }
      setRowsFailure({ key: requestKey, message: safeSummaryError(error) });
    }).finally(() => {
      if (requestIsCurrent()) {
        activeRowsRef.current = undefined;
        setRowsLoadingKey((current) => current === requestKey ? undefined : current);
      }
    });

    return () => {
      controller.abort();
      if (activeRowsRef.current?.generation === generation) activeRowsRef.current = undefined;
    };
  }, [
    abortRows,
    currentRowsKey,
    currentScopeKey,
    handleScopeConflict,
    rangeBlocksSummary,
    replaceWithAuthoritativeRange,
    rowsReload,
    view.mode,
  ]);

  const expandedReportDate = view.mode === "summary" ? view.expandedDate : undefined;
  const acceptedSummary = loadedSummary?.key === currentSummaryKey ? loadedSummary.response : undefined;
  const currentExpansionKey = expandedReportDate ? expansionKey(view, expandedReportDate) : "";
  const desiredExpansionOwner = expandedReportDate && acceptedSummary
    ? currentExpansionKey
    : undefined;
  desiredExpansionOwnerRef.current = desiredExpansionOwner;

  useEffect(() => {
    const sourceView = currentViewRef.current;
    if (!expandedReportDate || !acceptedSummary) {
      activeExpansionRef.current?.controller.abort();
      activeExpansionRef.current = undefined;
      if (!expandedReportDate) setExpansion(undefined);
      return;
    }
    const token = scopeTokenRef.current?.key === currentScopeKey
      ? scopeTokenRef.current.value
      : undefined;
    if (!token) return;

    const requestKey = currentExpansionKey;
    if (
      activeExpansionRef.current?.key === requestKey
      && activeExpansionRef.current.generation === expansionGenerationRef.current
      && desiredExpansionOwnerRef.current === requestKey
    ) return;
    activeExpansionRef.current?.controller.abort();
    const controller = new AbortController();
    const generation = expansionGenerationRef.current + 1;
    expansionGenerationRef.current = generation;
    desiredExpansionOwnerRef.current = requestKey;
    activeExpansionRef.current = { controller, generation, key: requestKey };
    const requestIsCurrent = () => {
      const current = currentViewRef.current;
      return !controller.signal.aborted
        && expansionGenerationRef.current === generation
        && activeExpansionRef.current?.generation === generation
        && activeExpansionRef.current.key === requestKey
        && desiredExpansionOwnerRef.current === requestKey
        && current.mode === "summary"
        && current.expandedDate === expandedReportDate
        && expansionKey(current, expandedReportDate) === requestKey;
    };
    setExpansion({ date: expandedReportDate, status: "loading" });
    void loadPublishedRows({
      direction: sourceView.direction,
      from: sourceView.from,
      page: 1,
      pageSize: 25,
      reportDate: expandedReportDate,
      reportType: sourceView.reportType,
      scopeToken: token,
      search: sourceView.search || undefined,
      sortColumnId: sourceView.sortColumnId,
      to: sourceView.to,
    }, controller.signal).then((response: PublishedRowsResponse) => {
      if (!requestIsCurrent()) return;
      if (!Array.isArray(response.rows) || !Array.isArray(response.columns) || !response.scope_token) {
        throw new Error("Invalid published rows response.");
      }
      const accepted = replaceWithAuthoritativeRange(
        response.range.from_date,
        response.range.to_date,
        response.scope_token,
      );
      if (!accepted) return;
      setExpansion({ date: expandedReportDate, response, status: "ready" });
      setConflictNotice(undefined);
      conflictRetryUsedRef.current = false;
    }).catch((error: unknown) => {
      if (!requestIsCurrent()) return;
      if (isPublicationScopeChangedError(error)) {
        handleScopeConflict();
        return;
      }
      setExpansion({
        date: expandedReportDate,
        message: "无法读取该日期的展开明细，请重试。",
        status: "error",
      });
    }).finally(() => {
      if (requestIsCurrent()) activeExpansionRef.current = undefined;
    });

    return undefined;
  }, [
    acceptedSummary,
    currentExpansionKey,
    currentScopeKey,
    expandedReportDate,
    expansionReload,
    handleScopeConflict,
    replaceWithAuthoritativeRange,
  ]);

  useEffect(() => () => {
    summaryGenerationRef.current += 1;
    rangeGenerationRef.current += 1;
    expansionGenerationRef.current += 1;
    rowsGenerationRef.current += 1;
    desiredSummaryOwnerRef.current = undefined;
    desiredRangeOwnerRef.current = undefined;
    desiredExpansionOwnerRef.current = undefined;
    desiredRowsOwnerRef.current = undefined;
    activeSummaryRef.current?.controller.abort();
    activeRangeRef.current?.controller.abort();
    activeExpansionRef.current?.controller.abort();
    activeRowsRef.current?.controller.abort();
    activeSummaryRef.current = undefined;
    activeRangeRef.current = undefined;
    activeExpansionRef.current = undefined;
    activeRowsRef.current = undefined;
  }, []);

  const resolveAllPublished = useCallback(() => {
    abortSummary();
    abortExpansion();
    abortRows();
    abortRangeResolution();
    scopeTokenRef.current = undefined;
    setLoadedSummary(undefined);
    setLoadedRows(undefined);
    setRowsFailure(undefined);
    setSummaryFailure(undefined);
    setConflictNotice(undefined);
    const source = currentViewRef.current;
    const ownerKey = rangeOwnerKey(source, currentRawSearchRef.current);
    const controller = new AbortController();
    const generation = rangeGenerationRef.current + 1;
    rangeGenerationRef.current = generation;
    desiredRangeOwnerRef.current = ownerKey;
    activeRangeRef.current = { controller, generation, key: ownerKey };
    const requestIsCurrent = () => {
      const current = currentViewRef.current;
      return !controller.signal.aborted
        && rangeGenerationRef.current === generation
        && activeRangeRef.current?.generation === generation
        && activeRangeRef.current.key === ownerKey
        && desiredRangeOwnerRef.current === ownerKey
        && rangeOwnerKey(current, currentRawSearchRef.current) === ownerKey;
    };
    setRangeResolution({ ownerKey, status: "loading" });
    void loadPublishedRange(source.reportType, controller.signal).then((response) => {
      if (!requestIsCurrent()) return;
      if (response.from_date === null && response.to_date === null) {
        setRangeResolution({ ownerKey, status: "empty" });
        return;
      }
      if (!response.from_date || !response.to_date || !isValidResolvedRange(response.from_date, response.to_date)) {
        throw new Error("Invalid all-published range response.");
      }
      if (!requestIsCurrent()) return;
      const current = currentViewRef.current;
      setRangeResolution({ status: "idle" });
      const next = updatePublishedDetailsViewState(current, {
        expandedDate: dateWithinRange(current.expandedDate, response.from_date, response.to_date)
          ? current.expandedDate
          : undefined,
        from: response.from_date,
        page: 1,
        to: response.to_date,
      });
      setSearchParamsRef.current(serializePublishedDetailsSearch(next), { replace: true });
    }).catch(() => {
      if (!requestIsCurrent()) return;
      setRangeResolution({
        message: "无法解析全部已发布日期范围，请重试。",
        ownerKey,
        status: "error",
      });
    }).finally(() => {
      if (requestIsCurrent()) activeRangeRef.current = undefined;
    });
  }, [abortExpansion, abortRangeResolution, abortRows, abortSummary]);

  const toggleExpanded = (reportDate: string) => {
    abortExpansion();
    const current = currentViewRef.current;
    const expandedDate = current.expandedDate === reportDate ? undefined : reportDate;
    setSearchParams(serializePublishedDetailsSearch({ ...current, expandedDate }));
  };

  const retryExpansion = (reportDate: string) => {
    if (currentViewRef.current.expandedDate !== reportDate) return;
    abortExpansion();
    setExpansionReload((value) => value + 1);
  };

  const retrySummaries = () => {
    abortSummary();
    conflictRetryUsedRef.current = false;
    setConflictNotice(undefined);
    setSummaryFailure(undefined);
    setSummaryReload((value) => value + 1);
  };

  const retryRows = () => {
    abortRows();
    conflictRetryUsedRef.current = false;
    setConflictNotice(undefined);
    setRowsFailure(undefined);
    setRowsReload((value) => value + 1);
  };

  const applyDateRange = (event: React.FormEvent) => {
    event.preventDefault();
    if (!isValidResolvedRange(dateDraft.from, dateDraft.to)) {
      setDateError("请选择有效的开始和结束日期，且开始日期不能晚于结束日期。");
      return;
    }
    commitView({ expandedDate: undefined, from: dateDraft.from, page: 1, to: dateDraft.to });
  };

  const applySearch = (event: React.FormEvent) => {
    event.preventDefault();
    commitView({ page: 1, search: searchDraft.slice(0, 200) });
  };

  const activeResponse = loadedSummary?.key === currentSummaryKey ? loadedSummary.response : undefined;
  const activeError = summaryFailure?.key === currentSummaryKey ? summaryFailure.message : undefined;
  const activeRowsResponse = loadedRows?.key === currentRowsKey ? loadedRows.response : undefined;
  const activeRowsError = rowsFailure?.key === currentRowsKey ? rowsFailure.message : undefined;
  const rangeLabel = (view.mode === "rows" ? activeRowsResponse?.range : activeResponse?.range)
    ?? { from_date: view.from, to_date: view.to };
  const gridSort: DataTableSort = view.sortColumnId
    ? { columnId: view.sortColumnId, direction: view.direction }
    : null;
  const applyAllRowsGridSort = (command: SortCommand) => {
    commitView({
      direction: command.direction ?? "asc",
      page: 1,
      sortColumnId: command.direction ? command.columnId : undefined,
    });
  };
  const applyExpandedGridSort = (command: SortCommand) => {
    commitView({
      direction: command.direction ?? "asc",
      sortColumnId: command.direction ? command.columnId : undefined,
    }, { preserveSummaryPage: true });
  };
  const exportQuery = {
    direction: view.direction,
    from: view.from,
    reportType: view.reportType,
    search: view.search || undefined,
    sortColumnId: view.sortColumnId,
    to: view.to,
  };
  const exportReason = activeResponse?.permissions.can_export === false
    ? "当前账号无导出权限；列设置将在全部明细列结构加载后可用。"
    : "列设置与导出将在全部明细列结构加载后可用。";
  const ownerMatches = "ownerKey" in rangeResolution && rangeResolution.ownerKey === currentRangeOwnerKey;

  return <PublishedDetailLedgerView siteId={siteId} displayName={principal.display_name} reportingTimezone={reportingTimezone}
    reportType={view.reportType} mode={view.mode} range={rangeLabel} dateDraft={dateDraft} dateError={dateError}
    searchDraft={searchDraft} resolvingRange={rangeResolution.status === "loading" && ownerMatches}
    stagedReason={view.mode === "summary" && !expandedReportDate ? exportReason : undefined} conflictNotice={conflictNotice}
    count={view.mode === "rows" ? activeRowsResponse?.pagination.total_items : activeResponse?.pagination.total_items}
    onDateDraft={setDateDraft} onApplyDates={applyDateRange} onSearchDraft={setSearchDraft} onSearch={applySearch}
    onReportType={reportType => commitView({ expandedDate: undefined, reportType })}
    onMode={mode => commitView(mode === "rows" ? { expandedDate: undefined, mode } : { mode })}
    onQuickRange={value => value === "all" ? resolveAllPublished() : commitView(value === "month" ? { expandedDate: undefined, from: `${today.slice(0, 7)}-01`, to: today } : { ...rollingRange(today, value), expandedDate: undefined })}
    rangeError={rangeResolution.status === "error" && ownerMatches ? <ErrorState title="已发布范围读取失败" description={rangeResolution.message} action={<Button onClick={resolveAllPublished}>重试全部已发布范围</Button>} /> : undefined}>
      {rangeResolution.status === "loading" && ownerMatches ? <div aria-label="正在解析全部已发布范围" className={styles["published-ledger__range-state"]} role="status">正在解析全部已发布范围…</div>
        : rangeResolution.status === "empty" && ownerMatches ? <EmptyState title="当前报表类型还没有任何已发布明细。" description="筛选工具仍可使用；可切换报表类型或指定日期范围。" />
          : view.mode === "rows" ? <ReadonlyPublishedDataGrid
        error={activeRowsError}
        exportQuery={exportQuery}
        loading={rowsLoadingKey === currentRowsKey}
        onPageChange={(page) => commitView({ page })}
        onRetry={retryRows}
        onSort={applyAllRowsGridSort}
        response={activeRowsResponse}
        siteId={siteId}
        sort={gridSort}
        userId={principal.id}
      /> : <PublishedDateSummaries
            error={activeError}
            expandedDate={expandedReportDate}
            expansion={expansion}
            loading={summaryLoadingKey === currentSummaryKey}
            onPageChange={(page) => commitView({ expandedDate: undefined, page })}
            onRetry={retrySummaries}
            onRetryExpansion={retryExpansion}
            onToggleExpanded={toggleExpanded}
            reportType={view.reportType}
            reportingTimezone={reportingTimezone}
            renderExpandedRows={(response) => <ReadonlyPublishedDataGrid
              exportQuery={{ ...exportQuery, reportDate: expandedReportDate }}
              label={`${expandedReportDate} 已发布原始明细`}
              loading={false}
              onPageChange={() => undefined}
              onRetry={() => retryExpansion(expandedReportDate!)}
              onSort={applyExpandedGridSort}
              pagination={false}
              response={response}
              siteId={siteId}
              sort={gridSort}
              userId={principal.id}
            />}
            response={activeResponse}
          />}
  </PublishedDetailLedgerView>;
}

export default PublishedDetailLedgerPage;
