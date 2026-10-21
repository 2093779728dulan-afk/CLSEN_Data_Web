import { ChevronLeft, ChevronRight } from "lucide-react";

import { Button } from "./Button";
import styles from "./Pagination.module.css";

export type PaginationProps = {
  itemLabel?: string;
  loading?: boolean;
  onPageChange: (page: number) => void;
  page: number;
  totalItems: number;
  totalPages: number;
};

export function Pagination({
  itemLabel = "条记录",
  loading = false,
  onPageChange,
  page,
  totalItems,
  totalPages,
}: PaginationProps) {
  const pageCount = Math.max(totalPages, 1);

  return (
    <nav aria-label="分页" className={styles.pagination}>
      <p aria-live="polite" className={styles.summary}>
        共 {totalItems.toLocaleString("zh-CN")} 个{itemLabel}
      </p>
      <div className={styles.actions}>
        <Button disabled={loading || page <= 1} icon={<ChevronLeft />} onClick={() => onPageChange(page - 1)} variant="quiet">上一页</Button>
        <span aria-atomic="true" aria-current="page" aria-label={`第 ${page} / ${pageCount} 页`} aria-live="polite" className={styles.position}>{page}<span aria-hidden="true"> / {pageCount}</span></span>
        <Button disabled={loading || page >= pageCount} onClick={() => onPageChange(page + 1)} variant="quiet"><span className={styles.next}>下一页<ChevronRight aria-hidden="true" /></span></Button>
      </div>
    </nav>
  );
}
