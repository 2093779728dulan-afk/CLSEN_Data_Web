import { Link } from "react-router-dom";
import { Button } from "../../design-system";
import { CatalogSetup } from "./CatalogSetup";
import { catalogReadError } from "./catalogReadError";

export function CatalogReadError({ failure, onRetry }: { failure: ReturnType<typeof catalogReadError>; onRetry: () => void }) {
  return <div className="catalog-stack">
    <section className="catalog-panel">
      <h2>{failure.setup ? "待处理清单尚未就绪" : "商品主档读取未完成"}</h2>
      <p role="alert">{failure.message}</p>
      {failure.setup ? <Link to="/catalog/maintenance">前往批量维护，完成初始化</Link> : failure.retry ? <Button onClick={onRetry}>重新读取</Button> : <Link to="/catalog">返回商品主档</Link>}
    </section>
    {failure.setup && <CatalogSetup />}
  </div>;
}
