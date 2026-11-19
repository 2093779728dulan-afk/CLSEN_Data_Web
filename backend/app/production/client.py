"""Explicit internal transport with no automatic write retries."""

from __future__ import annotations

import base64

import httpx2

from app.api.errors import ApiError
from app.config import Settings
from app.site_context import CurrentSiteContext


def production_request(
    settings: Settings,
    context: CurrentSiteContext,
    method: str,
    path: str,
    *,
    body: dict[str, object] | None = None,
    query: list[tuple[str, str]] | None = None,
    operation_key: str | None = None,
    binary: bool = False,
) -> object:
    if not settings.production_service_url:
        raise ApiError(503, "production_disabled", "生产跟踪尚未启用。")
    headers = {
        "Authorization": f"Bearer {settings.production_service_token}",
        "X-Production-Site": str(context.site_id),
        "X-Production-Actor": str(context.principal_user_id),
        "X-Production-Roles": ",".join(sorted(context.principal_roles)),
    }
    if operation_key:
        headers["Idempotency-Key"] = operation_key
    if body and isinstance(body.get("_actor_name"), str):
        headers["X-Production-Actor-Name"] = base64.urlsafe_b64encode(
            str(body["_actor_name"]).encode("utf-8")
        ).decode("ascii")
    try:
        with httpx2.Client(
            timeout=httpx2.Timeout(15, connect=3), trust_env=False
        ) as client:
            response = client.request(
                method,
                f"{settings.production_service_url.rstrip('/')}/internal/production/{path}",
                headers=headers,
                json=body,
                params=tuple(query) if query is not None else None,
            )
        if binary and response.is_success:
            return response.content
        payload = response.json()
    except (httpx2.HTTPError, ValueError) as error:
        raise ApiError(
            503,
            "production_result_unknown",
            "生产服务暂不可用。若已提交, 请查询原操作结果, 不要重新创建单据。",
        ) from error
    if response.is_error:
        detail = payload.get("error", {}) if isinstance(payload, dict) else {}
        code, message = detail.get("code"), detail.get("message")
        if not isinstance(code, str) or not isinstance(message, str):
            raise ApiError(
                503, "production_invalid_response", "生产服务返回了无法识别的结果。"
            )
        raise ApiError(response.status_code, code, message)
    return payload
