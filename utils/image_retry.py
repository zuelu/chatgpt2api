"""Identify account and upstream failures that another eligible account can resolve."""


def can_retry_with_another_account(error: Exception) -> bool:
    code = str(getattr(error, "code", "") or "").lower()
    text = str(error).lower()
    if any(value in code + " " + text for value in (
        "content_policy", "moderation", "safety", "policy violation",
        "unsupported_image_options", "invalid_image", "invalid_parameter",
    )):
        return False
    if code in {"insufficient_quota", "billing_hard_limit_reached", "invalid_api_key", "model_not_found", "rate_limit_exceeded"}:
        return True
    if any(value in text for value in (
        "quota", "rate limit", "rate_limit", "usage limit", "insufficient credit", "billing",
        "token expired", "invalid token", "unauthorized", "额度", "配额", "too many requests",
    )):
        return True
    if code == "invalid_request_error":
        return False
    status = getattr(error, "status_code", None) or getattr(error, "status", None)
    return status in {401, 403, 408, 409, 429, 500, 502, 503, 504}
