import { createContext, useContext } from "react";

export const ProductionTimezoneContext = createContext("America/Los_Angeles");

export const today = (timeZone = "America/Los_Angeles") => new Intl.DateTimeFormat("en-CA", {
  timeZone, year: "numeric", month: "2-digit", day: "2-digit",
}).format(new Date());

export function useBusinessToday() {
  const timeZone = useContext(ProductionTimezoneContext);
  return () => today(timeZone);
}
