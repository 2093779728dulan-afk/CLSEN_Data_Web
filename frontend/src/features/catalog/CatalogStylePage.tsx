import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { getCatalogStyle, getCatalogStylePendingItems, type CatalogPendingItem } from "./catalogApi";
import type { CatalogNameSuggestion } from "./catalogTypes";
import { catalogReadError } from "./catalogReadError";
import { CatalogCategoryEditor } from "./CatalogCategoryEditor";
import { CatalogChangeReview } from "./CatalogChangeReview";
import { CatalogPendingItems } from "./CatalogPendingItems";
import { useCatalogNavigation } from "./CatalogNavigationContext";
import { CatalogStyleView, type CatalogStyleDetail } from "./CatalogStyleView";

function CatalogStyleResource({ styleId }: { styleId: number }) {
  const { styleReturn } = useCatalogNavigation();
  const [search] = useSearchParams();
  const returnTo = search.get("return_to");
  const scopeId = Number(search.get("scope")) || undefined;
  const restoredDraftId = Number(search.get("change_draft")) || undefined;
  const [nameSuggestion, setNameSuggestion] = useState<CatalogNameSuggestion>();
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
      const [style, pendingItems] = await Promise.all([getCatalogStyle(styleId, scopeId), getCatalogStylePendingItems(styleId)]);
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
  }, [styleId, scopeId]);
  useEffect(() => {
    mounted.current = true;
    void refresh().catch(() => undefined); // The resource owns the visible error state.
    return () => { mounted.current = false; };
  }, [refresh]);
  return <CatalogStyleView onNameSuggestion={setNameSuggestion} value={value} failure={error} reading={reading} styleReturn={returnTo?.startsWith("/catalog/") ? returnTo : scopeId ? `/catalog?scope=${scopeId}` : styleReturn} onRefresh={() => void refresh().catch(() => undefined)}
    pending={pending && !error && <CatalogPendingItems canReview={pending.permissions.can_review} items={pending.items} />}
    actions={value && (value.permissions?.can_edit || value.permissions?.can_manage_categories) && <>{value.permissions.can_edit && <CatalogChangeReview nameSuggestion={nameSuggestion} restoredDraftId={restoredDraftId} catalogPublicationRevision={value.catalog_publication_revision ?? 0} onApproved={refresh} style={value.style} />}{value.permissions.can_manage_categories && <CatalogCategoryEditor />}</>} />;
}

export function CatalogStylePage() {
  const styleId = Number(useParams().style_id);
  // Route identity owns the resource, preventing an old response from appearing on another style.
  return <CatalogStyleResource key={styleId} styleId={styleId} />;
}
