/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, useState, type ReactNode } from "react";

export type CatalogListState = { query: string; sort: string; page: number; view: "cards" | "table" };
const initialList: CatalogListState = { query: "", sort: "code", page: 1, view: "cards" };
const CatalogNavigationContext = createContext<{
  list: CatalogListState;
  setList: (value: CatalogListState) => void;
  styleReturn: string;
  setStyleReturn: (value: string) => void;
  reviewReturn: string;
  setReviewReturn: (value: string) => void;
} | undefined>(undefined);

// The application keys this provider by principal, roles and site configuration.
// Never persist source data or navigation state across authorization boundaries.
export function CatalogNavigationProvider({ children }: { children: ReactNode }) {
  const [list, setList] = useState(initialList);
  const [styleReturn, setStyleReturn] = useState("/catalog");
  const [reviewReturn, setReviewReturn] = useState("/catalog/maintenance");
  return <CatalogNavigationContext.Provider value={{ list, setList, styleReturn, setStyleReturn, reviewReturn, setReviewReturn }}>{children}</CatalogNavigationContext.Provider>;
}

export function useCatalogNavigation() {
  const shared = useContext(CatalogNavigationContext);
  const [list, setList] = useState(initialList);
  const [styleReturn, setStyleReturn] = useState("/catalog");
  const [reviewReturn, setReviewReturn] = useState("/catalog/maintenance");
  return shared ?? { list, setList, styleReturn, setStyleReturn, reviewReturn, setReviewReturn };
}
