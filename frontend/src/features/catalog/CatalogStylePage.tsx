import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { getCatalogStyle, getCatalogStylePendingItems, type CatalogPendingItem } from "./catalogApi";
import { catalogReadError } from "./catalogReadError";
import { CatalogCategoryEditor } from "./CatalogCategoryEditor";
import { CatalogChangeReview } from "./CatalogChangeReview";
import { CatalogPendingItems } from "./CatalogPendingItems";
import { useCatalogNavigation } from "./CatalogNavigationContext";
import { CatalogStyleView, type CatalogStyleDetail } from "./CatalogStyleView";

function CatalogStyleResource({ styleId }: { styleId: number }) {
  const { styleReturn } = useCatalogNavigation();
  const [value, setValue] = useState<CatalogStyleDetail>();
  const [pending, setPending] = useState<{ items: CatalogPendingItem[]; permissions: { can_review: boolean } }>();
  const [error, setError] = useState<ReturnType<typeof catalogReadError>>();
  const [reading, setReading] = useState(true);
  const mounted = useRef(false);
  const generation = useRef(0);
  const refresh = useCallback(async () => {
    const request = ++generation.current;
    setReading(true); setError(undefined);
    try {
      const [style, pendingItems] = await Promise.all([getCatalogStyle(styleId), getCatalogStylePendingItems(styleId)]);
      if (!mounted.current || request !== generation.current) return;
      setValue(style); setPending(pendingItems);
    } catch (reason: unknown) {
      if (mounted.current && request === generation.current) {
        const failure = catalogReadError(reason, "商品详情读取未完成，请重试。");
        setError(failure);
        if (!failure.retry) { setValue(undefined); setPending(undefined); }
      }
      throw reason; // The existing approval consumer must still observe a refresh failure.
    } finally { if (mounted.current && request === generation.current) setReading(false); }
  }, [styleId]);
  useEffect(() => {
    mounted.current = true;
    void refresh().catch(() => undefined); // The resource owns the visible error state.
    return () => { mounted.current = false; };
  }, [refresh]);
  return <CatalogStyleView value={value} failure={error} reading={reading} styleReturn={styleReturn} onRefresh={() => void refresh().catch(() => undefined)}
    pending={pending && !error && <CatalogPendingItems canReview={pending.permissions.can_review} items={pending.items} />}
    actions={value && (value.permissions?.can_edit || value.permissions?.can_manage_categories) && <>{value.permissions.can_edit && <CatalogChangeReview catalogPublicationRevision={value.catalog_publication_revision ?? 0} onApproved={refresh} style={value.style} />}{value.permissions.can_manage_categories && <CatalogCategoryEditor />}</>} />;
}

export function CatalogStylePage() {
  const styleId = Number(useParams().style_id);
  // Route identity owns the resource, preventing an old response from appearing on another style.
  return <CatalogStyleResource key={styleId} styleId={styleId} />;
}
