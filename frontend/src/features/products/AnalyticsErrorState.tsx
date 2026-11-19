import { LinkButton, Button, ErrorState  } from "../../design-system";
import type { AnalyticsFailure } from "./analyticsError";

export function AnalyticsErrorState({ title, failure, onRetry }: { title: string; failure: AnalyticsFailure; onRetry: () => void }) {
  return <ErrorState title={failure.setup ? "商品分析尚未就绪" : title} description={failure.message} action={failure.setup ? <LinkButton to="/catalog">查看初始化与处理步骤</LinkButton> : failure.retry ? <Button onClick={onRetry}>按原条件重试</Button> : undefined} />;
}
