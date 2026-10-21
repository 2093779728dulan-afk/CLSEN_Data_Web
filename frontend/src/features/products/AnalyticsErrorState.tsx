import { Link } from "react-router-dom";
import { Button, ErrorState } from "../../design-system";
import type { AnalyticsFailure } from "./analyticsError";

export function AnalyticsErrorState({ title, failure, onRetry }: { title: string; failure: AnalyticsFailure; onRetry: () => void }) {
  return <ErrorState title={failure.setup ? "商品分析尚未就绪" : title} description={failure.message} action={failure.setup ? <Link to="/catalog">查看初始化与处理步骤</Link> : failure.retry ? <Button onClick={onRetry}>按原条件重试</Button> : undefined} />;
}
