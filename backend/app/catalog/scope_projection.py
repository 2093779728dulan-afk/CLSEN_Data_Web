"""Current shop display names projected from existing immutable audit evidence."""

SCOPES_WITH_DISPLAY_NAMES = """(
SELECT s.id, s.site_id, s.seller_account_scope_key,
               COALESCE(
                        JSON_UNQUOTE(JSON_EXTRACT(
                            n.safe_payload_json, '$.new_display_name')),
                        c.seller_account_display_name, s.seller_account_display_name)
                   AS seller_account_display_name,
               s.marketplace_scope_code, s.confirmed_by_user_id,
               s.confirmed_at, s.created_at, COALESCE(n.id, 0) AS display_name_revision
        FROM report_source_scopes s
        LEFT JOIN report_source_scope_corrections c
          ON c.site_id=s.site_id AND c.report_source_scope_id=s.id
        LEFT JOIN catalog_audit_events n ON n.id=(
            SELECT MAX(a.id) FROM catalog_audit_events a
            WHERE a.site_id=s.site_id AND a.resource_kind='report_source_scope'
              AND a.resource_id=s.id AND a.event_kind='catalog.source_scope_renamed'
        )
)"""
