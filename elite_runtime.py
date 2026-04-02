from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RuntimeSettings:
    api_host: str
    api_port: int
    log_level: str
    default_output_root: Path
    default_history_db: Path
    default_innovation_db: Path
    acceptance_sync_ttl_sec: int
    enable_audit_log: bool
    audit_log_path: Path
    metrics_window_size: int
    enable_api_key_auth: bool
    api_keys_json: str
    auth_header_name: str
    rate_limit_rpm: int
    enforce_tenant_header: bool
    tenant_header_name: str
    allowed_tenants_csv: str
    alert_webhook_url: str
    alert_webhook_map_json: str
    alert_provider: str
    alert_dingtalk_secret: str
    alert_timeout_sec: int
    alert_min_level: str
    alert_cooldown_sec: int
    alert_retry_count: int
    alert_retry_backoff_ms: int
    alert_dead_letter_path: Path
    alert_dead_letter_max_mb: int
    alert_dead_letter_backups: int
    enable_security_headers: bool
    audit_rotate_max_mb: int
    audit_rotate_backups: int
    metrics_max_path_entries: int
    ops_summary_cache_ttl_sec: int
    batch_images_root: Path | None


def _get_env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def _get_env_int(name: str, default: int, min_value: int, max_value: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except Exception:  # noqa: BLE001
        return default
    return max(min_value, min(max_value, value))


def load_runtime_settings(root_dir: Path) -> RuntimeSettings:
    host = os.getenv("ELITE_API_HOST", "0.0.0.0").strip() or "0.0.0.0"
    port = _get_env_int("ELITE_API_PORT", default=8877, min_value=1, max_value=65535)
    log_level = (os.getenv("ELITE_LOG_LEVEL", "info").strip() or "info").lower()
    output_root = Path(os.getenv("ELITE_OUTPUT_ROOT", str(root_dir / "service_runs")))
    history_db = Path(os.getenv("ELITE_HISTORY_DB", str(root_dir / "quality_history.sqlite")))
    innovation_db = Path(os.getenv("ELITE_INNOVATION_DB", str(root_dir / "innovation_state.sqlite")))
    sync_ttl = _get_env_int("ELITE_ACCEPTANCE_SYNC_TTL_SEC", default=20, min_value=0, max_value=3600)
    enable_audit_log = _get_env_bool("ELITE_ENABLE_AUDIT_LOG", default=True)
    audit_log_path = Path(os.getenv("ELITE_AUDIT_LOG_PATH", str(root_dir / "logs" / "elite_audit.jsonl")))
    metrics_window_size = _get_env_int("ELITE_METRICS_WINDOW_SIZE", default=4000, min_value=200, max_value=20000)
    enable_api_key_auth = _get_env_bool("ELITE_ENABLE_API_KEY_AUTH", default=False)
    api_keys_json = os.getenv("ELITE_API_KEYS_JSON", "").strip()
    auth_header_name = os.getenv("ELITE_AUTH_HEADER_NAME", "x-api-key").strip() or "x-api-key"
    rate_limit_rpm = _get_env_int("ELITE_RATE_LIMIT_RPM", default=0, min_value=0, max_value=20000)
    enforce_tenant_header = _get_env_bool("ELITE_ENFORCE_TENANT_HEADER", default=False)
    tenant_header_name = os.getenv("ELITE_TENANT_HEADER_NAME", "x-tenant-id").strip() or "x-tenant-id"
    allowed_tenants_csv = os.getenv("ELITE_ALLOWED_TENANTS", "").strip()
    alert_webhook_url = os.getenv("ELITE_ALERT_WEBHOOK_URL", "").strip()
    alert_webhook_map_json = os.getenv("ELITE_ALERT_WEBHOOK_MAP_JSON", "").strip()
    alert_provider = (os.getenv("ELITE_ALERT_PROVIDER", "webhook").strip() or "webhook").lower()
    alert_dingtalk_secret = os.getenv("ELITE_ALERT_DINGTALK_SECRET", "").strip()
    alert_timeout_sec = _get_env_int("ELITE_ALERT_TIMEOUT_SEC", default=4, min_value=1, max_value=30)
    alert_min_level = (os.getenv("ELITE_ALERT_MIN_LEVEL", "error").strip() or "error").lower()
    alert_cooldown_sec = _get_env_int("ELITE_ALERT_COOLDOWN_SEC", default=90, min_value=0, max_value=3600)
    alert_retry_count = _get_env_int("ELITE_ALERT_RETRY_COUNT", default=2, min_value=0, max_value=10)
    alert_retry_backoff_ms = _get_env_int("ELITE_ALERT_RETRY_BACKOFF_MS", default=500, min_value=0, max_value=60000)
    alert_dead_letter_path = Path(
        os.getenv("ELITE_ALERT_DEAD_LETTER_PATH", str(root_dir / "logs" / "elite_alert_dead_letter.jsonl"))
    )
    alert_dead_letter_max_mb = _get_env_int("ELITE_ALERT_DEAD_LETTER_MAX_MB", default=20, min_value=0, max_value=1024)
    alert_dead_letter_backups = _get_env_int("ELITE_ALERT_DEAD_LETTER_BACKUPS", default=5, min_value=1, max_value=30)
    enable_security_headers = _get_env_bool("ELITE_ENABLE_SECURITY_HEADERS", default=True)
    audit_rotate_max_mb = _get_env_int("ELITE_AUDIT_ROTATE_MAX_MB", default=50, min_value=0, max_value=1024)
    audit_rotate_backups = _get_env_int("ELITE_AUDIT_ROTATE_BACKUPS", default=5, min_value=1, max_value=30)
    metrics_max_path_entries = _get_env_int("ELITE_METRICS_MAX_PATH_ENTRIES", default=3000, min_value=200, max_value=20000)
    ops_summary_cache_ttl_sec = _get_env_int("ELITE_OPS_SUMMARY_CACHE_TTL_SEC", default=15, min_value=0, max_value=300)
    _batch_images_root_raw = os.getenv("ELITE_BATCH_IMAGES_ROOT", "").strip()
    batch_images_root: Path | None = Path(_batch_images_root_raw) if _batch_images_root_raw else None
    return RuntimeSettings(
        api_host=host,
        api_port=port,
        log_level=log_level,
        default_output_root=output_root,
        default_history_db=history_db,
        default_innovation_db=innovation_db,
        acceptance_sync_ttl_sec=sync_ttl,
        enable_audit_log=enable_audit_log,
        audit_log_path=audit_log_path,
        metrics_window_size=metrics_window_size,
        enable_api_key_auth=enable_api_key_auth,
        api_keys_json=api_keys_json,
        auth_header_name=auth_header_name,
        rate_limit_rpm=rate_limit_rpm,
        enforce_tenant_header=enforce_tenant_header,
        tenant_header_name=tenant_header_name,
        allowed_tenants_csv=allowed_tenants_csv,
        alert_webhook_url=alert_webhook_url,
        alert_webhook_map_json=alert_webhook_map_json,
        alert_provider=alert_provider,
        alert_dingtalk_secret=alert_dingtalk_secret,
        alert_timeout_sec=alert_timeout_sec,
        alert_min_level=alert_min_level,
        alert_cooldown_sec=alert_cooldown_sec,
        alert_retry_count=alert_retry_count,
        alert_retry_backoff_ms=alert_retry_backoff_ms,
        alert_dead_letter_path=alert_dead_letter_path,
        alert_dead_letter_max_mb=alert_dead_letter_max_mb,
        alert_dead_letter_backups=alert_dead_letter_backups,
        enable_security_headers=enable_security_headers,
        audit_rotate_max_mb=audit_rotate_max_mb,
        audit_rotate_backups=audit_rotate_backups,
        metrics_max_path_entries=metrics_max_path_entries,
        ops_summary_cache_ttl_sec=ops_summary_cache_ttl_sec,
        batch_images_root=batch_images_root,
    )
