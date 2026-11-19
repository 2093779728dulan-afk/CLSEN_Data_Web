import { Link, useLocation } from "react-router-dom";
import styles from "./Production.module.css";

import { matchesProductionPath, productionSection } from "./productionSections";

export function ProductionNavigation() {
  const { pathname, search } = useLocation();
  const section = productionSection(pathname, search);
  if (!section || section.items.length === 1) return null;
  const score = (paths: readonly string[]) => Math.max(-1, ...paths.filter(path => matchesProductionPath(pathname, path)).map(path => path.length));
  const active = [...section.items].filter(item => score(item.paths) >= 0).sort((a, b) => score(b.paths) - score(a.paths))[0] ?? section.items[pathname.includes("shipments") || new URLSearchParams(search).get("kind") === "packing" ? 1 : 0];
  return <nav className={styles.sectionNavigation} aria-label={`${section.label}功能`}>
    {section.items.map(item => <Link key={item.to} to={item.to} aria-current={active?.to === item.to ? "page" : undefined}>{item.label}</Link>)}
  </nav>;
}
