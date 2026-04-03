from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from asyncio import Semaphore as AsyncSemaphore
from threading import RLock
from typing import Any
from uuid import uuid4

import cv2
import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field, model_validator

from elite_color_match import (
    PROFILES,
    ROI,
    analyze_dual_image,
    analyze_single_image,
    build_target_override,
    parse_grid,
    read_image,
    roi_to_quad,
    run_batch_single_mode,
    run_ensemble_single_mode,
    write_html_report,
)
from elite_quality_history import (
    assess_current_vs_history,
    complaint_early_warning,
    executive_kpis,
    history_overview,
    init_db,
    list_outcomes,
    list_recent_runs,
    outcome_kpis,
    recommend_policy_adjustments,
    record_outcome,
    record_run,
)
from elite_decision_center import apply_policy_patch, attach_decision_center, load_decision_policy
from elite_customer_tier import apply_customer_tier_to_policy, load_customer_tier_config
from elite_process_advisor import attach_process_advice
from elite_policy_lab import run_policy_lab
from elite_counterfactual import run_counterfactual_twin
from elite_rollout_engine import champion_challenger_rollout
from elite_open_bandit import recommend_open_bandit_policy
from elite_innovation_engine import DriftPredictor, EliteInnovationEngine
try:
    from color_film_mvp_v3_optimized import ColorFilmPipelineV3Optimized as ColorFilmPipelineV2
except ImportError:  # pragma: no cover - fallback for compatibility
    from color_film_mvp_v2 import ColorFilmPipelineV2

try:
    from ultimate_color_film_system_v2_optimized import (
        UltimateColorFilmSystemV2Optimized as UltimateColorFilmSystem,
    )
except ImportError:  # pragma: no cover - fallback for compatibility
    from ultimate_color_film_system import UltimateColorFilmSystem
from elite_innovation_state import (
    load_color_passport,
    load_standard_versions,
    load_supplier_records,
    next_standard_version,
    record_acceptance_event,
    reload_customer_acceptance_from_db,
    save_standard_version,
    save_supplier_record,
    save_color_passport,
    upsert_acceptance_profile,
)
from elite_backup import BackupManager
from senia_auto_match import auto_match as senia_auto_match_pixels
from senia_dual_shot import analyze_dual_shot as senia_dual_shot
from senia_next_gen import (
    cam16_forward, cam16_delta, metamerism_risk,
    compute_surface_fingerprint, delta_e_to_cost, batch_consistency_index,
)
from senia_synergy import (
    predictive_maintenance, customer_specific_risk,
    one_click_color_match, batch_stability_monitor, smart_decision,
)
from senia_ai_brain import (
    ExperienceMemory, CaseMemory, expert_reasoning_chain,
    parse_operator_input, proactive_suggestions,
)
from senia_lifelong_learning import LifelongLearner
from senia_innovations_v2 import (
    DriftEarlyWarning, reverse_engineer_color, ColorSearchEngine,
    CustomerColorProfile, diagnose_machine_from_drift,
    seasonal_compensation, anisotropy_analysis, generate_ar_preview_data,
)
from senia_capture_station import CAPTURE_STATION_BOM, BUILD_STEPS, IPHONE_CAMERA_SETTINGS
from senia_colorchecker import calibrate_from_photo
from senia_edge_sdk import analyze_offline as edge_analyze_offline
from senia_instant import process_instant, InstantResult
from senia_knowledge_crawler import KnowledgeEngine, WebCrawler, AutoModelUpgrader
from senia_spa import render_senia_spa
from senia_predictor import ProductionPredictor, DeviceFingerprint
from senia_qr_passport import generate_passport, verify_passport, render_passport_html
from senia_learning import (
    OnlineLearner,
    AmbientLightLearner,
    RecipeDigitalTwin,
    CrossBatchMemory,
    predict_aging_acceptance,
)
from senia_history import compute_lot_trend, compare_with_baseline
from senia_image_pipeline import analyze_photo as senia_analyze_photo
from senia_models import (
    SeniaAnalyzeResponse,
    SeniaCalibrationResponse,
    SeniaLotTrendResponse,
    SeniaThresholdResponse,
)
from senia_threshold_store import ThresholdStore
from senia_web_ui import render_senia_home
from elite_batch_parallel import run_parallel_batch
from elite_config_reload import ConfigStore
from elite_event_bus import EventBus, FileQueueSubscriber, QualityDecisionEvent
from elite_i18n import get_locale, set_locale, t
from elite_image_store import ImageStore
from elite_logging import get_logger, setup_logging
from elite_report_pdf import generate_report
from elite_runtime import load_runtime_settings
from elite_web_console import (
    render_executive_brief_page,
    render_executive_dashboard,
    render_home_page,
    render_innovation_v3_dashboard_page,
    render_precision_observatory_page,
    get_precision_observatory_module_js,
)

ROOT_DIR = Path(__file__).resolve().parent
SETTINGS = load_runtime_settings(ROOT_DIR)
setup_logging(level=SETTINGS.log_level)
_log = get_logger("elite_api")
APP_VERSION = "2.4.0"
DEFAULT_OUTPUT_ROOT = SETTINGS.default_output_root
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
DEFAULT_GLOB = "*.jpg,*.jpeg,*.png,*.bmp,*.tif,*.tiff,*.webp"
DEFAULT_ACTION_RULES_CONFIG = ROOT_DIR / "process_action_rules.json"
DEFAULT_DECISION_POLICY_CONFIG = ROOT_DIR / "decision_policy.default.json"
DEFAULT_CUSTOMER_TIER_CONFIG = ROOT_DIR / "customer_tier_policy.default.json"
DEFAULT_INNOVATION_DOC = ROOT_DIR / "SENIA_ELITE_v14_创新全案.md"
DEFAULT_HISTORY_DB = SETTINGS.default_history_db
DEFAULT_INNOVATION_DB = SETTINGS.default_innovation_db
INNOVATION_ENGINE = EliteInnovationEngine()
INNOVATION_LOCK = RLock()
MVP2_PIPELINE = ColorFilmPipelineV2()
ULTIMATE_SYSTEM = UltimateColorFilmSystem()
ULTIMATE_LOCK = RLock()
APP_START_TS = time.time()
ACCEPTANCE_SYNC_CACHE: dict[str, dict[str, Any]] = {}
AUDIT_LOG_PATH = SETTINGS.audit_log_path
METRICS_LOCK = RLock()
AUDIT_LOG_LOCK = RLock()
REQUEST_RECENT_TS: deque[float] = deque(maxlen=SETTINGS.metrics_window_size)
REQUEST_STATUS_COUNTS: dict[str, int] = {}
REQUEST_PATH_STATS: dict[str, dict[str, Any]] = {}
REQUEST_TOTAL_COUNT = 0
REQUEST_ERROR_COUNT = 0
RATE_LIMIT_LOCK = RLock()
RATE_LIMIT_BUCKETS: dict[str, deque[float]] = {}
RATE_LIMIT_MAX_BUCKETS = 5000
RATE_LIMIT_CLEANUP_BATCH = 2000
RATE_LIMIT_STALE_SECONDS = 300
ROLE_RANK = {"viewer": 1, "operator": 2, "admin": 3}
TENANT_HEADER_NAME = SETTINGS.tenant_header_name.strip() or "x-tenant-id"
ALLOWED_TENANTS = {x.strip() for x in SETTINGS.allowed_tenants_csv.split(",") if x.strip()}
ALERT_LEVEL_RANK = {"info": 1, "warning": 2, "error": 3, "critical": 4}
ALERT_MIN_LEVEL = SETTINGS.alert_min_level if SETTINGS.alert_min_level in ALERT_LEVEL_RANK else "error"
ALERT_PROVIDER = SETTINGS.alert_provider if SETTINGS.alert_provider in {"webhook", "wecom", "dingtalk"} else "webhook"
ALERT_LOCK = RLock()
ALERT_LAST_SENT: dict[str, float] = {}
ALERT_DEAD_LETTER_PATH = SETTINGS.alert_dead_letter_path
ALERT_DEAD_LETTER_LOCK = RLock()
OPS_SUMMARY_CACHE_LOCK = RLock()
OPS_SUMMARY_CACHE: dict[str, dict[str, Any]] = {}

# ── New production modules ─────────────────────────────────
CONFIG_STORE = ConfigStore(check_interval_sec=3.0)
CONFIG_STORE.register("decision_policy", DEFAULT_DECISION_POLICY_CONFIG)
CONFIG_STORE.register("customer_tier", DEFAULT_CUSTOMER_TIER_CONFIG)
CONFIG_STORE.register("action_rules", DEFAULT_ACTION_RULES_CONFIG)

IMAGE_STORE = ImageStore(root=DEFAULT_OUTPUT_ROOT / "image_archive")

EVENT_BUS = EventBus(async_delivery=True)
EVENT_BUS.add_subscriber(FileQueueSubscriber(DEFAULT_OUTPUT_ROOT / "event_queue"))

BACKUP_MANAGER = BackupManager(
    backup_dir=DEFAULT_OUTPUT_ROOT / "backups",
    sources=[DEFAULT_HISTORY_DB, DEFAULT_INNOVATION_DB],
    config_files=[DEFAULT_DECISION_POLICY_CONFIG, DEFAULT_CUSTOMER_TIER_CONFIG, DEFAULT_ACTION_RULES_CONFIG],
)

THRESHOLD_STORE = ThresholdStore(config_path=ROOT_DIR / "senia_thresholds.json")
SENIA_ANALYZE_SEMAPHORE = AsyncSemaphore(3)
PRODUCTION_PREDICTOR = ProductionPredictor(store_path=DEFAULT_OUTPUT_ROOT / "senia_predictor.json")
DEVICE_FINGERPRINT = DeviceFingerprint(store_path=DEFAULT_OUTPUT_ROOT / "senia_device_fp.json")
KNOWLEDGE_ENGINE = KnowledgeEngine(store_path=DEFAULT_OUTPUT_ROOT / "senia_knowledge.json")
DRIFT_WARNING = DriftEarlyWarning()
AI_MEMORY = ExperienceMemory(store_path=DEFAULT_OUTPUT_ROOT / "senia_ai_memory.json")
LIFELONG = LifelongLearner(store_dir=DEFAULT_OUTPUT_ROOT)
COLOR_SEARCH = ColorSearchEngine()
CUSTOMER_PROFILES = CustomerColorProfile()
WEB_CRAWLER = WebCrawler(cache_dir=DEFAULT_OUTPUT_ROOT / "crawler_cache")
AUTO_UPGRADER = AutoModelUpgrader(
    knowledge=KNOWLEDGE_ENGINE, crawler=WEB_CRAWLER,
    log_path=DEFAULT_OUTPUT_ROOT / "senia_upgrade_log.jsonl",
)
ONLINE_LEARNER = OnlineLearner(store_path=DEFAULT_OUTPUT_ROOT / "senia_feedback.json")
AMBIENT_LEARNER = AmbientLightLearner(store_path=DEFAULT_OUTPUT_ROOT / "senia_ambient.json")
RECIPE_TWIN = RecipeDigitalTwin(store_path=DEFAULT_OUTPUT_ROOT / "senia_recipe_twin.json")
BATCH_MEMORY = CrossBatchMemory(store_path=DEFAULT_OUTPUT_ROOT / "senia_batch_memory.json")

_log.info("modules_initialized", version=APP_VERSION,
          config_count=len(CONFIG_STORE.status()),
          image_root=str(IMAGE_STORE._root))

SENSITIVE_QUERY_KEYS = {
    "api_key",
    "apikey",
    "access_token",
    "token",
    "authorization",
    "password",
    "passwd",
    "pwd",
    "secret",
    "secret_key",
    "private_key",
    "signature",
}


def _looks_sensitive_query_key(key: str) -> bool:
    normalized = key.strip().lower().replace("-", "_")
    if not normalized:
        return False
    if normalized in SENSITIVE_QUERY_KEYS:
        return True
    if normalized.endswith("_token") or normalized.endswith("_key"):
        return True
    return "password" in normalized or "secret" in normalized


def _redact_sensitive_value(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return "***"
    return f"{value[:2]}***{value[-2:]}"


def _sanitize_query_string(query: str) -> str:
    raw = query.strip()
    if not raw:
        return ""
    try:
        pairs = urllib.parse.parse_qsl(raw, keep_blank_values=True)
    except ValueError:
        return raw
    safe_pairs: list[tuple[str, str]] = []
    for key, value in pairs:
        if _looks_sensitive_query_key(key):
            safe_pairs.append((key, _redact_sensitive_value(value)))
        else:
            safe_pairs.append((key, value))
    return urllib.parse.urlencode(safe_pairs, doseq=True)


def _apply_security_headers(response: Response, path: str) -> None:
    if not SETTINGS.enable_security_headers:
        return
    headers = response.headers
    if "x-content-type-options" not in headers:
        headers["x-content-type-options"] = "nosniff"
    if "x-frame-options" not in headers:
        headers["x-frame-options"] = "DENY"
    if "referrer-policy" not in headers:
        headers["referrer-policy"] = "no-referrer"
    if "permissions-policy" not in headers:
        headers["permissions-policy"] = "camera=(), microphone=(), geolocation=()"
    if (path.startswith("/v1/") or path in {"/health", "/ready"}) and "cache-control" not in headers:
        headers["cache-control"] = "no-store"


def _audit_rotated_file(path: Path, idx: int) -> Path:
    return Path(f"{path}.{idx}")


def _rotate_audit_log_if_needed() -> None:
    max_bytes = int(SETTINGS.audit_rotate_max_mb) * 1024 * 1024
    if max_bytes <= 0:
        return
    if not AUDIT_LOG_PATH.exists():
        return
    try:
        if AUDIT_LOG_PATH.stat().st_size < max_bytes:
            return
    except OSError:
        return

    backups = max(1, int(SETTINGS.audit_rotate_backups))
    for idx in range(backups, 0, -1):
        src = AUDIT_LOG_PATH if idx == 1 else _audit_rotated_file(AUDIT_LOG_PATH, idx - 1)
        dst = _audit_rotated_file(AUDIT_LOG_PATH, idx)
        if not src.exists():
            continue
        if dst.exists():
            dst.unlink(missing_ok=True)
        src.replace(dst)


def _count_existing_audit_backups() -> int:
    backups = max(1, int(SETTINGS.audit_rotate_backups))
    count = 0
    for idx in range(1, backups + 1):
        if _audit_rotated_file(AUDIT_LOG_PATH, idx).exists():
            count += 1
    return count


def _append_unique(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def _clean_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


def _parse_optional_dict_json(payload_text: str | None, field_name: str) -> dict[str, Any] | None:
    raw = _clean_optional_text(payload_text)
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"{field_name} must be valid JSON") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail=f"{field_name} must be a JSON object")
    return data


def _parse_api_keys_map(raw: str) -> dict[str, str]:
    text = (raw or "").strip()
    if not text:
        return {}
    key_to_role: dict[str, str] = {}
    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            # layout A: {"viewer":"k1","operator":["k2"],"admin":"k3"}
            for role, values in payload.items():
                role_key = str(role).strip().lower()
                if role_key not in ROLE_RANK:
                    continue
                items = values if isinstance(values, list) else [values]
                for item in items:
                    key_text = str(item).strip()
                    if key_text:
                        key_to_role[key_text] = role_key
            if key_to_role:
                return key_to_role

            # layout B: {"k1":"viewer","k2":"operator","k3":"admin"}
            for key_raw, role_raw in payload.items():
                role_key = str(role_raw).strip().lower()
                key_text = str(key_raw).strip()
                if role_key in ROLE_RANK and key_text:
                    key_to_role[key_text] = role_key
            if key_to_role:
                return key_to_role
    except (json.JSONDecodeError, KeyError, ValueError, AttributeError):
        pass

    # fallback format: "viewer:key1,operator:key2,admin:key3"
    # also compatible with reversed tokens: "key1:viewer,key2:operator"
    for token in text.replace(";", ",").split(","):
        part = token.strip()
        if ":" not in part:
            continue
        left_raw, right_raw = part.split(":", 1)
        left = left_raw.strip()
        right = right_raw.strip()
        role_key = ""
        key_text = ""
        if left.lower() in ROLE_RANK and right:
            role_key = left.lower()
            key_text = right
        elif right.lower() in ROLE_RANK and left:
            role_key = right.lower()
            key_text = left
        if role_key in ROLE_RANK and key_text:
            key_to_role[key_text] = role_key
    return key_to_role


API_KEY_ROLE_MAP = _parse_api_keys_map(SETTINGS.api_keys_json)
API_KEY_AUTH_ENABLED = bool(SETTINGS.enable_api_key_auth and API_KEY_ROLE_MAP)


def _is_public_path(path: str) -> bool:
    if path == "/" or path == "/health" or path == "/ready" or path == "/favicon.ico":
        return True
    if path.startswith("/docs") or path.startswith("/redoc") or path.startswith("/openapi.json"):
        return True
    if path == "/v1/web/executive-dashboard":
        return True
    if path == "/v1/web/innovation-v3":
        return True
    if path == "/v1/web/precision-observatory":
        return True
    if path == "/v1/web/assets/observatory-module.js":
        return True
    return False


def _required_role_for_path(path: str, method: str) -> str | None:
    _ = method  # currently reserved for future use
    if not path.startswith("/v1/"):
        return None
    if (
        path.startswith("/v1/system/audit-tail")
        or path.startswith("/v1/system/self-test")
        or path.startswith("/v1/system/alert-test")
        or path.startswith("/v1/system/alert-dead-letter")
        or path.startswith("/v1/system/alert-replay")
    ):
        return "admin"
    if path.startswith("/v1/system/ops-summary"):
        return "operator"
    if path.startswith("/v1/system/executive-brief"):
        return "operator"
    if path.startswith("/v1/system/executive-weekly-card"):
        return "operator"
    if path.startswith("/v1/system/cockpit-snapshot"):
        return "operator"
    if path.startswith("/v1/system/next-best-action"):
        return "operator"
    if path.startswith("/v1/web/executive-brief"):
        return "operator"
    if path.startswith("/v1/system/metrics"):
        return "operator"
    if path.startswith("/v1/system/slo"):
        return "operator"
    if path.startswith("/v1/system/release-gate-report"):
        return "operator"
    if path.startswith("/v1/outcome/record"):
        return "operator"
    if path.startswith("/v1/customer/acceptance-record"):
        return "operator"
    if path.startswith("/v1/strategy/"):
        return "operator"
    if path.startswith("/v1/passport/generate"):
        return "operator"
    if path.startswith("/v1/analyze/") or path.startswith("/v1/web/analyze/"):
        return "operator"
    if path.startswith("/v1/predict/") or path.startswith("/v1/correct/") or path.startswith("/v1/optimize/"):
        return "operator"
    if path.startswith("/v1/history/executive-export"):
        return "operator"
    if path.startswith("/v1/quality/"):
        return "operator"
    if path.startswith("/v1/report/shift/generate"):
        return "operator"
    if path.startswith("/v1/supplier/record"):
        return "operator"
    if path.startswith("/v1/standards/register"):
        return "operator"
    if path.startswith("/v1/mvp2/"):
        return "operator"
    if path.startswith("/v1/lifecycle/"):
        return "operator"
    return "viewer"


def _extract_api_key(request: Request) -> str | None:
    header_primary = SETTINGS.auth_header_name.strip() or "x-api-key"
    key = request.headers.get(header_primary)
    if not key and header_primary.lower() != "x-api-key":
        key = request.headers.get("x-api-key")
    if key:
        return key.strip() or None
    query_key = request.query_params.get("api_key", "").strip()
    return query_key or None


def _extract_tenant_id(request: Request) -> str | None:
    tenant = request.headers.get(TENANT_HEADER_NAME, "")
    if not tenant and TENANT_HEADER_NAME.lower() != "x-tenant-id":
        tenant = request.headers.get("x-tenant-id", "")
    tenant = tenant.strip()
    if tenant:
        return tenant
    query_tenant = request.query_params.get("tenant_id", "").strip()
    return query_tenant or None


def _consume_rate_limit_token(bucket_key: str) -> tuple[bool, int]:
    rpm = int(SETTINGS.rate_limit_rpm)
    if rpm <= 0:
        return True, 0
    now_ts = time.time()
    cutoff = now_ts - 60.0
    with RATE_LIMIT_LOCK:
        bucket = RATE_LIMIT_BUCKETS.get(bucket_key)
        if bucket is None:
            bucket = deque()
            RATE_LIMIT_BUCKETS[bucket_key] = bucket
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= rpm:
            retry_after = max(1, int(60 - (now_ts - bucket[0])))
            return False, retry_after
        bucket.append(now_ts)
        if len(RATE_LIMIT_BUCKETS) > RATE_LIMIT_MAX_BUCKETS:
            stale_keys = [k for k, v in RATE_LIMIT_BUCKETS.items() if not v or (now_ts - v[-1]) > RATE_LIMIT_STALE_SECONDS]
            for k in stale_keys[:RATE_LIMIT_CLEANUP_BATCH]:
                RATE_LIMIT_BUCKETS.pop(k, None)
    return True, 0


def _authorize_request(request: Request, path: str, method: str, client_ip: str) -> JSONResponse | None:
    request.state.auth_role = "anonymous"
    request.state.auth_key_id = None
    request.state.tenant_id = None

    if _is_public_path(path):
        request.state.auth_role = "public"
        request.state.tenant_id = "public"
        return None

    required_role = _required_role_for_path(path, method)
    if required_role is None:
        request.state.auth_role = "public"
        request.state.tenant_id = "public"
        return None

    tenant_id = _extract_tenant_id(request)
    if SETTINGS.enforce_tenant_header and not tenant_id:
        return JSONResponse(
            status_code=400,
            content={"detail": "missing tenant header", "header": TENANT_HEADER_NAME},
        )
    if tenant_id and ALLOWED_TENANTS and tenant_id not in ALLOWED_TENANTS:
        return JSONResponse(
            status_code=403,
            content={"detail": "tenant not allowed", "tenant_id": tenant_id},
        )
    request.state.tenant_id = tenant_id or "default"

    rate_bucket_key = f"{client_ip}::{request.state.tenant_id}"
    allowed, retry_after = _consume_rate_limit_token(rate_bucket_key)
    if not allowed:
        return JSONResponse(
            status_code=429,
            content={"detail": "rate limit exceeded", "retry_after_sec": retry_after},
            headers={"Retry-After": str(retry_after)},
        )

    if not SETTINGS.enable_api_key_auth:
        request.state.auth_role = "no-auth"
        return None

    if not API_KEY_ROLE_MAP:
        return JSONResponse(
            status_code=503,
            content={"detail": "api key auth enabled but no valid keys configured"},
        )

    key = _extract_api_key(request)
    if not key:
        return JSONResponse(
            status_code=401,
            content={
                "detail": "missing api key",
                "header": SETTINGS.auth_header_name,
                "required_role": required_role,
            },
        )

    role = API_KEY_ROLE_MAP.get(key)
    if role is None:
        return JSONResponse(
            status_code=401,
            content={"detail": "invalid api key", "required_role": required_role},
        )

    if ROLE_RANK.get(role, 0) < ROLE_RANK.get(required_role, 0):
        return JSONResponse(
            status_code=403,
            content={"detail": "insufficient role", "role": role, "required_role": required_role},
        )

    request.state.auth_role = role
    request.state.auth_key_id = f"{role}:{key[:6]}"
    return None


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _client_ip_from_request(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").strip()
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client is not None and request.client.host:
        return request.client.host
    return "unknown"


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    arr = sorted(values)
    pos = int(round((pct / 100.0) * (len(arr) - 1)))
    return round(arr[max(0, min(pos, len(arr) - 1))], 2)


def _prune_request_path_stats_locked(max_entries: int) -> None:
    if max_entries <= 0:
        return
    current_size = len(REQUEST_PATH_STATS)
    if current_size <= max_entries:
        return
    remove_count = current_size - max_entries
    sorted_items = sorted(
        REQUEST_PATH_STATS.items(),
        key=lambda kv: float(kv[1].get("last_seen_ts", 0.0)),
    )
    for path, _ in sorted_items[:remove_count]:
        REQUEST_PATH_STATS.pop(path, None)


def _record_request_metrics(path: str, method: str, status_code: int, elapsed_ms: float, client_ip: str) -> None:
    global REQUEST_TOTAL_COUNT, REQUEST_ERROR_COUNT  # noqa: PLW0603
    now_ts = time.time()
    status_key = str(int(status_code))
    with METRICS_LOCK:
        REQUEST_TOTAL_COUNT += 1
        if status_code >= 400:
            REQUEST_ERROR_COUNT += 1
        REQUEST_STATUS_COUNTS[status_key] = int(REQUEST_STATUS_COUNTS.get(status_key, 0)) + 1
        REQUEST_RECENT_TS.append(now_ts)
        stat = REQUEST_PATH_STATS.get(path)
        if stat is None:
            stat = {
                "method": method,
                "count": 0,
                "error_count": 0,
                "last_status": 0,
                "last_seen": "",
                "last_seen_ts": 0.0,
                "last_client_ip": "",
                "latency_ms_total": 0.0,
                "latency_ms_max": 0.0,
                "recent_ms": deque(maxlen=240),
            }
            REQUEST_PATH_STATS[path] = stat
        stat["count"] = int(stat.get("count", 0)) + 1
        if status_code >= 400:
            stat["error_count"] = int(stat.get("error_count", 0)) + 1
        stat["last_status"] = int(status_code)
        stat["last_seen"] = _now_text()
        stat["last_seen_ts"] = now_ts
        stat["last_client_ip"] = client_ip
        stat["latency_ms_total"] = float(stat.get("latency_ms_total", 0.0)) + float(elapsed_ms)
        stat["latency_ms_max"] = max(float(stat.get("latency_ms_max", 0.0)), float(elapsed_ms))
        recent = stat.get("recent_ms")
        if isinstance(recent, deque):
            recent.append(float(elapsed_ms))
        _prune_request_path_stats_locked(max_entries=int(SETTINGS.metrics_max_path_entries))


def _get_metrics_snapshot(top_n: int = 30) -> dict[str, Any]:
    with METRICS_LOCK:
        now_ts = time.time()
        recent_rpm = sum(1 for ts in REQUEST_RECENT_TS if (now_ts - ts) <= 60.0)
        path_rows: list[dict[str, Any]] = []
        for path, stat in REQUEST_PATH_STATS.items():
            count = int(stat.get("count", 0))
            if count <= 0:
                continue
            recent_ms_deque = stat.get("recent_ms")
            recent_ms = list(recent_ms_deque) if isinstance(recent_ms_deque, deque) else []
            avg_ms = float(stat.get("latency_ms_total", 0.0)) / float(count)
            path_rows.append(
                {
                    "path": path,
                    "method": stat.get("method"),
                    "count": count,
                    "error_count": int(stat.get("error_count", 0)),
                    "error_ratio": round(float(stat.get("error_count", 0)) / float(count), 4),
                    "latency_ms_avg": round(avg_ms, 2),
                    "latency_ms_p50": _percentile(recent_ms, 50),
                    "latency_ms_p95": _percentile(recent_ms, 95),
                    "latency_ms_max": round(float(stat.get("latency_ms_max", 0.0)), 2),
                    "last_status": int(stat.get("last_status", 0)),
                    "last_seen": stat.get("last_seen"),
                    "last_client_ip": stat.get("last_client_ip"),
                }
            )
        path_rows.sort(key=lambda x: x.get("count", 0), reverse=True)
        total_count = int(REQUEST_TOTAL_COUNT)
        error_count = int(REQUEST_ERROR_COUNT)
        return {
            "captured_at": _now_text(),
            "totals": {
                "request_count": total_count,
                "error_count": error_count,
                "error_ratio": round((error_count / total_count), 4) if total_count > 0 else 0.0,
                "recent_requests_per_min": recent_rpm,
                "uptime_sec": round(max(0.0, time.time() - APP_START_TS), 2),
            },
            "status_counts": dict(sorted(REQUEST_STATUS_COUNTS.items(), key=lambda kv: kv[0])),
            "path_count": len(REQUEST_PATH_STATS),
            "top_paths": path_rows[: max(1, int(top_n))],
        }


def _write_audit_event(event: dict[str, Any]) -> None:
    if not SETTINGS.enable_audit_log:
        return
    try:
        AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(event, ensure_ascii=False)
        with AUDIT_LOG_LOCK:
            _rotate_audit_log_if_needed()
            with AUDIT_LOG_PATH.open("a", encoding="utf-8") as fp:
                fp.write(line + "\n")
    except Exception:
        # Audit logging must not block the business request path,
        # but we still log the failure to stderr for operational visibility.
        print("[WARN] audit log write failed", file=sys.stderr)
        return


def _parse_alert_webhook_map(raw_text: str, default_webhook: str) -> dict[str, str]:
    mapping: dict[str, str] = {}
    default = default_webhook.strip()
    if default:
        for level in ALERT_LEVEL_RANK:
            mapping[level] = default
    text = (raw_text or "").strip()
    if not text:
        return mapping
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return mapping
    if not isinstance(payload, dict):
        return mapping

    for key, value in payload.items():
        level_key = str(key).strip().lower()
        url = str(value).strip() if value is not None else ""
        if not url.startswith("http://") and not url.startswith("https://"):
            continue
        if level_key == "default":
            for level in ALERT_LEVEL_RANK:
                mapping[level] = url
            continue
        if level_key in ALERT_LEVEL_RANK:
            mapping[level_key] = url
    return mapping


ALERT_WEBHOOK_MAP = _parse_alert_webhook_map(SETTINGS.alert_webhook_map_json, SETTINGS.alert_webhook_url)


def _alert_level_allowed(level: str) -> bool:
    rank = ALERT_LEVEL_RANK.get(level, 0)
    min_rank = ALERT_LEVEL_RANK.get(ALERT_MIN_LEVEL, ALERT_LEVEL_RANK["error"])
    return rank >= min_rank


def _resolve_alert_webhook(level: str) -> str:
    level_key = (level or "").strip().lower()
    if level_key in ALERT_WEBHOOK_MAP:
        return ALERT_WEBHOOK_MAP[level_key]
    return SETTINGS.alert_webhook_url.strip()


def _alert_dead_letter_rotated_file(path: Path, idx: int) -> Path:
    return Path(f"{path}.{idx}")


def _rotate_alert_dead_letter_if_needed() -> None:
    max_bytes = int(SETTINGS.alert_dead_letter_max_mb) * 1024 * 1024
    if max_bytes <= 0:
        return
    if not ALERT_DEAD_LETTER_PATH.exists():
        return
    try:
        if ALERT_DEAD_LETTER_PATH.stat().st_size < max_bytes:
            return
    except OSError:
        return

    backups = max(1, int(SETTINGS.alert_dead_letter_backups))
    for idx in range(backups, 0, -1):
        src = ALERT_DEAD_LETTER_PATH if idx == 1 else _alert_dead_letter_rotated_file(ALERT_DEAD_LETTER_PATH, idx - 1)
        dst = _alert_dead_letter_rotated_file(ALERT_DEAD_LETTER_PATH, idx)
        if not src.exists():
            continue
        if dst.exists():
            dst.unlink(missing_ok=True)
        src.replace(dst)


def _count_alert_dead_letter_backups() -> int:
    backups = max(1, int(SETTINGS.alert_dead_letter_backups))
    count = 0
    for idx in range(1, backups + 1):
        if _alert_dead_letter_rotated_file(ALERT_DEAD_LETTER_PATH, idx).exists():
            count += 1
    return count


def _write_alert_dead_letter(event: dict[str, Any]) -> None:
    try:
        ALERT_DEAD_LETTER_PATH.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(event, ensure_ascii=False)
        with ALERT_DEAD_LETTER_LOCK:
            _rotate_alert_dead_letter_if_needed()
            with ALERT_DEAD_LETTER_PATH.open("a", encoding="utf-8") as fp:
                fp.write(line + "\n")
    except OSError:
        return


def _read_alert_dead_letter_rows(limit: int = 200) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit), 1000))
    if not ALERT_DEAD_LETTER_PATH.exists():
        return []
    rows_raw: deque[str] = deque(maxlen=safe_limit)
    with ALERT_DEAD_LETTER_LOCK:
        with ALERT_DEAD_LETTER_PATH.open("r", encoding="utf-8", errors="replace") as fp:
            for line in fp:
                text = line.strip()
                if text:
                    rows_raw.append(text)
    rows: list[dict[str, Any]] = []
    for text in rows_raw:
        try:
            payload = json.loads(text)
            if isinstance(payload, dict):
                rows.append(payload)
            else:
                rows.append({"raw": text})
        except (json.JSONDecodeError, ValueError):
            rows.append({"raw": text})
    return rows


def _read_all_alert_dead_letter_rows() -> list[dict[str, Any]]:
    if not ALERT_DEAD_LETTER_PATH.exists():
        return []
    rows: list[dict[str, Any]] = []
    with ALERT_DEAD_LETTER_LOCK:
        with ALERT_DEAD_LETTER_PATH.open("r", encoding="utf-8", errors="replace") as fp:
            for line in fp:
                text = line.strip()
                if not text:
                    continue
                try:
                    payload = json.loads(text)
                    if isinstance(payload, dict):
                        rows.append(payload)
                    else:
                        rows.append({"raw": text})
                except Exception:
                    rows.append({"raw": text})
    return rows


def _rewrite_alert_dead_letter_rows(rows: list[dict[str, Any]]) -> None:
    with ALERT_DEAD_LETTER_LOCK:
        ALERT_DEAD_LETTER_PATH.parent.mkdir(parents=True, exist_ok=True)
        if not rows:
            ALERT_DEAD_LETTER_PATH.write_text("", encoding="utf-8")
            return
        with ALERT_DEAD_LETTER_PATH.open("w", encoding="utf-8") as fp:
            for row in rows:
                fp.write(json.dumps(row, ensure_ascii=False) + "\n")


def _build_alert_text(body: dict[str, Any]) -> str:
    payload = body.get("payload", {})
    payload_text = json.dumps(payload, ensure_ascii=False)
    return (
        f"[{body.get('level', 'info').upper()}] {body.get('title', '')}\n"
        f"service={body.get('service', '')} version={body.get('version', '')} time={body.get('time', '')}\n"
        f"{payload_text}"
    )


def _build_dingtalk_signed_url(webhook: str, secret: str) -> str:
    clean_secret = secret.strip()
    if not clean_secret:
        return webhook
    ts = str(int(time.time() * 1000))
    string_to_sign = f"{ts}\n{clean_secret}"
    digest = hmac.new(clean_secret.encode("utf-8"), string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(digest).decode("utf-8"))
    delimiter = "&" if "?" in webhook else "?"
    return f"{webhook}{delimiter}timestamp={ts}&sign={sign}"


def _dispatch_alert_once(webhook: str, body: dict[str, Any]) -> bool:
    provider = ALERT_PROVIDER
    url = webhook
    payload: dict[str, Any]

    if provider == "wecom":
        payload = {
            "msgtype": "markdown",
            "markdown": {"content": _build_alert_text(body)},
        }
    elif provider == "dingtalk":
        url = _build_dingtalk_signed_url(webhook, SETTINGS.alert_dingtalk_secret)
        payload = {
            "msgtype": "markdown",
            "markdown": {"title": str(body.get("title", "Elite alert")), "text": _build_alert_text(body)},
        }
    else:
        payload = body

    req = urllib.request.Request(
        url,
        method="POST",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=max(1, int(SETTINGS.alert_timeout_sec))) as resp:  # noqa: S310
        raw = resp.read().decode("utf-8", errors="replace").strip()
        if provider in {"wecom", "dingtalk"} and raw:
            try:
                parsed = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                return True
            if isinstance(parsed, dict):
                code = parsed.get("errcode")
                return code in {0, "0", None}
        return True


def _emit_alert(level: str, key: str, title: str, payload: dict[str, Any]) -> bool:
    webhook = _resolve_alert_webhook(level)
    if not webhook:
        return False
    if not _alert_level_allowed(level):
        return False

    now_ts = time.time()
    cooldown = max(0, int(SETTINGS.alert_cooldown_sec))
    with ALERT_LOCK:
        last_ts = ALERT_LAST_SENT.get(key, 0.0)
        if cooldown > 0 and (now_ts - last_ts) < cooldown:
            return False
        ALERT_LAST_SENT[key] = now_ts

    body = {
        "service": "elite-color-match-api",
        "version": APP_VERSION,
        "time": _now_text(),
        "level": level,
        "title": title,
        "payload": payload,
        "provider": ALERT_PROVIDER,
    }
    retries = max(0, int(SETTINGS.alert_retry_count))
    backoff_ms = max(0, int(SETTINGS.alert_retry_backoff_ms))
    last_error = ""
    for idx in range(retries + 1):
        try:
            return _dispatch_alert_once(webhook=webhook, body=body)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = str(exc)
            if idx >= retries:
                dead_event = {
                    "time": _now_text(),
                    "level": level,
                    "key": key,
                    "title": title,
                    "webhook": webhook,
                    "provider": ALERT_PROVIDER,
                    "attempt_count": retries + 1,
                    "error": last_error,
                    "body": body,
                }
                _write_alert_dead_letter(dead_event)
                return False
            if backoff_ms > 0:
                time.sleep((backoff_ms * (idx + 1)) / 1000.0)
    return False


def _emit_quality_risk_alert(endpoint: str, result_payload: dict[str, Any]) -> None:
    is_pass = bool(result_payload.get("pass"))
    if is_pass:
        return
    decision = result_payload.get("decision_center", {})
    process = result_payload.get("process_advice", {})
    innovation = result_payload.get("innovation_engine", {})
    decision_code = decision.get("decision_code") if isinstance(decision, dict) else None
    risk_level = process.get("risk_level") if isinstance(process, dict) else None
    aging_risk = innovation.get("aging_warranty_risk") if isinstance(innovation, dict) else None
    severity = "warning"
    if decision_code in {"REJECT", "RECAPTURE_REQUIRED"} or risk_level in {"high", "critical"}:
        severity = "error"
    _emit_alert(
        level=severity,
        key=f"quality::{endpoint}::{decision_code or 'na'}::{risk_level or 'na'}",
        title="Quality risk detected",
        payload={
            "endpoint": endpoint,
            "decision_code": decision_code,
            "risk_level": risk_level,
            "aging_risk": aging_risk,
            "output_dir": result_payload.get("output_dir"),
            "report_path": result_payload.get("report_path"),
        },
    )


def _flatten_metrics(prefix: str, payload: Any, rows: list[tuple[str, str]]) -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            child = f"{prefix}.{key}" if prefix else str(key)
            _flatten_metrics(child, value, rows)
        return
    if isinstance(payload, list):
        for idx, value in enumerate(payload):
            child = f"{prefix}[{idx}]"
            _flatten_metrics(child, value, rows)
        return
    if payload is None:
        rows.append((prefix, ""))
        return
    rows.append((prefix, str(payload)))


def _csv_escape(value: str) -> str:
    text = value.replace("\r", " ").replace("\n", " ")
    if any(ch in text for ch in [",", '"']):
        return '"' + text.replace('"', '""') + '"'
    return text


def _generate_output_dir(prefix: str, requested_dir: str | None) -> Path:
    if requested_dir:
        out = Path(requested_dir)
    else:
        out = DEFAULT_OUTPUT_ROOT / f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _decode_image_b64(raw: str) -> np.ndarray:
    payload = raw.strip()
    if payload.startswith("data:image") and "," in payload:
        payload = payload.split(",", 1)[1]
    try:
        buf = base64.b64decode(payload, validate=True)
    except (base64.binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"invalid image b64: {exc}") from exc
    arr = np.frombuffer(buf, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(status_code=400, detail="b64 payload is not a valid image")
    return img


def _list_images_from_dir(root: Path, patterns_csv: str, recursive: bool) -> list[Path]:
    patterns = [p.strip() for p in patterns_csv.split(",") if p.strip()]
    all_paths: list[Path] = []
    for pattern in patterns:
        if recursive:
            all_paths.extend(sorted(root.rglob(pattern)))
        else:
            all_paths.extend(sorted(root.glob(pattern)))

    unique: list[Path] = []
    seen: set[str] = set()
    for p in all_paths:
        if not p.is_file():
            continue
        key = str(p.resolve())
        if key in seen:
            continue
        seen.add(key)
        unique.append(p)
    return unique


def _quad_from_payload(quad: list[list[float]] | None, label: str) -> np.ndarray | None:
    if quad is None:
        return None
    arr = np.array(quad, dtype=np.float32)
    if arr.shape != (4, 2):
        raise HTTPException(status_code=400, detail=f"{label} must be [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]")
    return arr


def _resolve_action_rules_config(enabled: bool, explicit_path: str | None) -> Path | None:
    if not enabled:
        return None
    if explicit_path:
        p = Path(explicit_path)
        if not p.exists():
            raise HTTPException(status_code=400, detail=f"action rules config not found: {explicit_path}")
        return p
    if DEFAULT_ACTION_RULES_CONFIG.exists():
        return DEFAULT_ACTION_RULES_CONFIG
    return None


def _attach_process_advice(report: dict[str, Any], enabled: bool, explicit_path: str | None) -> None:
    cfg = _resolve_action_rules_config(enabled=enabled, explicit_path=explicit_path)
    attach_process_advice(report, cfg)


def _process_advice_brief(report: dict[str, Any]) -> dict[str, Any]:
    pa = report.get("process_advice", {})
    if not isinstance(pa, dict):
        return {"enabled": False}
    return {
        "enabled": bool(pa.get("enabled", False)),
        "risk_level": pa.get("risk_level"),
        "risk_score": pa.get("risk_score"),
        "matched_rule_count": pa.get("matched_rule_count"),
    }


def _resolve_decision_policy_config(enabled: bool, explicit_path: str | None) -> Path | None:
    if not enabled:
        return None
    if explicit_path:
        p = Path(explicit_path)
        if not p.exists():
            raise HTTPException(status_code=400, detail=f"decision policy config not found: {explicit_path}")
        return p
    if DEFAULT_DECISION_POLICY_CONFIG.exists():
        return DEFAULT_DECISION_POLICY_CONFIG
    return None


def _resolve_customer_tier_config(explicit_path: str | None) -> Path | None:
    if explicit_path:
        p = Path(explicit_path)
        if not p.exists():
            raise HTTPException(status_code=400, detail=f"customer tier config not found: {explicit_path}")
        return p
    if DEFAULT_CUSTOMER_TIER_CONFIG.exists():
        return DEFAULT_CUSTOMER_TIER_CONFIG
    return None


def _resolve_innovation_db_path(explicit_path: str | None) -> Path | None:
    if not explicit_path:
        return None
    p = Path(explicit_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _resolve_innovation_db_path_with_default(explicit_path: str | None) -> Path:
    p = Path(explicit_path) if explicit_path else DEFAULT_INNOVATION_DB
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _resolve_project_html_path(path_text: str) -> Path:
    raw = path_text.strip()
    if not raw:
        raise HTTPException(status_code=400, detail="path is required")
    candidate = Path(raw).expanduser()
    resolved = (ROOT_DIR / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
    if resolved.suffix.lower() != ".html":
        raise HTTPException(status_code=400, detail="only .html report is supported")
    try:
        resolved.relative_to(ROOT_DIR)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="report path must be inside project root") from exc
    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(status_code=404, detail=f"report not found: {resolved}")
    return resolved


def _resolve_decision_policy_for_request(
    enabled: bool,
    explicit_policy_path: str | None,
    customer_tier: str | None = None,
    customer_id: str | None = None,
    customer_tier_config_path: str | None = None,
) -> tuple[Path | None, dict[str, Any] | None, str | None, dict[str, Any] | None]:
    cfg = _resolve_decision_policy_config(enabled=enabled, explicit_path=explicit_policy_path)
    if not enabled:
        return cfg, None, None, None

    if not customer_tier and not customer_id and not customer_tier_config_path:
        return cfg, None, None, None

    base_policy, base_source = load_decision_policy(cfg)
    tier_cfg_path = _resolve_customer_tier_config(customer_tier_config_path)
    tier_cfg, tier_source = load_customer_tier_config(tier_cfg_path)
    applied = apply_customer_tier_to_policy(
        base_policy=base_policy,
        customer_tier_config=tier_cfg,
        customer_tier=customer_tier,
        customer_id=customer_id,
    )
    policy_source = f"{base_source}+tier:{applied.get('tier')}@{tier_source}"
    tier_info = {
        "tier": applied.get("tier"),
        "description": applied.get("tier_description"),
        "patch": applied.get("patch"),
        "customer_id": customer_id,
        "config_source": tier_source,
    }
    return cfg, applied.get("policy"), policy_source, tier_info


def _attach_decision_center(
    report: dict[str, Any],
    enabled: bool,
    explicit_path: str | None,
    customer_tier: str | None = None,
    customer_id: str | None = None,
    customer_tier_config_path: str | None = None,
) -> dict[str, Any] | None:
    cfg, policy_override, policy_source, tier_info = _resolve_decision_policy_for_request(
        enabled=enabled,
        explicit_policy_path=explicit_path,
        customer_tier=customer_tier,
        customer_id=customer_id,
        customer_tier_config_path=customer_tier_config_path,
    )
    attach_decision_center(
        report,
        cfg,
        enabled=enabled,
        policy_override=policy_override,
        policy_source_override=policy_source,
    )
    if tier_info is not None:
        report["customer_tier_applied"] = tier_info
    return tier_info


def _decision_center_brief(report: dict[str, Any]) -> dict[str, Any]:
    dc = report.get("decision_center", {})
    if not isinstance(dc, dict):
        return {"enabled": False}
    scores = dc.get("stakeholder_scores", {})
    return {
        "enabled": bool(dc.get("enabled", False)),
        "decision_code": dc.get("decision_code"),
        "priority": dc.get("priority"),
        "risk_probability": dc.get("risk_probability"),
        "estimated_cost": dc.get("estimated_cost"),
        "customer_score": scores.get("customer_score") if isinstance(scores, dict) else None,
        "boss_score": scores.get("boss_score") if isinstance(scores, dict) else None,
        "company_score": scores.get("company_score") if isinstance(scores, dict) else None,
        "customer_tier": (report.get("customer_tier_applied") or {}).get("tier") if isinstance(report.get("customer_tier_applied"), dict) else None,
    }


def _policy_recommendation_brief(report: dict[str, Any]) -> dict[str, Any]:
    pr = report.get("policy_recommendation", {})
    if not isinstance(pr, dict):
        return {"enabled": False}
    patch = pr.get("policy_patch", {})
    return {
        "enabled": bool(pr.get("enabled", False)),
        "insufficient_data": bool(pr.get("insufficient_data", False)),
        "recommendation_count": len(pr.get("recommendations", []) if isinstance(pr.get("recommendations", []), list) else []),
        "has_patch": bool(patch),
    }


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, lo: float, hi: float) -> float:
    return float(max(lo, min(hi, value)))


def _as_lab(value: Any, fallback: dict[str, float] | None = None) -> dict[str, float]:
    if isinstance(value, dict):
        if {"L", "a", "b"}.issubset(value.keys()):
            return {
                "L": _safe_float(value.get("L"), 0.0),
                "a": _safe_float(value.get("a"), 0.0),
                "b": _safe_float(value.get("b"), 0.0),
            }
        if {"l", "a", "b"}.issubset(value.keys()):
            return {
                "L": _safe_float(value.get("l"), 0.0),
                "a": _safe_float(value.get("a"), 0.0),
                "b": _safe_float(value.get("b"), 0.0),
            }
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        return {"L": _safe_float(value[0]), "a": _safe_float(value[1]), "b": _safe_float(value[2])}
    if fallback is not None:
        return fallback
    return {"L": 50.0, "a": 0.0, "b": 0.0}


def _lab_to_rgb_guess(lab: dict[str, float]) -> tuple[int, int, int]:
    l = _safe_float(lab.get("L"), 50.0)
    a = _safe_float(lab.get("a"), 0.0)
    b = _safe_float(lab.get("b"), 0.0)
    base = _clamp(l * 2.55, 0.0, 255.0)
    r = int(round(_clamp(base + 1.2 * a + 0.4 * b, 0.0, 255.0)))
    g = int(round(_clamp(base - 0.3 * a - 0.2 * b, 0.0, 255.0)))
    bl = int(round(_clamp(base - 1.0 * b, 0.0, 255.0)))
    return r, g, bl


def _first_numeric(values: Any, idx: int, default: float = 10.0) -> float:
    if isinstance(values, (list, tuple)) and len(values) > idx:
        return _safe_float(values[idx], default)
    return default


def _report_to_innovation_input(report: dict[str, Any]) -> dict[str, Any]:
    result = report.get("result", {})
    summary = result.get("summary", {}) if isinstance(result, dict) else {}
    confidence_obj = result.get("confidence", {}) if isinstance(result, dict) else {}
    mode = str(report.get("mode", "unknown"))

    avg_de = _safe_float(summary.get("avg_delta_e00"), np.nan)
    p95_de = _safe_float(summary.get("p95_delta_e00"), np.nan)
    d_l = _safe_float(summary.get("dL"), np.nan)
    d_c = _safe_float(summary.get("dC"), np.nan)
    d_h = _safe_float(summary.get("dH_deg"), np.nan)
    confidence = _safe_float(confidence_obj.get("overall"), np.nan) if isinstance(confidence_obj, dict) else np.nan

    if mode == "ensemble_single":
        avg_de = _safe_float(summary.get("median_avg_delta_e00"), avg_de)
        p95_de = _safe_float(summary.get("median_p95_delta_e00"), p95_de)
        d_l = _safe_float(summary.get("median_dL"), d_l)
        d_c = _safe_float(summary.get("median_dC"), d_c)
        d_h = _safe_float(summary.get("median_dH_deg"), d_h)
        confidence = _safe_float(confidence_obj.get("median"), confidence) if isinstance(confidence_obj, dict) else confidence

    board_lab_raw = summary.get("board_lab")
    sample_lab_raw = summary.get("sample_lab")
    ref_lab_raw = summary.get("reference_lab")
    film_lab_raw = summary.get("film_lab")

    if board_lab_raw is not None and sample_lab_raw is not None:
        sample_lab = _as_lab(board_lab_raw)
        film_lab = _as_lab(sample_lab_raw)
    elif ref_lab_raw is not None and film_lab_raw is not None:
        sample_lab = _as_lab(ref_lab_raw)
        film_lab = _as_lab(film_lab_raw)
    else:
        sample_lab = _as_lab(summary.get("sample_lab"))
        film_lab = _as_lab(summary.get("film_lab"), fallback=sample_lab)

    sample_rgb = _lab_to_rgb_guess(sample_lab)
    film_rgb = _lab_to_rgb_guess(film_lab)

    std_a = summary.get("board_std")
    std_b = summary.get("sample_std")
    if std_a is None:
        std_a = summary.get("reference_std")
    if std_b is None:
        std_b = summary.get("film_std")

    profile_used = str((report.get("profile") or {}).get("used", "auto")) if isinstance(report.get("profile"), dict) else "auto"
    texture_similarity = _safe_float((report.get("alignment") or {}).get("correlation"), 0.90) if isinstance(report.get("alignment"), dict) else 0.90

    return {
        "avg_de": 0.0 if np.isnan(avg_de) else avg_de,
        "p95_de": 0.0 if np.isnan(p95_de) else p95_de,
        "confidence": 0.75 if np.isnan(confidence) else confidence,
        "sample_lab": sample_lab,
        "film_lab": film_lab,
        "sample_rgb": sample_rgb,
        "film_rgb": film_rgb,
        "de_components": {
            "dL": 0.0 if np.isnan(d_l) else d_l,
            "dC": 0.0 if np.isnan(d_c) else d_c,
            "dH": 0.0 if np.isnan(d_h) else d_h,
        },
        "sample_texture_std": _first_numeric(std_a, 0, 10.0),
        "film_texture_std": _first_numeric(std_b, 0, 10.0),
        "texture_similarity": _clamp(texture_similarity, 0.0, 1.0),
        "material_type": profile_used,
        "avg_L": _safe_float(film_lab.get("L"), 0.0),
        "avg_a": _safe_float(film_lab.get("a"), 0.0),
        "avg_b": _safe_float(film_lab.get("b"), 0.0),
        "wb_applied": bool((report.get("preprocess") or {}).get("shading_correction")) if isinstance(report.get("preprocess"), dict) else False,
    }


def _attach_innovation_engine(
    report: dict[str, Any],
    enabled: bool,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not enabled:
        info = {"enabled": False, "reason": "disabled_by_flag"}
        report["innovation_engine"] = info
        return info
    try:
        run_input = _report_to_innovation_input(report)
        ctx = dict(context or {})
        tier_info = report.get("customer_tier_applied", {})
        if isinstance(tier_info, dict):
            if tier_info.get("customer_id") and "customer_id" not in ctx:
                ctx["customer_id"] = tier_info.get("customer_id")
            if tier_info.get("tier") and "customer_tier" not in ctx:
                ctx["customer_tier"] = tier_info.get("tier")
        with INNOVATION_LOCK:
            result = INNOVATION_ENGINE.full_analysis(run_input, ctx)
        info = {"enabled": True, **result}
    except Exception as exc:  # noqa: BLE001
        info = {"enabled": False, "reason": f"innovation_engine_error: {exc}"}
    report["innovation_engine"] = info
    return info


def _innovation_brief(report: dict[str, Any]) -> dict[str, Any]:
    ie = report.get("innovation_engine", {})
    if not isinstance(ie, dict):
        return {"enabled": False}
    if not bool(ie.get("enabled", False)):
        return {"enabled": False, "reason": ie.get("reason")}
    innovations = ie.get("innovations", {})
    if not isinstance(innovations, dict):
        return {"enabled": True, "innovation_count": 0}
    metamerism = innovations.get("metamerism", {})
    aging = innovations.get("aging_prediction", {})
    aging_wr = aging.get("warranty_risk", {}) if isinstance(aging, dict) else {}
    drift = innovations.get("drift_prediction", {})
    ink = innovations.get("ink_correction", {})
    return {
        "enabled": True,
        "innovation_count": len(innovations),
        "metamerism_risk": metamerism.get("risk_level") if isinstance(metamerism, dict) else None,
        "drift_urgency": drift.get("urgency") if isinstance(drift, dict) else None,
        "aging_warranty_risk": aging_wr.get("level") if isinstance(aging_wr, dict) else None,
        "ink_adjustment": ink.get("adjustments_description") if isinstance(ink, dict) else None,
    }


def _load_report_payload(report_path: str | None, report_payload: dict[str, Any] | None) -> dict[str, Any]:
    if report_payload is not None:
        if not isinstance(report_payload, dict):
            raise HTTPException(status_code=400, detail="report payload must be a JSON object")
        return report_payload
    if not report_path:
        raise HTTPException(status_code=400, detail="provide report or report_path")
    fp = Path(report_path)
    if not fp.exists():
        raise HTTPException(status_code=400, detail=f"report not found: {report_path}")
    try:
        payload = json.loads(fp.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"invalid report json: {exc}") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="report json must be an object")
    return payload


def _sync_acceptance_customer_from_db(db_path: str | None, customer_id: str) -> tuple[Path | None, int, bool]:
    path = _resolve_innovation_db_path(db_path)
    if path is None:
        return None, 0, False
    cache_key = f"{str(path.resolve())}::{customer_id}"
    now = time.time()
    ttl = max(0, int(SETTINGS.acceptance_sync_ttl_sec))
    hit = ACCEPTANCE_SYNC_CACHE.get(cache_key)
    if hit and (now - float(hit.get("loaded_at", 0.0)) <= ttl):
        return path, 0, True
    with INNOVATION_LOCK:
        loaded = reload_customer_acceptance_from_db(
            db_path=path,
            learner=INNOVATION_ENGINE.acceptance,
            customer_id=customer_id,
        )
    ACCEPTANCE_SYNC_CACHE[cache_key] = {"loaded_at": now, "events_loaded": loaded}
    return path, loaded, False


def _build_supplier_engine_from_db(db_path: Path) -> Any:
    supplier_engine = INNOVATION_ENGINE.supplier.__class__()
    records = load_supplier_records(db_path=db_path, supplier_id=None, limit=50000)
    for row in records:
        supplier_engine.record(
            supplier_id=str(row.get("supplier_id", "")),
            delta_e=float(row.get("delta_e", 0.0)),
            product=str(row.get("product", "")),
            passed=bool(row.get("passed", True)),
            ts=str(row.get("ts", "")),
        )
    return supplier_engine


def _build_standard_library_from_db(db_path: Path) -> Any:
    library = INNOVATION_ENGINE.library.__class__()
    versions = load_standard_versions(db_path=db_path, code=None, limit=50000)
    for row in versions:
        library.import_version(
            code=str(row.get("code", "")),
            version=int(row.get("version", 1)),
            lab=row.get("lab", {"L": 0.0, "a": 0.0, "b": 0.0}),
            source=str(row.get("source", "")),
            notes=str(row.get("notes", "")),
            created=str(row.get("created_at", "")),
        )
    return library


def _add_history_assessment(report: dict[str, Any], history: "HistoryConfig | None") -> None:
    if history is None:
        return

    db_path = Path(history.db_path)
    init_db(db_path)
    assessment = assess_current_vs_history(
        db_path=db_path,
        report=report,
        line_id=history.line_id,
        product_code=history.product_code,
        window=max(5, int(history.window)),
    )
    report["history_assessment"] = assessment
    if not assessment.get("enabled"):
        return

    flags = assessment.get("flags", [])
    if not flags:
        return

    quality_flags = report.get("result", {}).setdefault("quality_flags", [])
    guidance = report.get("result", {}).setdefault("capture_guidance", [])
    for flag in flags:
        _append_unique(quality_flags, str(flag))
    if "history_drift_uptrend" in flags:
        _append_unique(guidance, "History trend shows DeltaE rising; check raw material batch and equipment stability.")
    if "history_confidence_drop" in flags:
        _append_unique(guidance, "History comparison shows confidence drop; check station lighting and lens cleanliness.")
    if any(f in flags for f in ("history_avg_outlier_high", "history_p95_outlier_high", "history_max_outlier_high")):
        _append_unique(guidance, "Current result is above historical baseline; apply small-step adjustment then recheck.")


def _add_policy_recommendation(report: dict[str, Any], history: "HistoryConfig | None") -> None:
    if history is None:
        return
    try:
        report["policy_recommendation"] = recommend_policy_adjustments(
            db_path=Path(history.db_path),
            line_id=history.line_id,
            product_code=history.product_code,
            lot_id=history.lot_id,
            window=max(20, int(history.window) * 4),
        )
    except Exception:  # noqa: BLE001
        pass

def _record_with_history(
    report: dict[str, Any],
    history: "HistoryConfig | None",
    report_path: Path,
) -> None:
    if history is None:
        return
    try:
        record_run(
            db_path=Path(history.db_path),
            report=report,
            line_id=history.line_id,
            product_code=history.product_code,
            lot_id=history.lot_id,
            report_path=str(report_path),
        )
        _invalidate_ops_summary_cache()
    except Exception:  # noqa: BLE001
        pass


class ImageInput(BaseModel):
    path: str | None = Field(default=None, description="Local image path")
    b64: str | None = Field(default=None, description="Base64 image payload (raw or data URI)")

    @model_validator(mode="after")
    def validate_source(self) -> "ImageInput":
        if not self.path and not self.b64:
            raise ValueError("Either path or b64 is required")
        return self


class ROIInput(BaseModel):
    x: int
    y: int
    w: int
    h: int

    def to_roi(self) -> ROI:
        return ROI(x=int(self.x), y=int(self.y), w=int(self.w), h=int(self.h))


class HistoryConfig(BaseModel):
    db_path: str
    line_id: str | None = None
    product_code: str | None = None
    lot_id: str | None = None
    window: int = 30


class OutcomeRecordRequest(BaseModel):
    db_path: str
    outcome: str = Field(description="accepted/complaint_minor/complaint_major/return/rework/pending")
    run_id: int | None = None
    report_path: str | None = None
    line_id: str | None = None
    product_code: str | None = None
    lot_id: str | None = None
    severity: float | None = None
    realized_cost: float | None = None
    customer_rating: float | None = None
    note: str | None = None

    @model_validator(mode="after")
    def validate_ref(self) -> "OutcomeRecordRequest":
        if self.run_id is None and not self.report_path and not (self.line_id and self.product_code):
            raise ValueError("Provide run_id or report_path, or at least line_id+product_code")
        return self


class ChampionChallengerRequest(BaseModel):
    db_path: str
    line_id: str | None = None
    product_code: str | None = None
    lot_id: str | None = None
    window: int = 260
    champion_policy_config: str | None = None
    challenger_policy_config: str | None = None
    challenger_patch: dict[str, Any] | None = None
    canary_ratio: float = 0.15
    phase_days: int = 3


class LabInput(BaseModel):
    L: float
    a: float
    b: float

    def to_dict(self) -> dict[str, float]:
        return {"L": float(self.L), "a": float(self.a), "b": float(self.b)}


class SpectralAnalyzeRequest(BaseModel):
    sample_rgb: list[float]
    film_rgb: list[float]

    @model_validator(mode="after")
    def validate_rgb(self) -> "SpectralAnalyzeRequest":
        if len(self.sample_rgb) != 3 or len(self.film_rgb) != 3:
            raise ValueError("sample_rgb and film_rgb must be [r,g,b]")
        return self


class TextureAwareRequest(BaseModel):
    standard_delta_e: float
    sample_texture_std: float
    film_texture_std: float
    texture_similarity: float = 1.0
    material_type: str = "auto"


class FullInnovationRequest(BaseModel):
    report_path: str | None = None
    report: dict[str, Any] | None = None
    context: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_source(self) -> "FullInnovationRequest":
        if not self.report_path and self.report is None:
            raise ValueError("provide report_path or report")
        return self


class AgingPredictRequest(BaseModel):
    lab: LabInput
    material: str = "pvc_film"
    environment: str = "indoor_normal"
    years: list[int] | None = None


class DifferentialAgingPredictRequest(BaseModel):
    sample_lab: LabInput
    film_lab: LabInput
    sample_material: str = "melamine"
    film_material: str = "pvc_film"
    environment: str = "indoor_normal"
    years: list[int] | None = None


class InkCorrectionRequest(BaseModel):
    dL: float
    dC: float
    dH: float
    current_recipe: dict[str, float] | None = None
    confidence: float = 1.0


class BlendBatchItem(BaseModel):
    batch_id: str
    lab: LabInput
    quantity: float = 0.0


class BatchBlendOptimizeRequest(BaseModel):
    batches: list[BlendBatchItem]
    n_groups: int = 2
    customer_tiers: list[str] | None = None

    @model_validator(mode="after")
    def validate_batches(self) -> "BatchBlendOptimizeRequest":
        if len(self.batches) < 2:
            raise ValueError("batches must contain at least 2 items")
        return self


class CustomerAcceptanceRecordRequest(BaseModel):
    customer_id: str
    delta_e: float
    complained: bool
    db_path: str | None = None
    extra: dict[str, Any] | None = None


class PassportGenerateRequest(BaseModel):
    lot_id: str
    report_path: str | None = None
    report: dict[str, Any] | None = None
    context: dict[str, Any] | None = None
    decision: dict[str, Any] | None = None
    db_path: str | None = None

    @model_validator(mode="after")
    def validate_source(self) -> "PassportGenerateRequest":
        if not self.report_path and self.report is None:
            raise ValueError("provide report_path or report")
        return self


class PassportVerifyRequest(BaseModel):
    passport: dict[str, Any] | None = None
    passport_id: str | None = None
    db_path: str | None = None
    new_lab: LabInput

    @model_validator(mode="after")
    def validate_source(self) -> "PassportVerifyRequest":
        if self.passport is None and not self.passport_id:
            raise ValueError("provide passport object or passport_id")
        return self


class ObserverAnalyzeRequest(BaseModel):
    sample_lab: LabInput
    film_lab: LabInput
    standard_delta_e: float | None = None
    target_age: int = 35
    sensitivity: str = "normal"

    @model_validator(mode="after")
    def validate_sensitivity(self) -> "ObserverAnalyzeRequest":
        if self.sensitivity not in {"normal", "high"}:
            raise ValueError("sensitivity must be 'normal' or 'high'")
        return self


class SPCAnalyzeRequest(BaseModel):
    subgroups: list[list[float]]
    spec_lower: float = 0.0
    spec_upper: float = 3.0

    @model_validator(mode="after")
    def validate_subgroups(self) -> "SPCAnalyzeRequest":
        if len(self.subgroups) < 5:
            raise ValueError("subgroups must contain at least 5 entries")
        subgroup_size = len(self.subgroups[0]) if self.subgroups else 0
        if subgroup_size < 2 or subgroup_size > 10:
            raise ValueError("subgroup size must be between 2 and 10")
        if any(len(sg) != subgroup_size for sg in self.subgroups):
            raise ValueError("all subgroups must have the same size")
        return self


class ShiftRunItem(BaseModel):
    avg_de: float
    pass_flag: bool = Field(alias="pass")
    decision: str = "AUTO_RELEASE"
    confidence: float = 0.8
    product_code: str = ""
    lot_id: str = ""
    dL: float = 0.0
    dC: float = 0.0
    dH: float = 0.0


class ShiftGenerateRequest(BaseModel):
    runs: list[ShiftRunItem]
    shift_id: str | None = None
    line_id: str | None = None
    hours: float = 8.0

    @model_validator(mode="after")
    def validate_runs(self) -> "ShiftGenerateRequest":
        if not self.runs:
            raise ValueError("runs is required")
        return self


class SupplierRecordRequest(BaseModel):
    supplier_id: str
    delta_e: float
    product: str = ""
    passed: bool = True
    ts: str | None = None
    db_path: str | None = None


class StandardRegisterRequest(BaseModel):
    code: str
    lab: LabInput
    source: str = "manual"
    notes: str = ""
    db_path: str | None = None


class StandardCompareRequest(BaseModel):
    code: str
    measured_lab: LabInput
    version: int | None = None
    db_path: str | None = None


class SingleAnalyzeRequest(BaseModel):
    image: ImageInput
    profile: str = "auto"
    grid: str = "6x8"
    output_dir: str | None = None
    html_report: bool = True
    include_report: bool = False
    board_roi: ROIInput | None = None
    sample_roi: ROIInput | None = None
    board_quad: list[list[float]] | None = None
    sample_quad: list[list[float]] | None = None
    target_avg: float | None = None
    target_p95: float | None = None
    target_max: float | None = None
    use_aruco: bool = False
    aruco_dict: str = "DICT_4X4_50"
    aruco_ids: list[int] | None = None
    disable_shading_correction: bool = False
    with_process_advice: bool = True
    action_rules_config: str | None = None
    with_decision_center: bool = True
    decision_policy_config: str | None = None
    customer_id: str | None = None
    customer_tier: str | None = None
    customer_tier_config: str | None = None
    with_innovation_engine: bool = False
    innovation_context: dict[str, Any] | None = None
    history: HistoryConfig | None = None


class DualAnalyzeRequest(BaseModel):
    reference: ImageInput
    film: ImageInput
    profile: str = "auto"
    grid: str = "6x8"
    output_dir: str | None = None
    html_report: bool = True
    include_report: bool = False
    roi: ROIInput | None = None
    target_avg: float | None = None
    target_p95: float | None = None
    target_max: float | None = None
    disable_shading_correction: bool = False
    with_process_advice: bool = True
    action_rules_config: str | None = None
    with_decision_center: bool = True
    decision_policy_config: str | None = None
    customer_id: str | None = None
    customer_tier: str | None = None
    customer_tier_config: str | None = None
    with_innovation_engine: bool = False
    innovation_context: dict[str, Any] | None = None
    history: HistoryConfig | None = None


class BatchAnalyzeRequest(BaseModel):
    batch_dir: str | None = None
    image_paths: list[str] | None = None
    profile: str = "auto"
    grid: str = "6x8"
    output_dir: str | None = None
    html_report: bool = False
    include_rows: bool = False
    patterns: str = DEFAULT_GLOB
    recursive: bool = False
    board_roi: ROIInput | None = None
    sample_roi: ROIInput | None = None
    board_quad: list[list[float]] | None = None
    sample_quad: list[list[float]] | None = None
    target_avg: float | None = None
    target_p95: float | None = None
    target_max: float | None = None
    use_aruco: bool = False
    aruco_dict: str = "DICT_4X4_50"
    aruco_ids: list[int] | None = None
    disable_shading_correction: bool = False
    with_process_advice: bool = True
    action_rules_config: str | None = None
    with_decision_center: bool = True
    decision_policy_config: str | None = None
    customer_id: str | None = None
    customer_tier: str | None = None
    customer_tier_config: str | None = None
    with_innovation_engine: bool = False
    innovation_context: dict[str, Any] | None = None
    history: HistoryConfig | None = None

    @model_validator(mode="after")
    def validate_source(self) -> "BatchAnalyzeRequest":
        if not self.batch_dir and not self.image_paths:
            raise ValueError("Either batch_dir or image_paths is required")
        return self


class EnsembleAnalyzeRequest(BaseModel):
    ensemble_dir: str | None = None
    ensemble_images: list[str] | None = None
    profile: str = "auto"
    grid: str = "6x8"
    output_dir: str | None = None
    html_report: bool = True
    include_report: bool = False
    patterns: str = DEFAULT_GLOB
    recursive: bool = False
    min_count: int = 3
    board_roi: ROIInput | None = None
    sample_roi: ROIInput | None = None
    board_quad: list[list[float]] | None = None
    sample_quad: list[list[float]] | None = None
    target_avg: float | None = None
    target_p95: float | None = None
    target_max: float | None = None
    use_aruco: bool = False
    aruco_dict: str = "DICT_4X4_50"
    aruco_ids: list[int] | None = None
    disable_shading_correction: bool = False
    with_process_advice: bool = True
    action_rules_config: str | None = None
    with_decision_center: bool = True
    decision_policy_config: str | None = None
    customer_id: str | None = None
    customer_tier: str | None = None
    customer_tier_config: str | None = None
    with_innovation_engine: bool = False
    innovation_context: dict[str, Any] | None = None
    history: HistoryConfig | None = None

    @model_validator(mode="after")
    def validate_source(self) -> "EnsembleAnalyzeRequest":
        if not self.ensemble_dir and not self.ensemble_images:
            raise ValueError("Either ensemble_dir or ensemble_images is required")
        return self


def _load_image(source: ImageInput) -> np.ndarray:
    if source.path:
        p = Path(source.path)
        if not p.exists():
            raise HTTPException(status_code=400, detail=f"image not found: {source.path}")
        return read_image(p)
    if source.b64:
        return _decode_image_b64(source.b64)
    raise HTTPException(status_code=400, detail="image source is empty")


async def _upload_to_image_input(upload: UploadFile, field_name: str) -> ImageInput:
    payload = await upload.read()
    if not payload:
        raise HTTPException(status_code=400, detail=f"{field_name} upload is empty")
    if len(payload) > MAX_UPLOAD_BYTES:
        max_mb = MAX_UPLOAD_BYTES // (1024 * 1024)
        raise HTTPException(status_code=413, detail=f"{field_name} exceeds upload limit ({max_mb}MB)")
    return ImageInput(b64=base64.b64encode(payload).decode("ascii"))


app = FastAPI(
    title="SENIA Elite Color Matching",
    description="AI-Powered Color Quality Intelligence for Decorative Film Manufacturing",
    version=APP_VERSION,
)

# CORS: 允许公网浏览器访问 (手机/PC/任何域名)
try:
    from fastapi.middleware.cors import CORSMiddleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
except ImportError:
    pass  # CORS middleware not available


@app.middleware("http")
async def request_observability_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
    request_id = request.headers.get("x-request-id", "") or uuid4().hex[:12]
    request.state.request_id = request_id
    client_ip = _client_ip_from_request(request)
    method = request.method.upper()
    path = request.url.path
    start = time.perf_counter()
    blocked = _authorize_request(request, path=path, method=method, client_ip=client_ip)
    if blocked is not None:
        response: Response = blocked
    else:
        try:
            response = await call_next(request)
        except Exception as exc:  # noqa: BLE001
            response = JSONResponse(
                status_code=500,
                content={
                    "detail": "internal server error",
                    "request_id": request_id,
                    "path": path,
                },
            )
            _emit_alert(
                level="critical",
                key=f"middleware-unhandled::{path}",
                title="Unhandled exception in request pipeline",
                payload={
                    "request_id": request_id,
                    "method": method,
                    "path": path,
                    "client_ip": client_ip,
                    "error": str(exc),
                },
            )
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    response.headers["x-request-id"] = request_id
    response.headers["x-process-ms"] = f"{elapsed_ms:.2f}"
    response.headers["x-service-version"] = APP_VERSION
    response.headers["x-auth-role"] = str(getattr(request.state, "auth_role", "unknown"))
    response.headers[TENANT_HEADER_NAME] = str(getattr(request.state, "tenant_id", "n/a"))
    _apply_security_headers(response, path=path)
    status_code = int(response.status_code)
    _record_request_metrics(path=path, method=method, status_code=status_code, elapsed_ms=elapsed_ms, client_ip=client_ip)
    if path.startswith("/v1/") or status_code >= 400:
        _write_audit_event(
            {
                "time": _now_text(),
                "request_id": request_id,
                "method": method,
                "path": path,
                "query": _sanitize_query_string(request.url.query),
                "status_code": status_code,
                "elapsed_ms": round(elapsed_ms, 2),
                "client_ip": client_ip,
                "auth_role": getattr(request.state, "auth_role", "unknown"),
                "auth_key_id": getattr(request.state, "auth_key_id", None),
                "tenant_id": getattr(request.state, "tenant_id", None),
            }
        )
    if status_code >= 500:
        _emit_alert(
            level="critical",
            key=f"http500::{path}",
            title="HTTP 5xx detected",
            payload={
                "path": path,
                "method": method,
                "status_code": status_code,
                "tenant_id": getattr(request.state, "tenant_id", None),
                "request_id": request_id,
            },
        )
    elif status_code in {429, 503}:
        _emit_alert(
            level="warning",
            key=f"http-special::{status_code}::{path}",
            title="HTTP throttling or service config issue",
            payload={
                "path": path,
                "method": method,
                "status_code": status_code,
                "tenant_id": getattr(request.state, "tenant_id", None),
                "request_id": request_id,
            },
        )
    return response


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "version": APP_VERSION}


def _check_dir_writable(path: Path, probe_prefix: str) -> tuple[bool, str]:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / f"_{probe_prefix}_{uuid4().hex[:8]}.tmp"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True, str(path)
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def _build_readiness_payload() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def add_check(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    out_ok, out_detail = _check_dir_writable(DEFAULT_OUTPUT_ROOT, "ready_output")
    add_check("output_root_writable", out_ok, out_detail)

    hist_ok, hist_detail = _check_dir_writable(DEFAULT_HISTORY_DB.parent, "ready_history_parent")
    add_check("history_db_parent_writable", hist_ok, hist_detail)

    inv_ok, inv_detail = _check_dir_writable(DEFAULT_INNOVATION_DB.parent, "ready_innovation_parent")
    add_check("innovation_db_parent_writable", inv_ok, inv_detail)

    if SETTINGS.enable_audit_log:
        audit_ok, audit_detail = _check_dir_writable(AUDIT_LOG_PATH.parent, "ready_audit_parent")
        add_check("audit_log_parent_writable", audit_ok, audit_detail)
    else:
        add_check("audit_log_parent_writable", True, "disabled")

    if SETTINGS.enable_api_key_auth:
        add_check("api_key_auth_configured", len(API_KEY_ROLE_MAP) > 0, f"keys={len(API_KEY_ROLE_MAP)}")
    else:
        add_check("api_key_auth_configured", True, "disabled")

    if SETTINGS.enforce_tenant_header:
        add_check("tenant_allowlist_configured", len(ALLOWED_TENANTS) > 0, f"tenants={len(ALLOWED_TENANTS)}")
    else:
        add_check("tenant_allowlist_configured", True, "disabled")

    webhook = SETTINGS.alert_webhook_url.strip()
    add_check("alert_provider_valid", ALERT_PROVIDER in {"webhook", "wecom", "dingtalk"}, ALERT_PROVIDER)
    if webhook:
        ok = webhook.startswith("http://") or webhook.startswith("https://")
        add_check("alert_webhook_url_valid", ok, webhook)
        if ALERT_PROVIDER == "dingtalk":
            add_check("alert_dingtalk_secret_present", bool(SETTINGS.alert_dingtalk_secret.strip()), "required for dingtalk")
        else:
            add_check("alert_dingtalk_secret_present", True, "not required")
    else:
        add_check("alert_webhook_url_valid", True, "disabled")
        add_check("alert_dingtalk_secret_present", True, "disabled")

    dead_ok, dead_detail = _check_dir_writable(ALERT_DEAD_LETTER_PATH.parent, "ready_alert_dead")
    add_check("alert_dead_letter_parent_writable", dead_ok, dead_detail)

    ok = all(item["ok"] for item in checks)
    return {
        "ok": ok,
        "checked_at": _now_text(),
        "check_count": len(checks),
        "checks": checks,
    }


@app.get("/ready")
def ready() -> JSONResponse:
    payload = _build_readiness_payload()
    status_code = 200 if bool(payload.get("ok")) else 503
    return JSONResponse(status_code=status_code, content=payload)


@app.get("/v1/system/status")
def get_system_status() -> dict[str, Any]:
    uptime = max(0.0, time.time() - APP_START_TS)
    history_exists = DEFAULT_HISTORY_DB.exists()
    innovation_exists = DEFAULT_INNOVATION_DB.exists()
    metrics = _get_metrics_snapshot(top_n=8)
    return {
        "ok": True,
        "service": {
            "name": "Elite Color Match API",
            "version": app.version,
            "pid": os.getpid(),
            "started_at_unix": APP_START_TS,
            "uptime_sec": round(uptime, 2),
        },
        "runtime": {
            "api_host": SETTINGS.api_host,
            "api_port": SETTINGS.api_port,
            "log_level": SETTINGS.log_level,
            "acceptance_sync_ttl_sec": SETTINGS.acceptance_sync_ttl_sec,
            "upload_max_bytes": MAX_UPLOAD_BYTES,
            "audit_log_enabled": SETTINGS.enable_audit_log,
            "audit_rotate_max_mb": SETTINGS.audit_rotate_max_mb,
            "audit_rotate_backups": SETTINGS.audit_rotate_backups,
            "metrics_window_size": SETTINGS.metrics_window_size,
            "metrics_max_path_entries": SETTINGS.metrics_max_path_entries,
            "api_key_auth_enabled": SETTINGS.enable_api_key_auth,
            "auth_header_name": SETTINGS.auth_header_name,
            "rate_limit_rpm": SETTINGS.rate_limit_rpm,
            "tenant_enforced": SETTINGS.enforce_tenant_header,
            "tenant_header_name": TENANT_HEADER_NAME,
            "alert_webhook_enabled": bool(SETTINGS.alert_webhook_url.strip()),
            "alert_webhook_map_configured": bool((SETTINGS.alert_webhook_map_json or "").strip()),
            "alert_provider": ALERT_PROVIDER,
            "alert_min_level": ALERT_MIN_LEVEL,
            "alert_cooldown_sec": SETTINGS.alert_cooldown_sec,
            "alert_retry_count": SETTINGS.alert_retry_count,
            "alert_retry_backoff_ms": SETTINGS.alert_retry_backoff_ms,
            "alert_dead_letter_max_mb": SETTINGS.alert_dead_letter_max_mb,
            "alert_dead_letter_backups": SETTINGS.alert_dead_letter_backups,
            "enable_security_headers": SETTINGS.enable_security_headers,
            "ops_summary_cache_ttl_sec": SETTINGS.ops_summary_cache_ttl_sec,
        },
        "paths": {
            "root_dir": str(ROOT_DIR),
            "output_root": str(DEFAULT_OUTPUT_ROOT),
            "history_db_default": str(DEFAULT_HISTORY_DB),
            "innovation_db_default": str(DEFAULT_INNOVATION_DB),
            "innovation_doc": str(DEFAULT_INNOVATION_DOC),
            "audit_log_path": str(AUDIT_LOG_PATH),
            "alert_dead_letter_path": str(ALERT_DEAD_LETTER_PATH),
        },
        "storage": {
            "history_db_exists": history_exists,
            "history_db_bytes": DEFAULT_HISTORY_DB.stat().st_size if history_exists else 0,
            "innovation_db_exists": innovation_exists,
            "innovation_db_bytes": DEFAULT_INNOVATION_DB.stat().st_size if innovation_exists else 0,
            "audit_log_exists": AUDIT_LOG_PATH.exists(),
            "audit_log_bytes": AUDIT_LOG_PATH.stat().st_size if AUDIT_LOG_PATH.exists() else 0,
            "audit_log_backup_count": _count_existing_audit_backups(),
            "alert_dead_letter_exists": ALERT_DEAD_LETTER_PATH.exists(),
            "alert_dead_letter_bytes": ALERT_DEAD_LETTER_PATH.stat().st_size if ALERT_DEAD_LETTER_PATH.exists() else 0,
            "alert_dead_letter_backup_count": _count_alert_dead_letter_backups(),
        },
        "cache": {
            "acceptance_sync_cache_entries": len(ACCEPTANCE_SYNC_CACHE),
            "ops_summary_cache_entries": len(OPS_SUMMARY_CACHE),
        },
        "security": {
            "auth_active": API_KEY_AUTH_ENABLED,
            "configured_key_count": len(API_KEY_ROLE_MAP),
            "configured_roles": sorted({role for role in API_KEY_ROLE_MAP.values()}),
            "rate_limit_rpm": SETTINGS.rate_limit_rpm,
            "tenant_enforced": SETTINGS.enforce_tenant_header,
            "tenant_header_name": TENANT_HEADER_NAME,
            "allowed_tenant_count": len(ALLOWED_TENANTS),
            "allowed_tenants": sorted(ALLOWED_TENANTS)[:50],
        },
        "metrics_brief": metrics.get("totals", {}),
        "web": {
            "home": "/",
            "ready_endpoint": "/ready",
            "upload_endpoints": [
                "/v1/web/analyze/single-upload",
                "/v1/web/analyze/dual-upload",
            ],
            "report_view_endpoint": "/v1/report/html",
            "self_test_endpoint": "/v1/system/self-test",
            "metrics_endpoint": "/v1/system/metrics",
            "slo_endpoint": "/v1/system/slo",
            "auth_info_endpoint": "/v1/system/auth-info",
            "tenant_info_endpoint": "/v1/system/tenant-info",
            "alert_test_endpoint": "/v1/system/alert-test",
            "alert_dead_letter_endpoint": "/v1/system/alert-dead-letter",
            "alert_replay_endpoint": "/v1/system/alert-replay",
            "audit_endpoint": "/v1/system/audit-tail",
            "ops_summary_endpoint": "/v1/system/ops-summary",
            "executive_brief_endpoint": "/v1/system/executive-brief",
            "executive_weekly_card_endpoint": "/v1/system/executive-weekly-card",
            "cockpit_snapshot_endpoint": "/v1/system/cockpit-snapshot",
            "next_best_action_endpoint": "/v1/system/next-best-action",
            "release_gate_report_endpoint": "/v1/system/release-gate-report",
            "executive_dashboard": "/v1/web/executive-dashboard",
            "executive_brief_page": "/v1/web/executive-brief",
            "innovation_v3_dashboard": "/v1/web/innovation-v3",
            "precision_observatory_page": "/v1/web/precision-observatory",
            "precision_observatory_module_endpoint": "/v1/web/assets/observatory-module.js",
            "executive_export": "/v1/history/executive-export",
        },
        "routes": {
            "count": len(app.routes),
        },
    }


@app.get("/v1/system/metrics")
def get_system_metrics(top_n: int = 30) -> dict[str, Any]:
    return {"ok": True, **_get_metrics_snapshot(top_n=max(1, min(int(top_n), 200)))}


def _is_analysis_path(path: str) -> bool:
    return path.startswith("/v1/analyze/") or path.startswith("/v1/web/analyze/")


def _collect_recent_latency_samples(limit: int = 12000, include_analysis_paths: bool = False) -> list[float]:
    values: list[float] = []
    with METRICS_LOCK:
        for path, stat in REQUEST_PATH_STATS.items():
            if not include_analysis_paths and _is_analysis_path(path):
                continue
            recent = stat.get("recent_ms")
            if not isinstance(recent, deque):
                continue
            for v in recent:
                if isinstance(v, (int, float)):
                    values.append(float(v))
    if len(values) > limit:
        values = values[-limit:]
    return values


@app.get("/v1/system/slo")
def get_system_slo(
    availability_target_pct: float = 99.5,
    latency_p95_target_ms: float = 1200.0,
    include_analysis_paths: bool = False,
) -> dict[str, Any]:
    target_availability = max(90.0, min(99.999, float(availability_target_pct)))
    target_p95 = max(50.0, min(30000.0, float(latency_p95_target_ms)))
    metrics = _get_metrics_snapshot(top_n=20)
    totals = metrics.get("totals", {}) if isinstance(metrics, dict) else {}
    error_ratio = float(totals.get("error_ratio", 0.0))
    availability = round(100.0 - (error_ratio * 100.0), 4)
    latency_samples = _collect_recent_latency_samples(
        limit=12000,
        include_analysis_paths=bool(include_analysis_paths),
    )
    p95 = _percentile(latency_samples, 95)
    p99 = _percentile(latency_samples, 99)
    p50 = _percentile(latency_samples, 50)

    error_budget = max(0.001, 100.0 - target_availability)
    consumed_pct = round(min(100.0, max(0.0, ((100.0 - availability) / error_budget) * 100.0)), 2)

    status = "healthy"
    reasons: list[str] = []
    if availability < target_availability:
        status = "critical"
        reasons.append("availability below target")
    if p95 is not None and p95 > (target_p95 * 1.5):
        status = "critical"
        reasons.append("p95 latency far above target")
    if status != "critical":
        if availability < (target_availability - (error_budget * 0.4)):
            status = "warning"
            reasons.append("availability approaching limit")
        if p95 is not None and p95 > target_p95:
            status = "warning"
            reasons.append("p95 latency above target")
        if consumed_pct >= 80.0:
            status = "warning"
            reasons.append("error budget consumption above 80%")
    if not reasons:
        reasons.append("within target")

    recommendations: list[str] = []
    if status == "critical":
        recommendations.append("Enable stricter release gate and block risky deployments.")
        recommendations.append("Increase operator review sampling and inspect top error paths immediately.")
    elif status == "warning":
        recommendations.append("Track top latency paths and optimize slow endpoints this sprint.")
        recommendations.append("Schedule a targeted reliability burn-down before peak load.")
    else:
        recommendations.append("Maintain current guardrails and continue daily release gate checks.")

    return {
        "ok": True,
        "generated_at": _now_text(),
        "status": status,
        "status_reasons": reasons,
        "targets": {
            "availability_pct": target_availability,
            "latency_p95_ms": target_p95,
            "include_analysis_paths": bool(include_analysis_paths),
        },
        "observed": {
            "availability_pct": availability,
            "error_ratio": round(error_ratio, 6),
            "latency_p50_ms": p50,
            "latency_p95_ms": p95,
            "latency_p99_ms": p99,
            "sample_count": len(latency_samples),
            "recent_requests_per_min": totals.get("recent_requests_per_min"),
        },
        "error_budget": {
            "budget_pct": round(error_budget, 4),
            "consumed_pct": consumed_pct,
            "remaining_pct": round(max(0.0, 100.0 - consumed_pct), 2),
        },
        "recommendations": recommendations,
        "top_paths": metrics.get("top_paths", []),
    }


@app.get("/v1/system/auth-info")
def get_system_auth_info(request: Request) -> dict[str, Any]:
    return {
        "ok": True,
        "auth_enabled": SETTINGS.enable_api_key_auth,
        "auth_active": API_KEY_AUTH_ENABLED,
        "auth_header_name": SETTINGS.auth_header_name,
        "configured_key_count": len(API_KEY_ROLE_MAP),
        "configured_roles": sorted({role for role in API_KEY_ROLE_MAP.values()}),
        "rate_limit_rpm": SETTINGS.rate_limit_rpm,
        "alert_provider": ALERT_PROVIDER,
        "alert_webhook_map_configured": bool((SETTINGS.alert_webhook_map_json or "").strip()),
        "alert_dead_letter_path": str(ALERT_DEAD_LETTER_PATH),
        "current_role": getattr(request.state, "auth_role", "unknown"),
        "tenant_id": getattr(request.state, "tenant_id", None),
        "tenant_header_name": TENANT_HEADER_NAME,
        "tenant_enforced": SETTINGS.enforce_tenant_header,
        "allowed_tenant_count": len(ALLOWED_TENANTS),
    }


@app.get("/v1/system/tenant-info")
def get_system_tenant_info(request: Request) -> dict[str, Any]:
    return {
        "ok": True,
        "tenant_header_name": TENANT_HEADER_NAME,
        "tenant_enforced": SETTINGS.enforce_tenant_header,
        "allowed_tenant_count": len(ALLOWED_TENANTS),
        "allowed_tenants": sorted(ALLOWED_TENANTS)[:200],
        "current_tenant": getattr(request.state, "tenant_id", None),
    }


@app.post("/v1/system/alert-test")
def post_system_alert_test(
    request: Request,
    level: str = "warning",
    title: str = "Manual alert test",
    message: str = "health ping",
) -> dict[str, Any]:
    safe_level = level.strip().lower()
    if safe_level not in ALERT_LEVEL_RANK:
        safe_level = "warning"
    sent = _emit_alert(
        level=safe_level,
        key=f"manual-alert::{safe_level}",
        title=title.strip() or "Manual alert test",
        payload={
            "message": message.strip() or "health ping",
            "tenant_id": getattr(request.state, "tenant_id", None),
            "auth_role": getattr(request.state, "auth_role", None),
        },
    )
    return {
        "ok": True,
        "sent": sent,
        "level": safe_level,
        "title": title,
        "webhook_enabled": bool(SETTINGS.alert_webhook_url.strip()),
        "provider": ALERT_PROVIDER,
    }


def _replay_alert_dead_letter_entry(entry: dict[str, Any]) -> bool:
    body = entry.get("body")
    if not isinstance(body, dict):
        return False
    level = str(body.get("level", "warning")).strip().lower()
    if level not in ALERT_LEVEL_RANK:
        level = "warning"
    title = str(body.get("title", "replay")).strip() or "replay"
    payload = body.get("payload")
    if not isinstance(payload, dict):
        payload = {"raw_payload": payload}
    return _emit_alert(
        level=level,
        key=f"dead-letter-replay::{uuid4().hex[:10]}",
        title=title,
        payload=payload,
    )


@app.get("/v1/system/alert-dead-letter")
def get_system_alert_dead_letter(limit: int = 120) -> dict[str, Any]:
    rows = _read_alert_dead_letter_rows(limit=max(1, min(int(limit), 500)))
    return {
        "ok": True,
        "enabled": True,
        "path": str(ALERT_DEAD_LETTER_PATH),
        "count": len(rows),
        "backup_count": _count_alert_dead_letter_backups(),
        "rows": rows,
    }


@app.post("/v1/system/alert-replay")
def post_system_alert_replay(limit: int = 20, prune_on_success: bool = True) -> dict[str, Any]:
    rows_all = _read_all_alert_dead_letter_rows()
    if not rows_all:
        return {
            "ok": True,
            "path": str(ALERT_DEAD_LETTER_PATH),
            "replay_count": 0,
            "replayed_success": 0,
            "replayed_failed": 0,
            "remaining_count": 0,
        }

    safe_limit = max(1, min(int(limit), 200))
    start_idx = max(0, len(rows_all) - safe_limit)
    target_indexes = list(range(start_idx, len(rows_all)))
    success_indexes: set[int] = set()
    replayed_success = 0
    replayed_failed = 0

    for idx in target_indexes:
        row = rows_all[idx]
        sent = _replay_alert_dead_letter_entry(row)
        if sent:
            replayed_success += 1
            if prune_on_success:
                success_indexes.add(idx)
        else:
            replayed_failed += 1

    if prune_on_success and success_indexes:
        remained = [row for i, row in enumerate(rows_all) if i not in success_indexes]
        _rewrite_alert_dead_letter_rows(remained)
        remaining_count = len(remained)
    else:
        remaining_count = len(rows_all)

    return {
        "ok": True,
        "path": str(ALERT_DEAD_LETTER_PATH),
        "replay_count": len(target_indexes),
        "replayed_success": replayed_success,
        "replayed_failed": replayed_failed,
        "prune_on_success": bool(prune_on_success),
        "remaining_count": remaining_count,
    }


def _build_ops_summary_cache_key(
    tenant_id: str | None,
    db_path: Path,
    line_id: str | None,
    product_code: str | None,
    lot_id: str | None,
    window: int,
    audit_limit: int,
) -> str:
    payload = {
        "tenant_id": tenant_id or "",
        "db_path": str(db_path),
        "line_id": line_id or "",
        "product_code": product_code or "",
        "lot_id": lot_id or "",
        "window": int(window),
        "audit_limit": int(audit_limit),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _get_cached_ops_summary(cache_key: str) -> dict[str, Any] | None:
    ttl = max(0, int(SETTINGS.ops_summary_cache_ttl_sec))
    if ttl <= 0:
        return None
    now_ts = time.time()
    with OPS_SUMMARY_CACHE_LOCK:
        hit = OPS_SUMMARY_CACHE.get(cache_key)
        if hit is None:
            return None
        cached_ts = float(hit.get("cached_ts", 0.0))
        if (now_ts - cached_ts) > ttl:
            OPS_SUMMARY_CACHE.pop(cache_key, None)
            return None
        payload = hit.get("payload")
        if isinstance(payload, dict):
            cloned = deepcopy(payload)
            cloned["cache"] = {
                "enabled": True,
                "hit": True,
                "ttl_sec": ttl,
                "age_sec": round(max(0.0, now_ts - cached_ts), 2),
            }
            return cloned
    return None


def _put_cached_ops_summary(cache_key: str, payload: dict[str, Any]) -> None:
    ttl = max(0, int(SETTINGS.ops_summary_cache_ttl_sec))
    if ttl <= 0:
        return
    now_ts = time.time()
    with OPS_SUMMARY_CACHE_LOCK:
        OPS_SUMMARY_CACHE[cache_key] = {
            "cached_ts": now_ts,
            "payload": deepcopy(payload),
        }
        if len(OPS_SUMMARY_CACHE) > 300:
            sorted_items = sorted(
                OPS_SUMMARY_CACHE.items(),
                key=lambda kv: float(kv[1].get("cached_ts", 0.0)),
            )
            for old_key, _ in sorted_items[:100]:
                OPS_SUMMARY_CACHE.pop(old_key, None)


def _invalidate_ops_summary_cache() -> None:
    with OPS_SUMMARY_CACHE_LOCK:
        OPS_SUMMARY_CACHE.clear()


@app.get("/v1/system/ops-summary")
def get_system_ops_summary(
    request: Request,
    db_path: str | None = None,
    line_id: str | None = None,
    product_code: str | None = None,
    lot_id: str | None = None,
    window: int = 200,
    audit_limit: int = 50,
) -> dict[str, Any]:
    safe_window = max(1, int(window))
    safe_audit_limit = max(1, min(int(audit_limit), 200))
    tenant_id = getattr(request.state, "tenant_id", None)
    resolved_db = Path(db_path) if db_path else DEFAULT_HISTORY_DB
    cache_key = _build_ops_summary_cache_key(
        tenant_id=tenant_id,
        db_path=resolved_db,
        line_id=line_id,
        product_code=product_code,
        lot_id=lot_id,
        window=safe_window,
        audit_limit=safe_audit_limit,
    )
    cached = _get_cached_ops_summary(cache_key)
    if cached is not None:
        return cached

    result: dict[str, Any] = {
        "ok": True,
        "generated_at": _now_text(),
        "tenant_id": tenant_id,
        "status": get_system_status(),
        "metrics": _get_metrics_snapshot(top_n=12),
        "auth": get_system_auth_info(request),
        "tenant": get_system_tenant_info(request),
        "audit_tail": get_system_audit_tail(limit=safe_audit_limit),
        "cache": {
            "enabled": max(0, int(SETTINGS.ops_summary_cache_ttl_sec)) > 0,
            "hit": False,
            "ttl_sec": max(0, int(SETTINGS.ops_summary_cache_ttl_sec)),
            "age_sec": 0.0,
        },
    }

    if resolved_db.exists():
        result["history"] = {
            "db_path": str(resolved_db),
            "executive": executive_kpis(
                db_path=resolved_db,
                line_id=line_id,
                product_code=product_code,
                lot_id=lot_id,
                window=safe_window,
            ),
            "early_warning": complaint_early_warning(
                db_path=resolved_db,
                line_id=line_id,
                product_code=product_code,
                lot_id=lot_id,
                window=max(20, safe_window),
            ),
            "outcome_kpis": outcome_kpis(
                db_path=resolved_db,
                line_id=line_id,
                product_code=product_code,
                lot_id=lot_id,
                window=max(20, safe_window),
            ),
        }
    else:
        result["history"] = {"db_path": str(resolved_db), "available": False}
    _put_cached_ops_summary(cache_key, result)
    return result


def _resolve_project_json_path(path_text: str) -> Path:
    raw = path_text.strip()
    if not raw:
        raise HTTPException(status_code=400, detail="path is required")
    candidate = Path(raw).expanduser()
    resolved = (ROOT_DIR / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
    if resolved.suffix.lower() != ".json":
        raise HTTPException(status_code=400, detail="only .json file is supported")
    try:
        resolved.relative_to(ROOT_DIR)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="json path must be inside project root") from exc
    return resolved


def _build_release_gate_report_payload(path: str | None = None) -> dict[str, Any]:
    report_path = (
        _resolve_project_json_path(path)
        if path
        else (ROOT_DIR / "out_e2e_flow" / "release_gate_result.json").resolve()
    )
    if not report_path.exists() or not report_path.is_file():
        return {"ok": True, "available": False, "path": str(report_path), "report": None}
    text = report_path.read_text(encoding="utf-8", errors="replace")
    try:
        payload = json.loads(text)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": True,
            "available": False,
            "path": str(report_path),
            "report": None,
            "parse_error": str(exc),
        }
    return {"ok": True, "available": True, "path": str(report_path), "report": payload}


@app.get("/v1/system/release-gate-report", response_model=None)
def get_system_release_gate_report(path: str | None = None) -> JSONResponse:
    payload = _build_release_gate_report_payload(path=path)
    return JSONResponse(content=_json_safe(payload))


def _clamp_score(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _json_safe(value: Any) -> Any:
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, tuple):
        return [_json_safe(v) for v in value]
    return value


def _score_to_grade(score: float) -> str:
    if score >= 90:
        return "A"
    if score >= 75:
        return "B"
    if score >= 60:
        return "C"
    return "D"


@app.get("/v1/system/executive-brief", response_model=None)
def get_system_executive_brief(
    request: Request,
    db_path: str | None = None,
    line_id: str | None = None,
    product_code: str | None = None,
    lot_id: str | None = None,
    window: int = 200,
) -> JSONResponse:
    ready_payload = _build_readiness_payload()
    slo_payload = get_system_slo()
    release_payload = _build_release_gate_report_payload()
    metrics = _get_metrics_snapshot(top_n=8)
    totals = metrics.get("totals", {}) if isinstance(metrics, dict) else {}

    history: dict[str, Any] = {"available": False}
    resolved_db = Path(db_path) if db_path else DEFAULT_HISTORY_DB
    if resolved_db.exists():
        safe_window = max(20, int(window))
        exec_payload = executive_kpis(
            db_path=resolved_db,
            line_id=line_id,
            product_code=product_code,
            lot_id=lot_id,
            window=safe_window,
        )
        early = complaint_early_warning(
            db_path=resolved_db,
            line_id=line_id,
            product_code=product_code,
            lot_id=lot_id,
            window=max(40, safe_window),
        )
        outcomes = outcome_kpis(
            db_path=resolved_db,
            line_id=line_id,
            product_code=product_code,
            lot_id=lot_id,
            window=max(40, safe_window),
        )
        history = {
            "available": True,
            "db_path": str(resolved_db),
            "executive": exec_payload,
            "early_warning": early,
            "outcome_kpis": outcomes,
        }

    score = 100.0
    reasons: list[str] = []
    recommendations: list[str] = []

    if not bool(ready_payload.get("ok")):
        score -= 40.0
        reasons.append("readiness failed")
        recommendations.append("Stop release and fix readiness checks first.")
    else:
        reasons.append("readiness passed")

    slo_status = str(slo_payload.get("status", "unknown")).lower()
    if slo_status == "critical":
        score -= 35.0
        reasons.append("SLO critical")
        recommendations.append("Freeze release and run incident handling on latency/error spikes.")
    elif slo_status == "warning":
        score -= 18.0
        reasons.append("SLO warning")
        recommendations.append("Reduce risk by tightening release gate and watch top slow paths.")
    elif slo_status == "healthy":
        reasons.append("SLO healthy")

    report_obj = release_payload.get("report") if isinstance(release_payload, dict) else None
    release_ok = bool(isinstance(report_obj, dict) and report_obj.get("ok"))
    if release_payload.get("available") and not release_ok:
        score -= 30.0
        reasons.append("release gate failed")
        recommendations.append("Block production rollout until release gate is green.")
    elif release_payload.get("available"):
        reasons.append("release gate passed")
    else:
        score -= 8.0
        reasons.append("release gate report unavailable")
        recommendations.append("Run release gate before production rollout.")

    if history.get("available"):
        early = history.get("early_warning", {})
        outcomes = history.get("outcome_kpis", {})
        risk_level = str(early.get("risk_level", "green")).lower()
        complaint_rate = float(outcomes.get("complaint_rate", 0.0) or 0.0)
        if risk_level == "red":
            score -= 30.0
            reasons.append("customer complaint risk red")
            recommendations.append("Escalate quality war room and switch to strict policy immediately.")
        elif risk_level == "orange":
            score -= 20.0
            reasons.append("customer complaint risk orange")
            recommendations.append("Increase manual review sampling for next 72 hours.")
        elif risk_level == "yellow":
            score -= 10.0
            reasons.append("customer complaint risk yellow")
            recommendations.append("Watch drift trend and pre-adjust process parameters.")
        else:
            reasons.append("customer complaint risk green")
        if complaint_rate > 0.15:
            score -= 15.0
            reasons.append("complaint rate high")
            recommendations.append("Prioritize VIP threshold strategy and tighten release criteria.")
        elif complaint_rate > 0.08:
            score -= 8.0
            reasons.append("complaint rate elevated")
    else:
        score -= 5.0
        reasons.append("history data unavailable")
        recommendations.append("Enable history DB tracking to improve decision confidence.")

    final_score = round(_clamp_score(score), 2)
    grade = _score_to_grade(final_score)
    go_live = bool(
        ready_payload.get("ok")
        and slo_status != "critical"
        and (not release_payload.get("available") or release_ok)
    )
    if not recommendations:
        recommendations.append("Maintain current operation strategy and keep release gate daily.")

    payload = {
        "ok": True,
        "generated_at": _now_text(),
        "tenant_id": getattr(request.state, "tenant_id", None),
        "decision": {
            "go_live_recommended": go_live,
            "grade": grade,
            "score_0_100": final_score,
            "summary": "GO" if go_live else "NO_GO",
        },
        "signals": {
            "readiness_ok": bool(ready_payload.get("ok")),
            "slo_status": slo_status,
            "release_gate_available": bool(release_payload.get("available")),
            "release_gate_ok": release_ok if release_payload.get("available") else None,
            "recent_requests_per_min": totals.get("recent_requests_per_min"),
            "recent_error_ratio": totals.get("error_ratio"),
        },
        "reasons": reasons,
        "recommendations": recommendations[:8],
        "status_ref": {
            "ready": ready_payload,
            "slo": slo_payload,
            "release_gate": release_payload,
            "history": history,
        },
    }
    return JSONResponse(content=_json_safe(payload))


def _build_executive_weekly_card_payload(
    request: Request,
    db_path: str | None = None,
    line_id: str | None = None,
    product_code: str | None = None,
    lot_id: str | None = None,
    window: int = 500,
) -> dict[str, Any]:
    safe_window = max(40, int(window))
    resolved_db = Path(db_path) if db_path else DEFAULT_HISTORY_DB
    history_available = resolved_db.exists()

    exec_payload: dict[str, Any] = {}
    early_payload: dict[str, Any] = {}
    outcome_payload: dict[str, Any] = {}
    policy_payload: dict[str, Any] = {}
    if history_available:
        exec_payload = executive_kpis(
            db_path=resolved_db,
            line_id=line_id,
            product_code=product_code,
            lot_id=lot_id,
            window=safe_window,
        )
        early_payload = complaint_early_warning(
            db_path=resolved_db,
            line_id=line_id,
            product_code=product_code,
            lot_id=lot_id,
            window=safe_window,
        )
        outcome_payload = outcome_kpis(
            db_path=resolved_db,
            line_id=line_id,
            product_code=product_code,
            lot_id=lot_id,
            window=safe_window,
        )
        policy_payload = recommend_policy_adjustments(
            db_path=resolved_db,
            line_id=line_id,
            product_code=product_code,
            lot_id=lot_id,
            window=safe_window,
        )

    auto_release_rate = float(exec_payload.get("auto_release_rate", 0.0) or 0.0)
    manual_review_rate = float(exec_payload.get("manual_review_rate", 0.0) or 0.0)
    recapture_rate = float(exec_payload.get("recapture_rate", 0.0) or 0.0)
    hold_rate = float(exec_payload.get("hold_rate", 0.0) or 0.0)
    complaint_rate = float(outcome_payload.get("complaint_rate", 0.0) or 0.0)
    rework_rate = float(outcome_payload.get("rework_rate", 0.0) or 0.0)
    escape_rate = float(outcome_payload.get("escape_rate", 0.0) or 0.0)
    risk_index = float(early_payload.get("risk_index_0_100", 50.0) or 50.0)

    quality_penalty = risk_index * 0.50 + complaint_rate * 220.0 + rework_rate * 120.0 + escape_rate * 140.0
    efficiency_bonus = auto_release_rate * 30.0
    recapture_penalty = recapture_rate * 40.0 + hold_rate * 60.0 + manual_review_rate * 20.0
    score = _clamp_score(100.0 - quality_penalty - recapture_penalty + efficiency_bonus)
    score = round(float(score), 2)
    grade = _score_to_grade(score)
    go_live = bool(score >= 72.0 and risk_index < 70.0)

    weekly_volume_est = max(int(exec_payload.get("count", 0) or 0), 300)
    annual_volume_est = weekly_volume_est * 52
    manual_saving = max(0.18 - manual_review_rate, 0.0) * annual_volume_est * 6.0
    complaint_saving = max(0.06 - complaint_rate, 0.0) * annual_volume_est * 280.0
    rework_saving = max(0.10 - rework_rate, 0.0) * annual_volume_est * 90.0
    annual_saving_cny = round(max(0.0, manual_saving + complaint_saving + rework_saving), 2)

    recs: list[str] = []
    for src in (
        early_payload.get("recommendations", []),
        policy_payload.get("recommendations", []),
    ):
        if isinstance(src, list):
            for item in src:
                txt = str(item).strip()
                if txt and txt not in recs:
                    recs.append(txt)
    if not recs:
        recs.append("Keep current policy and monitor risk trend daily.")

    return {
        "ok": True,
        "generated_at": _now_text(),
        "tenant_id": getattr(request.state, "tenant_id", None),
        "scope": {
            "db_path": str(resolved_db),
            "line_id": line_id,
            "product_code": product_code,
            "lot_id": lot_id,
            "window": safe_window,
            "history_available": history_available,
        },
        "decision": {
            "go_live_recommended": go_live,
            "summary": "GO" if go_live else "NO_GO",
            "grade": grade,
            "score_0_100": score,
        },
        "risk": {
            "risk_index_0_100": round(risk_index, 2),
            "warning_level": early_payload.get("warning_level"),
            "complaint_rate": round(complaint_rate, 5),
            "escape_rate": round(escape_rate, 5),
            "rework_rate": round(rework_rate, 5),
        },
        "operations": {
            "auto_release_rate": round(auto_release_rate, 5),
            "manual_review_rate": round(manual_review_rate, 5),
            "recapture_rate": round(recapture_rate, 5),
            "hold_rate": round(hold_rate, 5),
            "customer_acceptance_index": exec_payload.get("customer_acceptance_index"),
            "boss_efficiency_index": exec_payload.get("boss_efficiency_index"),
            "company_governance_index": exec_payload.get("company_governance_index"),
        },
        "roi": {
            "annual_saving_cny": annual_saving_cny,
            "weekly_volume_est": weekly_volume_est,
            "annual_volume_est": annual_volume_est,
            "drivers": {
                "manual_review_optimized_cny": round(manual_saving, 2),
                "complaint_avoided_cny": round(complaint_saving, 2),
                "rework_avoided_cny": round(rework_saving, 2),
            },
            "assumptions": {
                "manual_review_cost_per_order_cny": 6.0,
                "complaint_cost_per_order_cny": 280.0,
                "rework_cost_per_order_cny": 90.0,
                "baseline_manual_review_rate": 0.18,
                "baseline_complaint_rate": 0.06,
                "baseline_rework_rate": 0.10,
            },
        },
        "recommendations": recs[:8],
        "raw": {
            "executive": exec_payload,
            "early_warning": early_payload,
            "outcome_kpis": outcome_payload,
            "policy": policy_payload,
        },
    }


@app.get("/v1/system/executive-weekly-card", response_model=None)
def get_system_executive_weekly_card(
    request: Request,
    db_path: str | None = None,
    line_id: str | None = None,
    product_code: str | None = None,
    lot_id: str | None = None,
    window: int = 500,
) -> JSONResponse:
    payload = _build_executive_weekly_card_payload(
        request=request,
        db_path=db_path,
        line_id=line_id,
        product_code=product_code,
        lot_id=lot_id,
        window=window,
    )
    return JSONResponse(content=_json_safe(payload))


def _build_cockpit_snapshot_payload(
    request: Request,
    db_path: str | None = None,
    line_id: str | None = None,
    product_code: str | None = None,
    lot_id: str | None = None,
    window: int = 200,
    weekly_window: int = 500,
    audit_limit: int = 20,
) -> dict[str, Any]:
    safe_window = max(40, int(window))
    safe_weekly_window = max(safe_window, int(weekly_window))
    safe_audit_limit = max(1, min(int(audit_limit), 200))

    ops_payload = get_system_ops_summary(
        request=request,
        db_path=db_path,
        line_id=line_id,
        product_code=product_code,
        lot_id=lot_id,
        window=safe_window,
        audit_limit=safe_audit_limit,
    )
    weekly_payload = _build_executive_weekly_card_payload(
        request=request,
        db_path=db_path,
        line_id=line_id,
        product_code=product_code,
        lot_id=lot_id,
        window=safe_weekly_window,
    )

    history = ops_payload.get("history")
    history_dict = history if isinstance(history, dict) else {}
    executive = history_dict.get("executive")
    executive_dict = executive if isinstance(executive, dict) else {}
    outcome = history_dict.get("outcome_kpis")
    outcome_dict = outcome if isinstance(outcome, dict) else {}
    early = history_dict.get("early_warning")
    early_dict = early if isinstance(early, dict) else {}

    metrics = ops_payload.get("metrics")
    metrics_dict = metrics if isinstance(metrics, dict) else {}
    totals = metrics_dict.get("totals")
    totals_dict = totals if isinstance(totals, dict) else {}

    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            number = float(value)
            return number if math.isfinite(number) else default
        except (TypeError, ValueError):
            return default

    auto_release_rate = _safe_float(executive_dict.get("auto_release_rate"), 0.0)
    escape_rate = _safe_float(outcome_dict.get("escape_rate"), 0.0)
    complaint_rate = _safe_float(outcome_dict.get("complaint_rate"), 0.0)
    risk_index = _safe_float(early_dict.get("risk_index_0_100"), 50.0)

    latency_p95 = _safe_float(totals_dict.get("latency_p95_ms"), float("nan"))
    if not math.isfinite(latency_p95):
        latency_p95 = _safe_float(totals_dict.get("latency_avg_ms"), 0.0)

    scope = weekly_payload.get("scope")
    scope_dict = scope if isinstance(scope, dict) else {}
    decision = weekly_payload.get("decision")
    decision_dict = decision if isinstance(decision, dict) else {}
    roi = weekly_payload.get("roi")
    roi_dict = roi if isinstance(roi, dict) else {}

    cache = ops_payload.get("cache")
    cache_dict = cache if isinstance(cache, dict) else {}

    return {
        "ok": True,
        "generated_at": _now_text(),
        "tenant_id": getattr(request.state, "tenant_id", None),
        "scope": {
            "db_path": scope_dict.get("db_path"),
            "line_id": scope_dict.get("line_id"),
            "product_code": scope_dict.get("product_code"),
            "lot_id": scope_dict.get("lot_id"),
            "window": safe_window,
            "weekly_window": safe_weekly_window,
            "history_available": bool(scope_dict.get("history_available", False)),
        },
        "cockpit": {
            "sample_count": int(executive_dict.get("count", 0) or 0),
            "auto_release_rate": round(auto_release_rate, 5),
            "alert_recall_rate": round(max(0.0, min(1.0, 1.0 - max(0.0, escape_rate))), 5),
            "complaint_rate": round(complaint_rate, 5),
            "risk_index_0_100": round(risk_index, 2),
            "warning_level": early_dict.get("warning_level"),
            "latency_p95_ms": round(latency_p95, 2),
            "recent_requests_per_min": _safe_float(totals_dict.get("recent_requests_per_min"), 0.0),
            "error_ratio": round(_safe_float(totals_dict.get("error_ratio"), 0.0), 5),
            "decision_summary": decision_dict.get("summary"),
            "decision_grade": decision_dict.get("grade"),
            "decision_score_0_100": decision_dict.get("score_0_100"),
            "go_live_recommended": bool(decision_dict.get("go_live_recommended", False)),
            "annual_saving_cny": roi_dict.get("annual_saving_cny"),
        },
        "history": history_dict,
        "metrics": metrics_dict,
        "status": ops_payload.get("status"),
        "weekly_card": weekly_payload,
        "cache": {
            "ops_summary": cache_dict,
            "ops_summary_hit": bool(cache_dict.get("hit")),
        },
    }


@app.get("/v1/system/cockpit-snapshot", response_model=None)
def get_system_cockpit_snapshot(
    request: Request,
    db_path: str | None = None,
    line_id: str | None = None,
    product_code: str | None = None,
    lot_id: str | None = None,
    window: int = 200,
    weekly_window: int = 500,
    audit_limit: int = 20,
) -> JSONResponse:
    payload = _build_cockpit_snapshot_payload(
        request=request,
        db_path=db_path,
        line_id=line_id,
        product_code=product_code,
        lot_id=lot_id,
        window=window,
        weekly_window=weekly_window,
        audit_limit=audit_limit,
    )
    return JSONResponse(content=_json_safe(payload))


def _build_next_best_action_payload(
    request: Request,
    db_path: str | None = None,
    line_id: str | None = None,
    product_code: str | None = None,
    lot_id: str | None = None,
    window: int = 200,
    weekly_window: int = 500,
    ui_role: str | None = None,
) -> dict[str, Any]:
    snapshot = _build_cockpit_snapshot_payload(
        request=request,
        db_path=db_path,
        line_id=line_id,
        product_code=product_code,
        lot_id=lot_id,
        window=window,
        weekly_window=weekly_window,
        audit_limit=20,
    )

    cockpit = snapshot.get("cockpit")
    cockpit_dict = cockpit if isinstance(cockpit, dict) else {}
    weekly = snapshot.get("weekly_card")
    weekly_dict = weekly if isinstance(weekly, dict) else {}
    weekly_decision = weekly_dict.get("decision")
    weekly_decision_dict = weekly_decision if isinstance(weekly_decision, dict) else {}
    risk = weekly_dict.get("risk")
    risk_dict = risk if isinstance(risk, dict) else {}

    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            number = float(value)
            return number if math.isfinite(number) else default
        except (TypeError, ValueError):
            return default

    warning_level = str(cockpit_dict.get("warning_level") or risk_dict.get("warning_level") or "").strip().lower()
    risk_index = _safe_float(cockpit_dict.get("risk_index_0_100"), 50.0)
    complaint_rate = _safe_float(cockpit_dict.get("complaint_rate"), 0.0)
    auto_release_rate = _safe_float(cockpit_dict.get("auto_release_rate"), 0.0)
    latency_p95 = _safe_float(cockpit_dict.get("latency_p95_ms"), 0.0)
    error_ratio = _safe_float(cockpit_dict.get("error_ratio"), 0.0)
    weekly_score = _safe_float(weekly_decision_dict.get("score_0_100"), _safe_float(cockpit_dict.get("decision_score_0_100"), 50.0))
    go_live = bool(cockpit_dict.get("go_live_recommended", False))

    action_code = "RUN_OPS_CHECK"
    confidence = 0.78
    reasons: list[str] = []
    sequence: list[str] = []

    severe_warning = warning_level in {"red", "critical"}
    elevated_warning = warning_level in {"orange", "high", "elevated"}
    executive_view = str(ui_role or "").strip().lower() == "executive"

    if severe_warning or risk_index >= 82.0 or complaint_rate >= 0.12:
        action_code = "HOLD_AND_ESCALATE"
        confidence = 0.95
        reasons = [
            f"Risk index {risk_index:.1f}/100 is in critical range",
            f"Warning level is {warning_level or 'critical'}",
            "Immediate cross-team quality escalation is recommended",
        ]
        sequence = ["RUN_OPS_CHECK", "DEEP_INNOVATION_REVIEW", "EXECUTIVE_WEEKLY_CARD"]
    elif elevated_warning or risk_index >= 68.0:
        if auto_release_rate < 0.78:
            action_code = "DEEP_INNOVATION_REVIEW"
            confidence = 0.87
            reasons = [
                f"Risk index {risk_index:.1f}/100 indicates elevated drift risk",
                f"Auto release rate {auto_release_rate:.2%} is below target",
                "Need root-cause and correction strategy before scale-out",
            ]
            sequence = ["DEEP_INNOVATION_REVIEW", "RUN_OPS_CHECK", "EXECUTIVE_WEEKLY_CARD"]
        else:
            action_code = "RUN_OPS_CHECK"
            confidence = 0.81
            reasons = [
                f"Risk index {risk_index:.1f}/100 is elevated",
                "Current automation is still acceptable; monitor with tighter window",
            ]
            sequence = ["RUN_OPS_CHECK", "EXECUTIVE_WEEKLY_CARD"]
    elif executive_view and (weekly_score < 75.0 or not go_live):
        action_code = "EXECUTIVE_WEEKLY_CARD"
        confidence = 0.84
        reasons = [
            f"Executive score {weekly_score:.1f}/100 needs management review",
            "Weekly card gives ROI and go/no-go evidence for business decisions",
        ]
        sequence = ["EXECUTIVE_WEEKLY_CARD", "RUN_OPS_CHECK"]
    elif go_live and risk_index < 45.0 and auto_release_rate >= 0.82 and error_ratio < 0.03:
        action_code = "MAINTAIN_MONITOR"
        confidence = 0.86
        reasons = [
            "Quality and risk indicators are within stable operating range",
            "Recommend keep policy and continue monitoring trend",
        ]
        sequence = ["RUN_OPS_CHECK", "EXECUTIVE_WEEKLY_CARD"]
    elif latency_p95 > 1800.0:
        action_code = "RUN_OPS_CHECK"
        confidence = 0.76
        reasons = [
            f"P95 latency {latency_p95:.1f}ms is above comfort range",
            "Run ops check to validate service quality before volume increase",
        ]
        sequence = ["RUN_OPS_CHECK", "EXECUTIVE_WEEKLY_CARD"]
    else:
        action_code = "RUN_OPS_CHECK"
        confidence = 0.8
        reasons = [
            "Balanced state detected; ops check keeps decision quality and traceability",
        ]
        sequence = ["RUN_OPS_CHECK", "EXECUTIVE_WEEKLY_CARD"]

    label_map = {
        "RUN_OPS_CHECK": "Smart Next: Ops Check",
        "DEEP_INNOVATION_REVIEW": "Smart Next: Deep Innovation",
        "EXECUTIVE_WEEKLY_CARD": "Smart Next: Weekly Card",
        "HOLD_AND_ESCALATE": "Smart Next: Escalate",
        "MAINTAIN_MONITOR": "Smart Next: Monitor",
    }
    title_map = {
        "RUN_OPS_CHECK": "Operational Health Check",
        "DEEP_INNOVATION_REVIEW": "Deep Innovation Review",
        "EXECUTIVE_WEEKLY_CARD": "Executive Weekly Card",
        "HOLD_AND_ESCALATE": "Hold And Escalate",
        "MAINTAIN_MONITOR": "Maintain And Monitor",
    }

    catalog = [
        {
            "code": "RUN_OPS_CHECK",
            "title": title_map["RUN_OPS_CHECK"],
            "requires_analysis_report": False,
        },
        {
            "code": "DEEP_INNOVATION_REVIEW",
            "title": title_map["DEEP_INNOVATION_REVIEW"],
            "requires_analysis_report": True,
        },
        {
            "code": "EXECUTIVE_WEEKLY_CARD",
            "title": title_map["EXECUTIVE_WEEKLY_CARD"],
            "requires_analysis_report": False,
        },
        {
            "code": "HOLD_AND_ESCALATE",
            "title": title_map["HOLD_AND_ESCALATE"],
            "requires_analysis_report": False,
        },
        {
            "code": "MAINTAIN_MONITOR",
            "title": title_map["MAINTAIN_MONITOR"],
            "requires_analysis_report": False,
        },
    ]

    return {
        "ok": True,
        "generated_at": _now_text(),
        "tenant_id": getattr(request.state, "tenant_id", None),
        "ui_role": ui_role,
        "recommended_action": {
            "code": action_code,
            "title": title_map.get(action_code, action_code),
            "button_label": label_map.get(action_code, "Smart Next"),
            "confidence": round(max(0.0, min(1.0, confidence)), 4),
            "reasons": reasons,
            "sequence": sequence,
        },
        "action_catalog": catalog,
        "signals": {
            "warning_level": warning_level,
            "risk_index_0_100": round(risk_index, 2),
            "complaint_rate": round(complaint_rate, 5),
            "auto_release_rate": round(auto_release_rate, 5),
            "latency_p95_ms": round(latency_p95, 2),
            "error_ratio": round(error_ratio, 5),
            "go_live_recommended": go_live,
            "weekly_score_0_100": round(weekly_score, 2),
        },
        "snapshot": {
            "scope": snapshot.get("scope"),
            "cockpit": cockpit_dict,
        },
    }


@app.get("/v1/system/next-best-action", response_model=None)
def get_system_next_best_action(
    request: Request,
    db_path: str | None = None,
    line_id: str | None = None,
    product_code: str | None = None,
    lot_id: str | None = None,
    window: int = 200,
    weekly_window: int = 500,
    ui_role: str | None = None,
) -> JSONResponse:
    payload = _build_next_best_action_payload(
        request=request,
        db_path=db_path,
        line_id=line_id,
        product_code=product_code,
        lot_id=lot_id,
        window=window,
        weekly_window=weekly_window,
        ui_role=ui_role,
    )
    return JSONResponse(content=_json_safe(payload))


@app.get("/v1/system/audit-tail")
def get_system_audit_tail(limit: int = 120) -> dict[str, Any]:
    safe_limit = max(1, min(int(limit), 500))
    backup_count = _count_existing_audit_backups()
    if not SETTINGS.enable_audit_log:
        return {
            "ok": True,
            "enabled": False,
            "path": str(AUDIT_LOG_PATH),
            "count": 0,
            "backup_count": backup_count,
            "rows": [],
        }
    if not AUDIT_LOG_PATH.exists():
        return {
            "ok": True,
            "enabled": True,
            "path": str(AUDIT_LOG_PATH),
            "count": 0,
            "backup_count": backup_count,
            "rows": [],
        }
    rows_raw: deque[str] = deque(maxlen=safe_limit)
    with AUDIT_LOG_LOCK:
        with AUDIT_LOG_PATH.open("r", encoding="utf-8", errors="replace") as fp:
            for line in fp:
                line_text = line.strip()
                if line_text:
                    rows_raw.append(line_text)
    rows: list[dict[str, Any]] = []
    for text in rows_raw:
        try:
            payload = json.loads(text)
            if isinstance(payload, dict):
                rows.append(payload)
            else:
                rows.append({"raw": text})
        except (json.JSONDecodeError, ValueError):
            rows.append({"raw": text})
    return {
        "ok": True,
        "enabled": True,
        "path": str(AUDIT_LOG_PATH),
        "count": len(rows),
        "backup_count": backup_count,
        "rows": rows,
    }


@app.get("/v1/system/self-test")
def get_system_self_test() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def add_check(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    add_check("default_action_rules_config", DEFAULT_ACTION_RULES_CONFIG.exists(), str(DEFAULT_ACTION_RULES_CONFIG))
    add_check("default_decision_policy_config", DEFAULT_DECISION_POLICY_CONFIG.exists(), str(DEFAULT_DECISION_POLICY_CONFIG))
    add_check("default_customer_tier_config", DEFAULT_CUSTOMER_TIER_CONFIG.exists(), str(DEFAULT_CUSTOMER_TIER_CONFIG))
    add_check("innovation_doc", DEFAULT_INNOVATION_DOC.exists(), str(DEFAULT_INNOVATION_DOC))

    try:
        DEFAULT_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
        probe = DEFAULT_OUTPUT_ROOT / f"_self_test_{uuid4().hex[:8]}.tmp"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        add_check("output_root_writable", True, str(DEFAULT_OUTPUT_ROOT))
    except Exception as exc:  # noqa: BLE001
        add_check("output_root_writable", False, str(exc))

    try:
        init_db(DEFAULT_HISTORY_DB)
        add_check("history_db_ready", True, str(DEFAULT_HISTORY_DB))
    except Exception as exc:  # noqa: BLE001
        add_check("history_db_ready", False, str(exc))

    try:
        DEFAULT_INNOVATION_DB.parent.mkdir(parents=True, exist_ok=True)
        add_check("innovation_db_parent_ready", True, str(DEFAULT_INNOVATION_DB.parent))
    except Exception as exc:  # noqa: BLE001
        add_check("innovation_db_parent_ready", False, str(exc))

    try:
        AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        probe = AUDIT_LOG_PATH.parent / f"_audit_self_test_{uuid4().hex[:8]}.tmp"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        add_check("audit_log_parent_writable", True, str(AUDIT_LOG_PATH.parent))
    except Exception as exc:  # noqa: BLE001
        add_check("audit_log_parent_writable", False, str(exc))

    if SETTINGS.enable_api_key_auth:
        add_check("api_key_auth_configured", len(API_KEY_ROLE_MAP) > 0, f"keys={len(API_KEY_ROLE_MAP)}")
        add_check("auth_header_name_valid", bool((SETTINGS.auth_header_name or "").strip()), SETTINGS.auth_header_name)
    else:
        add_check("api_key_auth_configured", True, "disabled")

    if SETTINGS.enforce_tenant_header:
        add_check("tenant_header_name_valid", bool(TENANT_HEADER_NAME.strip()), TENANT_HEADER_NAME)
        add_check("tenant_allowlist_configured", len(ALLOWED_TENANTS) > 0, f"tenants={len(ALLOWED_TENANTS)}")
    else:
        add_check("tenant_allowlist_configured", True, "disabled")

    webhook = SETTINGS.alert_webhook_url.strip()
    add_check("alert_provider_valid", ALERT_PROVIDER in {"webhook", "wecom", "dingtalk"}, ALERT_PROVIDER)
    if webhook:
        add_check("alert_webhook_url_present", webhook.startswith("http://") or webhook.startswith("https://"), webhook)
        if ALERT_PROVIDER == "dingtalk":
            add_check("alert_dingtalk_secret_present", bool(SETTINGS.alert_dingtalk_secret.strip()), "required for dingtalk")
        else:
            add_check("alert_dingtalk_secret_present", True, "not required")
    else:
        add_check("alert_webhook_url_present", True, "disabled")
        add_check("alert_dingtalk_secret_present", True, "disabled")

    if (SETTINGS.alert_webhook_map_json or "").strip():
        try:
            payload = json.loads(SETTINGS.alert_webhook_map_json)
            add_check("alert_webhook_map_json_valid", isinstance(payload, dict), "json dict required")
        except Exception as exc:  # noqa: BLE001
            add_check("alert_webhook_map_json_valid", False, str(exc))
    else:
        add_check("alert_webhook_map_json_valid", True, "disabled")

    try:
        ALERT_DEAD_LETTER_PATH.parent.mkdir(parents=True, exist_ok=True)
        probe = ALERT_DEAD_LETTER_PATH.parent / f"_alert_dead_self_test_{uuid4().hex[:8]}.tmp"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        add_check("alert_dead_letter_parent_writable", True, str(ALERT_DEAD_LETTER_PATH.parent))
    except Exception as exc:  # noqa: BLE001
        add_check("alert_dead_letter_parent_writable", False, str(exc))

    add_check(
        "alert_dead_letter_rotation_config",
        SETTINGS.alert_dead_letter_max_mb >= 0 and SETTINGS.alert_dead_letter_backups >= 1,
        f"max_mb={SETTINGS.alert_dead_letter_max_mb}, backups={SETTINGS.alert_dead_letter_backups}",
    )

    add_check("security_headers_enabled", SETTINGS.enable_security_headers, str(SETTINGS.enable_security_headers))
    add_check(
        "audit_rotation_config",
        SETTINGS.audit_rotate_max_mb >= 0 and SETTINGS.audit_rotate_backups >= 1,
        f"max_mb={SETTINGS.audit_rotate_max_mb}, backups={SETTINGS.audit_rotate_backups}",
    )
    add_check(
        "metrics_path_cap_config",
        SETTINGS.metrics_max_path_entries >= 200,
        f"metrics_max_path_entries={SETTINGS.metrics_max_path_entries}",
    )
    add_check(
        "ops_summary_cache_ttl_config",
        SETTINGS.ops_summary_cache_ttl_sec >= 0,
        f"ops_summary_cache_ttl_sec={SETTINGS.ops_summary_cache_ttl_sec}",
    )

    passed = all(item["ok"] for item in checks)
    result = {
        "ok": passed,
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "check_count": len(checks),
        "checks": checks,
    }
    if not passed:
        failed = [c.get("name") for c in checks if not c.get("ok")]
        _emit_alert(
            level="error",
            key="system-self-test-failed",
            title="System self-test failed",
            payload={"failed_checks": failed, "check_count": len(checks)},
        )
    return result


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    return render_senia_home(APP_VERSION)


@app.get("/v1/web/classic", response_class=HTMLResponse)
def home_classic() -> str:
    return render_home_page(APP_VERSION)


@app.get("/v1/web/dashboard", response_class=HTMLResponse)
def web_senia_spa() -> str:
    """SENIA 全功能 SPA 仪表盘 (暴露所有端点)."""
    return render_senia_spa(APP_VERSION)


@app.get("/v1/senia/artifact")
def serve_senia_artifact(path: str = "") -> Response:
    """Serve generated analysis artifacts (heatmap, detection overlay, etc.)."""
    p = Path(path).resolve()
    allowed_root = DEFAULT_OUTPUT_ROOT.resolve()
    # Security: only serve files under the output directory
    if not str(p).startswith(str(allowed_root)):
        raise HTTPException(status_code=403, detail="forbidden: path outside output directory")
    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=404, detail="artifact not found")
    suffix = p.suffix.lower()
    allowed_suffixes = {".png", ".jpg", ".jpeg", ".json", ".html"}
    if suffix not in allowed_suffixes:
        raise HTTPException(status_code=403, detail="forbidden: unsupported file type")
    media_types = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                   ".json": "application/json", ".html": "text/html"}
    return FileResponse(str(p), media_type=media_types.get(suffix, "application/octet-stream"))


@app.get("/v1/web/executive-dashboard", response_class=HTMLResponse)
def web_executive_dashboard(
    db_path: str | None = None,
    line_id: str | None = None,
    product_code: str | None = None,
    lot_id: str | None = None,
    window: int = 200,
) -> str:
    return render_executive_dashboard(
        app_version=APP_VERSION,
        default_db_path=db_path or str(DEFAULT_HISTORY_DB),
        default_line_id=line_id or "",
        default_product_code=product_code or "",
        default_lot_id=lot_id or "",
        default_window=max(1, int(window)),
    )


@app.get("/v1/web/executive-brief", response_class=HTMLResponse)
def web_executive_brief(
    db_path: str | None = None,
    line_id: str | None = None,
    product_code: str | None = None,
    lot_id: str | None = None,
) -> str:
    return render_executive_brief_page(
        app_version=APP_VERSION,
        default_db_path=db_path or str(DEFAULT_HISTORY_DB),
        default_line_id=line_id or "",
        default_product_code=product_code or "",
        default_lot_id=lot_id or "",
    )


@app.get("/v1/web/innovation-v3", response_class=HTMLResponse)
def web_innovation_v3_dashboard(
    db_path: str | None = None,
    line_id: str | None = None,
    product_code: str | None = None,
) -> str:
    return render_innovation_v3_dashboard_page(
        app_version=APP_VERSION,
        default_db_path=db_path or str(DEFAULT_HISTORY_DB),
        default_line_id=line_id or "",
        default_product_code=product_code or "",
    )


@app.get("/v1/web/precision-observatory", response_class=HTMLResponse)
def web_precision_observatory(
    db_path: str | None = None,
    line_id: str | None = None,
    product_code: str | None = None,
) -> str:
    return render_precision_observatory_page(
        app_version=APP_VERSION,
        default_db_path=db_path or str(DEFAULT_HISTORY_DB),
        default_line_id=line_id or "",
        default_product_code=product_code or "",
    )


@app.get("/v1/web/assets/observatory-module.js")
def web_precision_observatory_module() -> Response:
    return Response(content=get_precision_observatory_module_js(), media_type="application/javascript")


@app.get("/v1/report/html")
def get_report_html(path: str) -> FileResponse:
    html_path = _resolve_project_html_path(path)
    return FileResponse(path=str(html_path), media_type="text/html", filename=html_path.name)


@app.get("/v1/profiles")
def get_profiles() -> dict[str, Any]:
    return {"profiles": PROFILES}


@app.post("/v1/analyze/single")
def analyze_single(req: SingleAnalyzeRequest) -> dict[str, Any]:
    try:
        rows, cols = parse_grid(req.grid)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"invalid grid: {exc}") from exc

    output_dir = _generate_output_dir("single", req.output_dir)
    image = _load_image(req.image)
    board_quad = _quad_from_payload(req.board_quad, "board_quad")
    sample_quad = _quad_from_payload(req.sample_quad, "sample_quad")
    if board_quad is None and req.board_roi is not None:
        board_quad = roi_to_quad(req.board_roi.to_roi())
    if sample_quad is None and req.sample_roi is not None:
        sample_quad = roi_to_quad(req.sample_roi.to_roi())

    target_override = build_target_override(req.target_avg, req.target_p95, req.target_max)
    aruco_config = {"enabled": bool(req.use_aruco), "dict_name": req.aruco_dict, "ids_order": req.aruco_ids}

    report = analyze_single_image(
        image_bgr=image,
        grid_rows=rows,
        grid_cols=cols,
        profile_name=req.profile,
        output_dir=output_dir,
        board_quad_override=board_quad,
        sample_quad_override=sample_quad,
        target_override=target_override,
        aruco_config=aruco_config,
        enable_shading_correction=not req.disable_shading_correction,
    )
    report["inputs"] = {
        "image": req.image.path if req.image.path else "inline_b64",
        "grid": {"rows": rows, "cols": cols},
    }
    report["generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _add_history_assessment(report, req.history)
    _add_policy_recommendation(report, req.history)
    _attach_process_advice(report, enabled=req.with_process_advice, explicit_path=req.action_rules_config)
    tier_info = _attach_decision_center(
        report,
        enabled=req.with_decision_center,
        explicit_path=req.decision_policy_config,
        customer_tier=req.customer_tier,
        customer_id=req.customer_id,
        customer_tier_config_path=req.customer_tier_config,
    )
    _attach_innovation_engine(
        report,
        enabled=req.with_innovation_engine,
        context=req.innovation_context,
    )

    report_path = output_dir / "elite_color_match_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path = None
    if req.html_report:
        html_path = output_dir / "elite_color_match_report.html"
        write_html_report(report, html_path)

    _record_with_history(report, req.history, report_path)
    resp: dict[str, Any] = {
        "mode": report.get("mode"),
        "pass": report.get("result", {}).get("pass"),
        "confidence": report.get("result", {}).get("confidence", {}).get("overall"),
        "process_advice": _process_advice_brief(report),
        "decision_center": _decision_center_brief(report),
        "policy_recommendation": _policy_recommendation_brief(report),
        "innovation_engine": _innovation_brief(report),
        "output_dir": str(output_dir),
        "report_path": str(report_path),
        "html_path": str(html_path) if html_path else None,
    }
    if tier_info is not None:
        resp["customer_tier_applied"] = tier_info
    if req.include_report:
        resp["report"] = report
    _emit_quality_risk_alert("analyze_single", resp)
    return resp


@app.post("/v1/analyze/dual")
def analyze_dual(req: DualAnalyzeRequest) -> dict[str, Any]:
    try:
        rows, cols = parse_grid(req.grid)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"invalid grid: {exc}") from exc

    output_dir = _generate_output_dir("dual", req.output_dir)
    reference = _load_image(req.reference)
    film = _load_image(req.film)
    target_override = build_target_override(req.target_avg, req.target_p95, req.target_max)
    roi = req.roi.to_roi() if req.roi is not None else None

    report = analyze_dual_image(
        reference_bgr=reference,
        film_bgr=film,
        grid_rows=rows,
        grid_cols=cols,
        profile_name=req.profile,
        roi=roi,
        output_dir=output_dir,
        target_override=target_override,
        enable_shading_correction=not req.disable_shading_correction,
    )
    report["inputs"] = {
        "reference": req.reference.path if req.reference.path else "inline_b64",
        "film": req.film.path if req.film.path else "inline_b64",
        "grid": {"rows": rows, "cols": cols},
    }
    report["generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _add_history_assessment(report, req.history)
    _add_policy_recommendation(report, req.history)
    _attach_process_advice(report, enabled=req.with_process_advice, explicit_path=req.action_rules_config)
    tier_info = _attach_decision_center(
        report,
        enabled=req.with_decision_center,
        explicit_path=req.decision_policy_config,
        customer_tier=req.customer_tier,
        customer_id=req.customer_id,
        customer_tier_config_path=req.customer_tier_config,
    )
    _attach_innovation_engine(
        report,
        enabled=req.with_innovation_engine,
        context=req.innovation_context,
    )

    report_path = output_dir / "elite_color_match_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path = None
    if req.html_report:
        html_path = output_dir / "elite_color_match_report.html"
        write_html_report(report, html_path)

    _record_with_history(report, req.history, report_path)
    resp: dict[str, Any] = {
        "mode": report.get("mode"),
        "pass": report.get("result", {}).get("pass"),
        "confidence": report.get("result", {}).get("confidence", {}).get("overall"),
        "process_advice": _process_advice_brief(report),
        "decision_center": _decision_center_brief(report),
        "policy_recommendation": _policy_recommendation_brief(report),
        "innovation_engine": _innovation_brief(report),
        "output_dir": str(output_dir),
        "report_path": str(report_path),
        "html_path": str(html_path) if html_path else None,
    }
    if tier_info is not None:
        resp["customer_tier_applied"] = tier_info
    if req.include_report:
        resp["report"] = report
    _emit_quality_risk_alert("analyze_dual", resp)
    return resp


@app.post("/v1/web/analyze/dual-upload")
async def analyze_dual_upload(
    reference: UploadFile = File(...),
    film: UploadFile = File(...),
    profile: str = Form("auto"),
    grid: str = Form("6x8"),
    output_dir: str | None = Form(None),
    html_report: bool = Form(True),
    include_report: bool = Form(False),
    disable_shading_correction: bool = Form(False),
    with_process_advice: bool = Form(True),
    with_decision_center: bool = Form(True),
    with_innovation_engine: bool = Form(True),
    customer_id: str | None = Form(None),
    customer_tier: str | None = Form(None),
    innovation_context_json: str | None = Form(None),
) -> dict[str, Any]:
    req = DualAnalyzeRequest(
        reference=await _upload_to_image_input(reference, "reference"),
        film=await _upload_to_image_input(film, "film"),
        profile=profile.strip() or "auto",
        grid=grid.strip() or "6x8",
        output_dir=_clean_optional_text(output_dir),
        html_report=bool(html_report),
        include_report=bool(include_report),
        disable_shading_correction=bool(disable_shading_correction),
        with_process_advice=bool(with_process_advice),
        with_decision_center=bool(with_decision_center),
        with_innovation_engine=bool(with_innovation_engine),
        customer_id=_clean_optional_text(customer_id),
        customer_tier=_clean_optional_text(customer_tier),
        innovation_context=_parse_optional_dict_json(innovation_context_json, "innovation_context_json"),
    )
    return analyze_dual(req)


@app.post("/v1/web/analyze/single-upload")
async def analyze_single_upload(
    image: UploadFile = File(...),
    profile: str = Form("auto"),
    grid: str = Form("6x8"),
    output_dir: str | None = Form(None),
    html_report: bool = Form(True),
    include_report: bool = Form(False),
    use_aruco: bool = Form(False),
    aruco_dict: str = Form("DICT_4X4_50"),
    disable_shading_correction: bool = Form(False),
    with_process_advice: bool = Form(True),
    with_decision_center: bool = Form(True),
    with_innovation_engine: bool = Form(True),
    customer_id: str | None = Form(None),
    customer_tier: str | None = Form(None),
    innovation_context_json: str | None = Form(None),
) -> dict[str, Any]:
    req = SingleAnalyzeRequest(
        image=await _upload_to_image_input(image, "image"),
        profile=profile.strip() or "auto",
        grid=grid.strip() or "6x8",
        output_dir=_clean_optional_text(output_dir),
        html_report=bool(html_report),
        include_report=bool(include_report),
        use_aruco=bool(use_aruco),
        aruco_dict=aruco_dict.strip() or "DICT_4X4_50",
        disable_shading_correction=bool(disable_shading_correction),
        with_process_advice=bool(with_process_advice),
        with_decision_center=bool(with_decision_center),
        with_innovation_engine=bool(with_innovation_engine),
        customer_id=_clean_optional_text(customer_id),
        customer_tier=_clean_optional_text(customer_tier),
        innovation_context=_parse_optional_dict_json(innovation_context_json, "innovation_context_json"),
    )
    return analyze_single(req)


@app.post("/v1/analyze/batch")
def analyze_batch(req: BatchAnalyzeRequest) -> dict[str, Any]:
    try:
        rows, cols = parse_grid(req.grid)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"invalid grid: {exc}") from exc

    output_dir = _generate_output_dir("batch", req.output_dir)
    board_quad = _quad_from_payload(req.board_quad, "board_quad")
    sample_quad = _quad_from_payload(req.sample_quad, "sample_quad")
    if board_quad is None and req.board_roi is not None:
        board_quad = roi_to_quad(req.board_roi.to_roi())
    if sample_quad is None and req.sample_roi is not None:
        sample_quad = roi_to_quad(req.sample_roi.to_roi())

    if req.image_paths:
        image_paths = [Path(p) for p in req.image_paths if Path(p).is_file()]
        batch_dir = Path(req.batch_dir) if req.batch_dir else Path(req.image_paths[0]).parent
    else:
        batch_dir = Path(req.batch_dir)  # type: ignore[arg-type]
        if not batch_dir.exists():
            raise HTTPException(status_code=400, detail=f"batch_dir not found: {batch_dir}")
        image_paths = _list_images_from_dir(batch_dir, req.patterns, req.recursive)

    if not image_paths:
        raise HTTPException(status_code=400, detail="no valid images found for batch mode")

    target_override = build_target_override(req.target_avg, req.target_p95, req.target_max)
    aruco_config = {"enabled": bool(req.use_aruco), "dict_name": req.aruco_dict, "ids_order": req.aruco_ids}
    action_rules_config = _resolve_action_rules_config(
        enabled=req.with_process_advice,
        explicit_path=req.action_rules_config,
    )
    decision_policy_config, decision_policy_override, _, tier_info = _resolve_decision_policy_for_request(
        enabled=req.with_decision_center,
        explicit_policy_path=req.decision_policy_config,
        customer_tier=req.customer_tier,
        customer_id=req.customer_id,
        customer_tier_config_path=req.customer_tier_config,
    )
    if decision_policy_override is not None:
        resolved_path = output_dir / "_decision_policy_resolved.json"
        resolved_path.write_text(json.dumps(decision_policy_override, ensure_ascii=False, indent=2), encoding="utf-8")
        decision_policy_config = resolved_path

    batch = run_batch_single_mode(
        batch_dir=batch_dir,
        image_paths=image_paths,
        rows=rows,
        cols=cols,
        profile=req.profile,
        output_dir=output_dir,
        board_quad_override=board_quad,
        sample_quad_override=sample_quad,
        target_override=target_override,
        aruco_config=aruco_config,
        enable_shading_correction=not req.disable_shading_correction,
        write_html=bool(req.html_report),
        action_rules_config=action_rules_config,
        decision_policy_config=decision_policy_config,
        enable_decision_center=bool(req.with_decision_center),
    )

    summary_path = Path(batch["summary_json"])
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    decision_counts: dict[str, int] = {}
    decision_scored = 0
    for row in summary.get("rows", []):
        if row.get("status") != "ok":
            continue
        report_fp = row.get("report")
        if not report_fp:
            continue
        try:
            rep = json.loads(Path(report_fp).read_text(encoding="utf-8"))
            dc = rep.get("decision_center", {})
            if not isinstance(dc, dict):
                continue
            code = str(dc.get("decision_code", "UNKNOWN"))
            decision_counts[code] = decision_counts.get(code, 0) + 1
            decision_scored += 1
        except Exception:  # noqa: BLE001
            continue

    if req.history is not None:
        init_db(Path(req.history.db_path))
        for row in summary.get("rows", []):
            if row.get("status") != "ok":
                continue
            report_fp = row.get("report")
            if not report_fp:
                continue
            try:
                report_obj = json.loads(Path(report_fp).read_text(encoding="utf-8"))
                record_run(
                    db_path=Path(req.history.db_path),
                    report=report_obj,
                    line_id=req.history.line_id,
                    product_code=req.history.product_code,
                    lot_id=req.history.lot_id,
                    report_path=report_fp,
                )
            except Exception:  # noqa: BLE001
                continue

    resp: dict[str, Any] = {
        "total": int(batch["total"]),
        "ok": int(batch["ok"]),
        "error": int(batch["error"]),
        "output_dir": str(output_dir),
        "summary_json": str(batch["summary_json"]),
        "summary_csv": str(batch["summary_csv"]),
        "decision_overview": {
            "scored_count": decision_scored,
            "decision_counts": decision_counts,
        },
    }
    if tier_info is not None:
        resp["customer_tier_applied"] = tier_info
    if req.history is not None:
        try:
            resp["policy_recommendation"] = recommend_policy_adjustments(
                db_path=Path(req.history.db_path),
                line_id=req.history.line_id,
                product_code=req.history.product_code,
                lot_id=req.history.lot_id,
                window=max(20, int(req.history.window) * 4),
            )
        except Exception:  # noqa: BLE001
            pass
    if req.include_rows:
        resp["rows"] = summary.get("rows", [])
    if int(resp.get("error", 0)) > 0:
        _emit_alert(
            level="warning",
            key="analyze-batch-errors",
            title="Batch analysis produced error rows",
            payload={
                "error_count": resp.get("error"),
                "ok_count": resp.get("ok"),
                "total": resp.get("total"),
                "output_dir": resp.get("output_dir"),
            },
        )
    return resp


@app.post("/v1/analyze/ensemble")
def analyze_ensemble(req: EnsembleAnalyzeRequest) -> dict[str, Any]:
    try:
        rows, cols = parse_grid(req.grid)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"invalid grid: {exc}") from exc

    output_dir = _generate_output_dir("ensemble", req.output_dir)
    board_quad = _quad_from_payload(req.board_quad, "board_quad")
    sample_quad = _quad_from_payload(req.sample_quad, "sample_quad")
    if board_quad is None and req.board_roi is not None:
        board_quad = roi_to_quad(req.board_roi.to_roi())
    if sample_quad is None and req.sample_roi is not None:
        sample_quad = roi_to_quad(req.sample_roi.to_roi())

    if req.ensemble_images:
        image_paths = [Path(p) for p in req.ensemble_images if Path(p).is_file()]
    else:
        ensemble_dir = Path(req.ensemble_dir)  # type: ignore[arg-type]
        if not ensemble_dir.exists():
            raise HTTPException(status_code=400, detail=f"ensemble_dir not found: {ensemble_dir}")
        image_paths = _list_images_from_dir(ensemble_dir, req.patterns, req.recursive)

    if not image_paths:
        raise HTTPException(status_code=400, detail="no valid images found for ensemble mode")

    target_override = build_target_override(req.target_avg, req.target_p95, req.target_max)
    aruco_config = {"enabled": bool(req.use_aruco), "dict_name": req.aruco_dict, "ids_order": req.aruco_ids}
    action_rules_config = _resolve_action_rules_config(
        enabled=req.with_process_advice,
        explicit_path=req.action_rules_config,
    )
    decision_policy_config, decision_policy_override, _, tier_info = _resolve_decision_policy_for_request(
        enabled=req.with_decision_center,
        explicit_policy_path=req.decision_policy_config,
        customer_tier=req.customer_tier,
        customer_id=req.customer_id,
        customer_tier_config_path=req.customer_tier_config,
    )
    if decision_policy_override is not None:
        resolved_path = output_dir / "_decision_policy_resolved.json"
        resolved_path.write_text(json.dumps(decision_policy_override, ensure_ascii=False, indent=2), encoding="utf-8")
        decision_policy_config = resolved_path

    ens = run_ensemble_single_mode(
        image_paths=image_paths,
        rows=rows,
        cols=cols,
        profile=req.profile,
        output_dir=output_dir,
        board_quad_override=board_quad,
        sample_quad_override=sample_quad,
        target_override=target_override,
        aruco_config=aruco_config,
        enable_shading_correction=not req.disable_shading_correction,
        min_count=max(1, int(req.min_count)),
        write_html=bool(req.html_report),
        action_rules_config=action_rules_config,
        decision_policy_config=decision_policy_config,
        enable_decision_center=bool(req.with_decision_center),
    )

    report_path = Path(ens["report_json"])
    report_obj = json.loads(report_path.read_text(encoding="utf-8"))
    _add_history_assessment(report_obj, req.history)
    _add_policy_recommendation(report_obj, req.history)
    _attach_process_advice(report_obj, enabled=req.with_process_advice, explicit_path=req.action_rules_config)
    _attach_decision_center(
        report_obj,
        enabled=req.with_decision_center,
        explicit_path=req.decision_policy_config,
        customer_tier=req.customer_tier,
        customer_id=req.customer_id,
        customer_tier_config_path=req.customer_tier_config,
    )
    _attach_innovation_engine(
        report_obj,
        enabled=req.with_innovation_engine,
        context=req.innovation_context,
    )
    report_path.write_text(json.dumps(report_obj, ensure_ascii=False, indent=2), encoding="utf-8")
    _record_with_history(report_obj, req.history, report_path)

    resp: dict[str, Any] = {
        "total": int(ens["total"]),
        "ok": int(ens["ok"]),
        "error": int(ens["error"]),
        "pass": bool(ens["pass"]),
        "process_advice": _process_advice_brief(report_obj),
        "decision_center": _decision_center_brief(report_obj),
        "policy_recommendation": _policy_recommendation_brief(report_obj),
        "innovation_engine": _innovation_brief(report_obj),
        "output_dir": str(output_dir),
        "report_json": str(ens["report_json"]),
        "report_csv": str(ens["report_csv"]),
        "report_html": ens.get("report_html"),
    }
    if tier_info is not None:
        resp["customer_tier_applied"] = tier_info
    if req.include_report:
        resp["report"] = report_obj
    _emit_quality_risk_alert("analyze_ensemble", resp)
    return resp


@app.post("/v1/outcome/record")
def post_outcome_record(req: OutcomeRecordRequest) -> dict[str, Any]:
    path = Path(req.db_path)
    init_db(path)
    row = record_outcome(
        db_path=path,
        outcome=req.outcome,
        run_id=req.run_id,
        report_path=req.report_path,
        line_id=req.line_id,
        product_code=req.product_code,
        lot_id=req.lot_id,
        severity=req.severity,
        realized_cost=req.realized_cost,
        customer_rating=req.customer_rating,
        note=req.note,
    )
    _invalidate_ops_summary_cache()
    return {"ok": True, "row": row}


@app.post("/v1/analyze/spectral")
def post_analyze_spectral(req: SpectralAnalyzeRequest) -> dict[str, Any]:
    sample = tuple(int(_clamp(_safe_float(v), 0, 255)) for v in req.sample_rgb[:3])
    film = tuple(int(_clamp(_safe_float(v), 0, 255)) for v in req.film_rgb[:3])
    with INNOVATION_LOCK:
        result = INNOVATION_ENGINE.spectral.metamerism_index(sample, film)
    return {"enabled": True, "innovation": "spectral_metamerism", **result}


@app.post("/v1/analyze/texture-aware")
def post_analyze_texture_aware(req: TextureAwareRequest) -> dict[str, Any]:
    with INNOVATION_LOCK:
        result = INNOVATION_ENGINE.texture.compute(
            standard_de=float(req.standard_delta_e),
            sample_texture_std=float(req.sample_texture_std),
            film_texture_std=float(req.film_texture_std),
            texture_similarity=float(req.texture_similarity),
            material_type=req.material_type,
        )
    return {"enabled": True, "innovation": "texture_aware_deltae", **result}


@app.post("/v1/analyze/full-innovation")
def post_analyze_full_innovation(req: FullInnovationRequest) -> dict[str, Any]:
    report = _load_report_payload(req.report_path, req.report)
    run_input = _report_to_innovation_input(report)
    with INNOVATION_LOCK:
        out = INNOVATION_ENGINE.full_analysis(run_input, req.context or {})
    return {
        "enabled": True,
        "innovation": "elite_v14_full_stack",
        "innovation_count": len(out.get("innovations", {})) if isinstance(out.get("innovations"), dict) else 0,
        **out,
    }


@app.get("/v1/history/drift-prediction")
def get_history_drift_prediction(
    db_path: str,
    line_id: str | None = None,
    product_code: str | None = None,
    lot_id: str | None = None,
    window: int = 120,
    threshold: float = 3.0,
) -> dict[str, Any]:
    path = Path(db_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"db not found: {db_path}")
    rows = list_recent_runs(
        db_path=path,
        line_id=line_id,
        product_code=product_code,
        lot_id=lot_id,
        limit=max(10, int(window)),
    )
    if not rows:
        return {"enabled": False, "reason": "no_runs"}

    predictor = DriftPredictor(threshold=float(threshold), window=max(20, int(window)))
    rows_sorted = sorted(rows, key=lambda r: int(r.get("id", 0)))
    sample_count = 0
    for row in rows_sorted:
        de = _safe_float(row.get("avg_de"), np.nan)
        if np.isnan(de):
            continue
        idx = int(row.get("id")) if row.get("id") is not None else sample_count + 1
        predictor.update(batch_index=idx, delta_e=de, extra={"run_id": row.get("id")})
        sample_count += 1

    if sample_count == 0:
        return {"enabled": False, "reason": "no_valid_avg_de"}

    pred = predictor.predict()
    return {
        "enabled": True,
        "innovation": "drift_predictor",
        "sample_count": sample_count,
        "threshold": float(threshold),
        "prediction": pred,
    }


@app.post("/v1/predict/aging")
def post_predict_aging(req: AgingPredictRequest) -> dict[str, Any]:
    with INNOVATION_LOCK:
        result = INNOVATION_ENGINE.aging.predict(
            lab_current=req.lab.to_dict(),
            material=req.material,
            environment=req.environment,
            years=req.years,
        )
    return {"enabled": True, "innovation": "color_aging_predictor", **result}


@app.post("/v1/predict/differential-aging")
def post_predict_differential_aging(req: DifferentialAgingPredictRequest) -> dict[str, Any]:
    with INNOVATION_LOCK:
        result = INNOVATION_ENGINE.aging.predict_differential_aging(
            lab_sample=req.sample_lab.to_dict(),
            lab_film=req.film_lab.to_dict(),
            material_sample=req.sample_material,
            material_film=req.film_material,
            environment=req.environment,
            years=req.years,
        )
    return {"enabled": True, "innovation": "differential_aging_predictor", **result}


@app.post("/v1/correct/ink-recipe")
def post_correct_ink_recipe(req: InkCorrectionRequest) -> dict[str, Any]:
    with INNOVATION_LOCK:
        result = INNOVATION_ENGINE.ink.compute_correction(
            dL=float(req.dL),
            dC=float(req.dC),
            dH=float(req.dH),
            current_recipe=req.current_recipe,
            confidence=float(req.confidence),
        )
    return {"enabled": True, "innovation": "ink_recipe_corrector", **result}


@app.post("/v1/optimize/batch-blend")
def post_optimize_batch_blend(req: BatchBlendOptimizeRequest) -> dict[str, Any]:
    batches = [
        {
            "batch_id": item.batch_id,
            "lab": item.lab.to_dict(),
            "quantity": float(item.quantity),
        }
        for item in req.batches
    ]
    n_groups = max(1, min(int(req.n_groups), len(batches)))
    with INNOVATION_LOCK:
        result = INNOVATION_ENGINE.blend.optimize(
            batches=batches,
            n_groups=n_groups,
            customer_tiers=req.customer_tiers,
        )
    return {"enabled": True, "innovation": "batch_blend_optimizer", **result}


@app.post("/v1/customer/acceptance-record")
def post_customer_acceptance_record(req: CustomerAcceptanceRecordRequest) -> dict[str, Any]:
    db_path = _resolve_innovation_db_path(req.db_path)
    if db_path is not None:
        record_acceptance_event(
            db_path=db_path,
            customer_id=req.customer_id,
            delta_e=float(req.delta_e),
            complained=bool(req.complained),
            extra=req.extra,
        )
    with INNOVATION_LOCK:
        INNOVATION_ENGINE.acceptance.record(
            customer_id=req.customer_id,
            delta_e=float(req.delta_e),
            complained=bool(req.complained),
            extra=req.extra,
        )
        profile = INNOVATION_ENGINE.acceptance.get_profile(req.customer_id)
    if db_path is not None:
        cache_key = f"{str(db_path.resolve())}::{req.customer_id}"
        ACCEPTANCE_SYNC_CACHE.pop(cache_key, None)
        upsert_acceptance_profile(db_path, INNOVATION_ENGINE.acceptance, req.customer_id)
    return {"ok": True, "profile": profile, "persisted": db_path is not None}


@app.get("/v1/customer/acceptance-profile")
def get_customer_acceptance_profile(customer_id: str, db_path: str | None = None) -> dict[str, Any]:
    db_fp, loaded, cache_hit = _sync_acceptance_customer_from_db(db_path, customer_id)
    with INNOVATION_LOCK:
        profile = INNOVATION_ENGINE.acceptance.get_profile(customer_id)
    if db_fp is not None and profile.get("status") != "unknown":
        upsert_acceptance_profile(db_fp, INNOVATION_ENGINE.acceptance, customer_id)
    return {
        "enabled": True,
        "innovation": "customer_acceptance_learner",
        "profile": profile,
        "db_sync": {"enabled": db_fp is not None, "events_loaded": loaded, "cache_hit": cache_hit},
    }


@app.get("/v1/customer/complaint-probability")
def get_customer_complaint_probability(customer_id: str, delta_e: float, db_path: str | None = None) -> dict[str, Any]:
    _sync_acceptance_customer_from_db(db_path, customer_id)
    with INNOVATION_LOCK:
        pred = INNOVATION_ENGINE.acceptance.predict_complaint_probability(customer_id, float(delta_e))
    return {
        "enabled": True,
        "innovation": "customer_acceptance_learner",
        "customer_id": customer_id,
        "delta_e": float(delta_e),
        **pred,
    }


@app.get("/v1/customer/dynamic-threshold")
def get_customer_dynamic_threshold(
    customer_id: str,
    target_complaint_rate: float = 0.05,
    db_path: str | None = None,
) -> dict[str, Any]:
    db_fp, _, _ = _sync_acceptance_customer_from_db(db_path, customer_id)
    with INNOVATION_LOCK:
        result = INNOVATION_ENGINE.acceptance.suggest_dynamic_threshold(customer_id, float(target_complaint_rate))
    if db_fp is not None:
        upsert_acceptance_profile(db_fp, INNOVATION_ENGINE.acceptance, customer_id)
    return {"enabled": True, "innovation": "customer_acceptance_learner", "customer_id": customer_id, **result}


@app.post("/v1/passport/generate")
def post_passport_generate(req: PassportGenerateRequest) -> dict[str, Any]:
    report = _load_report_payload(req.report_path, req.report)
    run_input = _report_to_innovation_input(report)
    decision_payload = req.decision
    if decision_payload is None:
        dc = report.get("decision_center", {})
        code = dc.get("decision_code") if isinstance(dc, dict) else None
        decision_payload = {"code": code or "UNKNOWN"}
    with INNOVATION_LOCK:
        passport = INNOVATION_ENGINE.passport.generate(
            run_result=run_input,
            decision=decision_payload,
            lot_id=req.lot_id,
            context=req.context,
        )
    db_fp = _resolve_innovation_db_path(req.db_path)
    if db_fp is not None:
        save_color_passport(db_fp, passport)
    return {"enabled": True, "innovation": "color_passport", "passport": passport, "persisted": db_fp is not None}


@app.post("/v1/passport/verify")
def post_passport_verify(req: PassportVerifyRequest) -> dict[str, Any]:
    passport_payload = req.passport
    if passport_payload is None and req.passport_id:
        db_fp = _resolve_innovation_db_path(req.db_path)
        if db_fp is None:
            raise HTTPException(status_code=400, detail="passport_id verification requires db_path")
        passport_payload = load_color_passport(db_fp, req.passport_id)
        if passport_payload is None:
            raise HTTPException(status_code=404, detail=f"passport not found: {req.passport_id}")
    if passport_payload is None:
        raise HTTPException(status_code=400, detail="passport payload is required")
    with INNOVATION_LOCK:
        result = INNOVATION_ENGINE.passport.verify(passport_payload, req.new_lab.to_dict())
    return {"enabled": True, "innovation": "color_passport", **result}


@app.get("/v1/innovation/manifest")
def get_innovation_manifest() -> dict[str, Any]:
    return {
        "enabled": True,
        "module": "elite_innovation_engine.py",
        "doc_path": str(DEFAULT_INNOVATION_DOC),
        "loaded": True,
        "runtime": {
            "service_version": APP_VERSION,
            "api_host": SETTINGS.api_host,
            "api_port": SETTINGS.api_port,
            "acceptance_sync_ttl_sec": SETTINGS.acceptance_sync_ttl_sec,
            "upload_max_bytes": MAX_UPLOAD_BYTES,
            "audit_log_enabled": SETTINGS.enable_audit_log,
            "audit_rotate_max_mb": SETTINGS.audit_rotate_max_mb,
            "audit_rotate_backups": SETTINGS.audit_rotate_backups,
            "metrics_window_size": SETTINGS.metrics_window_size,
            "metrics_max_path_entries": SETTINGS.metrics_max_path_entries,
            "api_key_auth_enabled": SETTINGS.enable_api_key_auth,
            "auth_header_name": SETTINGS.auth_header_name,
            "rate_limit_rpm": SETTINGS.rate_limit_rpm,
            "tenant_enforced": SETTINGS.enforce_tenant_header,
            "tenant_header_name": TENANT_HEADER_NAME,
            "alert_webhook_enabled": bool(SETTINGS.alert_webhook_url.strip()),
            "alert_webhook_map_configured": bool((SETTINGS.alert_webhook_map_json or "").strip()),
            "alert_provider": ALERT_PROVIDER,
            "alert_min_level": ALERT_MIN_LEVEL,
            "alert_retry_count": SETTINGS.alert_retry_count,
            "alert_retry_backoff_ms": SETTINGS.alert_retry_backoff_ms,
            "alert_dead_letter_max_mb": SETTINGS.alert_dead_letter_max_mb,
            "alert_dead_letter_backups": SETTINGS.alert_dead_letter_backups,
            "enable_security_headers": SETTINGS.enable_security_headers,
            "ops_summary_cache_ttl_sec": SETTINGS.ops_summary_cache_ttl_sec,
        },
        "endpoints": [
            "/ready",
            "/v1/system/status",
            "/v1/system/metrics",
            "/v1/system/slo",
            "/v1/system/auth-info",
            "/v1/system/tenant-info",
            "/v1/system/alert-test",
            "/v1/system/alert-dead-letter",
            "/v1/system/alert-replay",
            "/v1/system/audit-tail",
            "/v1/system/self-test",
            "/v1/system/ops-summary",
            "/v1/system/executive-brief",
            "/v1/system/release-gate-report",
            "/v1/report/html",
            "/v1/web/executive-dashboard",
            "/v1/web/executive-brief",
            "/v1/web/innovation-v3",
            "/v1/web/precision-observatory",
            "/v1/web/assets/observatory-module.js",
            "/v1/web/analyze/single-upload",
            "/v1/web/analyze/dual-upload",
            "/v1/analyze/spectral",
            "/v1/analyze/texture-aware",
            "/v1/analyze/multi-observer",
            "/v1/analyze/full-innovation",
            "/v1/quality/spc/analyze",
            "/v1/quality/spc/from-history",
            "/v1/history/drift-prediction",
            "/v1/predict/aging",
            "/v1/predict/differential-aging",
            "/v1/report/shift/generate",
            "/v1/report/shift/from-history",
            "/v1/correct/ink-recipe",
            "/v1/optimize/batch-blend",
            "/v1/supplier/record",
            "/v1/supplier/scorecard",
            "/v1/standards/register",
            "/v1/standards/get",
            "/v1/standards/compare",
            "/v1/standards/version-drift",
            "/v1/standards/list",
            "/v1/customer/acceptance-record",
            "/v1/customer/acceptance-profile",
            "/v1/customer/complaint-probability",
            "/v1/customer/dynamic-threshold",
            "/v1/passport/generate",
            "/v1/passport/verify",
            "/v1/mvp2/manifest",
            "/v1/mvp2/pipeline/run",
            "/v1/mvp2/ccm/calibrate",
            "/v1/mvp2/sop",
            "/v1/lifecycle/manifest",
            "/v1/lifecycle/preflight-check",
            "/v1/lifecycle/environment/check",
            "/v1/lifecycle/substrate/compare",
            "/v1/lifecycle/wet-dry/predict",
            "/v1/lifecycle/run-monitor/report",
            "/v1/lifecycle/operator/leaderboard",
            "/v1/lifecycle/trace/chain",
            "/v1/history/executive-export",
        ],
    }


@app.post("/v1/analyze/multi-observer")
def post_analyze_multi_observer(req: ObserverAnalyzeRequest) -> dict[str, Any]:
    sample = req.sample_lab.to_dict()
    film = req.film_lab.to_dict()
    with INNOVATION_LOCK:
        sim = INNOVATION_ENGINE.observer.simulate(
            lab_sample=sample,
            lab_film=film,
            standard_de=req.standard_delta_e,
        )
        demographic = INNOVATION_ENGINE.observer.for_demographic(
            lab_sample=sample,
            lab_film=film,
            target_age=int(req.target_age),
            sensitivity=req.sensitivity,
        )
    return {
        "enabled": True,
        "innovation": "multi_observer_simulator",
        "simulation": sim,
        "demographic_focus": demographic,
    }


@app.post("/v1/quality/spc/analyze")
def post_quality_spc_analyze(req: SPCAnalyzeRequest) -> dict[str, Any]:
    with INNOVATION_LOCK:
        spc_engine = INNOVATION_ENGINE.spc.__class__()
        for subgroup in req.subgroups:
            spc_engine.add_subgroup([float(v) for v in subgroup])
        result = spc_engine.analyze(
            spec_lower=float(req.spec_lower),
            spec_upper=float(req.spec_upper),
        )
    return {"enabled": True, "innovation": "spc_engine", "result": result}


@app.get("/v1/quality/spc/from-history")
def get_quality_spc_from_history(
    db_path: str,
    line_id: str | None = None,
    product_code: str | None = None,
    lot_id: str | None = None,
    window: int = 120,
    subgroup_size: int = 5,
    spec_lower: float = 0.0,
    spec_upper: float = 3.0,
) -> dict[str, Any]:
    fp = Path(db_path)
    if not fp.exists():
        raise HTTPException(status_code=404, detail=f"db not found: {db_path}")
    group_size = max(2, min(10, int(subgroup_size)))
    rows = list_recent_runs(
        db_path=fp,
        line_id=line_id,
        product_code=product_code,
        lot_id=lot_id,
        limit=max(20, int(window)),
    )
    values: list[float] = []
    for row in sorted(rows, key=lambda item: int(item.get("id", 0))):
        de = _safe_float(row.get("avg_de"), np.nan)
        if np.isnan(de):
            continue
        values.append(float(de))
    if len(values) < group_size * 5:
        return {
            "enabled": False,
            "innovation": "spc_engine",
            "reason": "insufficient_points",
            "required": group_size * 5,
            "actual": len(values),
        }

    usable = (len(values) // group_size) * group_size
    values = values[-usable:]
    with INNOVATION_LOCK:
        spc_engine = INNOVATION_ENGINE.spc.__class__()
        for idx in range(0, len(values), group_size):
            spc_engine.add_subgroup(values[idx:idx + group_size])
        result = spc_engine.analyze(spec_lower=float(spec_lower), spec_upper=float(spec_upper))
    return {
        "enabled": True,
        "innovation": "spc_engine",
        "source": "history",
        "points": len(values),
        "subgroup_size": group_size,
        "result": result,
    }


@app.post("/v1/report/shift/generate")
def post_report_shift_generate(req: ShiftGenerateRequest) -> dict[str, Any]:
    with INNOVATION_LOCK:
        shift_engine = INNOVATION_ENGINE.shift.__class__()
        for item in req.runs:
            shift_engine.add_run(
                {
                    "avg_de": float(item.avg_de),
                    "pass": bool(item.pass_flag),
                    "decision": item.decision,
                    "confidence": float(item.confidence),
                    "product_code": item.product_code,
                    "lot_id": item.lot_id,
                    "dL": float(item.dL),
                    "dC": float(item.dC),
                    "dH": float(item.dH),
                }
            )
        report = shift_engine.generate(
            shift_id=req.shift_id,
            line_id=req.line_id,
            hours=float(req.hours),
        )
    return {"enabled": True, "innovation": "shift_report_generator", "report": report}


@app.get("/v1/report/shift/from-history")
def get_report_shift_from_history(
    db_path: str,
    line_id: str | None = None,
    product_code: str | None = None,
    lot_id: str | None = None,
    window: int = 160,
    shift_id: str | None = None,
    hours: float = 8.0,
) -> dict[str, Any]:
    fp = Path(db_path)
    if not fp.exists():
        raise HTTPException(status_code=404, detail=f"db not found: {db_path}")
    rows = list_recent_runs(
        db_path=fp,
        line_id=line_id,
        product_code=product_code,
        lot_id=lot_id,
        limit=max(20, int(window)),
    )
    if not rows:
        return {"enabled": False, "innovation": "shift_report_generator", "reason": "no_runs"}

    with INNOVATION_LOCK:
        shift_engine = INNOVATION_ENGINE.shift.__class__()
        valid_count = 0
        for row in rows:
            de = _safe_float(row.get("avg_de"), np.nan)
            if np.isnan(de):
                continue
            shift_engine.add_run(
                {
                    "ts": row.get("created_at"),
                    "avg_de": float(de),
                    "pass": bool(row.get("pass")),
                    "decision": row.get("decision_code") or "AUTO_RELEASE",
                    "confidence": _safe_float(row.get("confidence"), 0.0),
                    "product_code": row.get("product_code") or "",
                    "lot_id": row.get("lot_id") or "",
                    "dL": _safe_float(row.get("dL"), 0.0),
                    "dC": _safe_float(row.get("dC"), 0.0),
                    "dH": _safe_float(row.get("dH"), 0.0),
                }
            )
            valid_count += 1
        if valid_count == 0:
            return {"enabled": False, "innovation": "shift_report_generator", "reason": "no_valid_runs"}
        report = shift_engine.generate(
            shift_id=shift_id,
            line_id=line_id,
            hours=float(hours),
        )
    return {
        "enabled": True,
        "innovation": "shift_report_generator",
        "source": "history",
        "run_count": valid_count,
        "report": report,
    }


@app.post("/v1/supplier/record")
def post_supplier_record(req: SupplierRecordRequest) -> dict[str, Any]:
    db_fp = _resolve_innovation_db_path_with_default(req.db_path)
    row_id = save_supplier_record(
        db_path=db_fp,
        supplier_id=req.supplier_id,
        delta_e=float(req.delta_e),
        product=req.product,
        passed=bool(req.passed),
        ts=req.ts,
    )
    with INNOVATION_LOCK:
        row = INNOVATION_ENGINE.supplier.record(
            supplier_id=req.supplier_id,
            delta_e=float(req.delta_e),
            product=req.product,
            passed=bool(req.passed),
            ts=req.ts,
        )
    return {
        "enabled": True,
        "innovation": "supplier_scorecard",
        "recorded": row,
        "persisted": True,
        "row_id": row_id,
        "db_path": str(db_fp),
    }


@app.get("/v1/supplier/scorecard")
def get_supplier_scorecard(supplier_id: str | None = None, db_path: str | None = None) -> dict[str, Any]:
    db_fp = _resolve_innovation_db_path_with_default(db_path)
    with INNOVATION_LOCK:
        supplier_engine = _build_supplier_engine_from_db(db_fp)
        INNOVATION_ENGINE.supplier = supplier_engine
        data = supplier_engine.scorecard(supplier_id=supplier_id)
    return {"enabled": True, "innovation": "supplier_scorecard", "db_path": str(db_fp), **data}


@app.post("/v1/standards/register")
def post_standards_register(req: StandardRegisterRequest) -> dict[str, Any]:
    db_fp = _resolve_innovation_db_path_with_default(req.db_path)
    version = next_standard_version(db_fp, req.code)
    save_standard_version(
        db_path=db_fp,
        code=req.code,
        version=version,
        lab=req.lab.to_dict(),
        source=req.source,
        notes=req.notes,
    )
    with INNOVATION_LOCK:
        library = _build_standard_library_from_db(db_fp)
        INNOVATION_ENGINE.library = library
        current = library.get(code=req.code, version=version)
    return {
        "enabled": True,
        "innovation": "color_standard_library",
        "status": "registered",
        "code": req.code,
        "version": version,
        "db_path": str(db_fp),
        "current": current,
    }


@app.get("/v1/standards/get")
def get_standards_get(code: str, version: int | None = None, db_path: str | None = None) -> dict[str, Any]:
    db_fp = _resolve_innovation_db_path_with_default(db_path)
    with INNOVATION_LOCK:
        library = _build_standard_library_from_db(db_fp)
        INNOVATION_ENGINE.library = library
        result = library.get(code=code, version=version)
    return {"enabled": True, "innovation": "color_standard_library", "db_path": str(db_fp), **result}


@app.post("/v1/standards/compare")
def post_standards_compare(req: StandardCompareRequest) -> dict[str, Any]:
    db_fp = _resolve_innovation_db_path_with_default(req.db_path)
    with INNOVATION_LOCK:
        library = _build_standard_library_from_db(db_fp)
        INNOVATION_ENGINE.library = library
        result = library.compare_to_standard(
            code=req.code,
            measured_lab=req.measured_lab.to_dict(),
            version=req.version,
        )
    return {"enabled": True, "innovation": "color_standard_library", "db_path": str(db_fp), **result}


@app.get("/v1/standards/version-drift")
def get_standards_version_drift(code: str, db_path: str | None = None) -> dict[str, Any]:
    db_fp = _resolve_innovation_db_path_with_default(db_path)
    with INNOVATION_LOCK:
        library = _build_standard_library_from_db(db_fp)
        INNOVATION_ENGINE.library = library
        result = library.version_drift(code=code)
    return {"enabled": True, "innovation": "color_standard_library", "db_path": str(db_fp), **result}


@app.get("/v1/standards/list")
def get_standards_list(db_path: str | None = None) -> dict[str, Any]:
    db_fp = _resolve_innovation_db_path_with_default(db_path)
    with INNOVATION_LOCK:
        library = _build_standard_library_from_db(db_fp)
        INNOVATION_ENGINE.library = library
        result = library.list_all()
    return {"enabled": True, "innovation": "color_standard_library", "db_path": str(db_fp), **result}


def _payload_lab_required(payload: dict[str, Any], key: str) -> dict[str, float]:
    if key not in payload:
        raise HTTPException(status_code=422, detail=f"missing field: {key}")
    return _as_lab(payload.get(key))


def _payload_text_required(payload: dict[str, Any], key: str) -> str:
    value = str(payload.get(key, "")).strip()
    if not value:
        raise HTTPException(status_code=422, detail=f"missing field: {key}")
    return value


@app.get("/v1/mvp2/manifest")
def get_mvp2_manifest() -> dict[str, Any]:
    return {
        "enabled": True,
        "system": "color_film_mvp_v2",
        "modules": [
            "M01 ColorCorrectionEngine",
            "M02 ThreeStepMatcher",
            "M03 DualPipelineAnalyzer",
            "M04 ThreeTierJudgeV2",
            "M05 RecipeAdvisorV2",
            "M06 SessionRecorder",
            "M07 CaptureSOPGenerator",
        ],
        "entrypoints": {
            "run": "/v1/mvp2/pipeline/run",
            "ccm_calibrate": "/v1/mvp2/ccm/calibrate",
            "matcher_evaluate": "/v1/mvp2/matcher/evaluate",
            "matcher_strategy": "/v1/mvp2/matcher/strategy",
            "sop": "/v1/mvp2/sop",
            "sessions": "/v1/mvp2/sessions",
        },
    }


@app.post("/v1/mvp2/pipeline/run")
def post_mvp2_pipeline_run(payload: dict[str, Any]) -> dict[str, Any]:
    ref_grid = payload.get("ref_grid")
    sample_grid = payload.get("sample_grid")
    if not isinstance(ref_grid, list) or not isinstance(sample_grid, list):
        raise HTTPException(status_code=422, detail="ref_grid and sample_grid must be list")
    shape_obj = payload.get("grid_shape", [6, 8])
    if not isinstance(shape_obj, (list, tuple)) or len(shape_obj) != 2:
        raise HTTPException(status_code=422, detail="grid_shape must be [rows, cols]")
    grid_shape = (max(1, int(shape_obj[0])), max(1, int(shape_obj[1])))
    capture_quality = str(payload.get("capture_quality", "GOOD"))
    recipe = payload.get("recipe") if isinstance(payload.get("recipe"), dict) else None
    process_params = payload.get("process_params") if isinstance(payload.get("process_params"), dict) else None
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else None
    with ULTIMATE_LOCK:
        result = MVP2_PIPELINE.run(
            ref_grid=ref_grid,
            sample_grid=sample_grid,
            grid_shape=grid_shape,
            capture_quality=capture_quality,
            recipe=recipe,
            process_params=process_params,
            meta=meta,
        )
    return {"enabled": True, "system": "color_film_mvp_v2", "result": result}


@app.post("/v1/mvp2/ccm/calibrate")
def post_mvp2_ccm_calibrate(payload: dict[str, Any]) -> dict[str, Any]:
    measured = payload.get("measured_rgb_24")
    if not isinstance(measured, list):
        raise HTTPException(status_code=422, detail="measured_rgb_24 must be list with 24 rgb tuples")
    with ULTIMATE_LOCK:
        result = MVP2_PIPELINE.ccm.calibrate(measured)
    return {"enabled": True, "system": "color_film_mvp_v2", "result": result}


@app.post("/v1/mvp2/matcher/evaluate")
def post_mvp2_matcher_evaluate(payload: dict[str, Any]) -> dict[str, Any]:
    match_result = payload.get("match_result")
    if not isinstance(match_result, dict):
        raise HTTPException(status_code=422, detail="match_result must be object")
    with ULTIMATE_LOCK:
        result = MVP2_PIPELINE.matcher.evaluate_match(match_result)
    return {"enabled": True, "system": "color_film_mvp_v2", "result": result}


@app.post("/v1/mvp2/matcher/strategy")
def post_mvp2_matcher_strategy(payload: dict[str, Any]) -> dict[str, Any]:
    scene = payload.get("scene")
    if not isinstance(scene, dict):
        raise HTTPException(status_code=422, detail="scene must be object")
    with ULTIMATE_LOCK:
        result = MVP2_PIPELINE.matcher.suggest_strategy(scene)
    return {"enabled": True, "system": "color_film_mvp_v2", "result": result}


@app.get("/v1/mvp2/sop")
def get_mvp2_sop(product_type: str = "decorative_film") -> dict[str, Any]:
    with ULTIMATE_LOCK:
        result = MVP2_PIPELINE.sop.generate(product_type=product_type)
    return {"enabled": True, "system": "color_film_mvp_v2", "result": result}


@app.get("/v1/mvp2/sessions")
def get_mvp2_sessions(product: str | None = None, last_n: int = 20) -> dict[str, Any]:
    with ULTIMATE_LOCK:
        rows = MVP2_PIPELINE.recorder.history(product=product, last_n=max(1, int(last_n)))
    return {"enabled": True, "system": "color_film_mvp_v2", "count": len(rows), "rows": rows}


@app.get("/v1/lifecycle/manifest")
def get_lifecycle_manifest() -> dict[str, Any]:
    return {
        "enabled": True,
        "system": "ultimate_color_film_system",
        "module_range": "M08-M45",
        "modules": [
            "M08 EnvironmentCompensator",
            "M09 SubstrateAnalyzer",
            "M10 WetToDryPredictor",
            "M11 PrintRunMonitor",
            "M12 CrossBatchMatcher",
            "M13 InkLotTracker",
            "M14 AutoCalibrationGuard",
            "M15 EdgeEffectAnalyzer",
            "M16 RollerLifeTracker",
            "M17 GoldenSampleManager",
            "M18 OperatorSkillTracker",
            "M19 FullLifecycleTracker",
            "M20 TimeStabilityManager",
            "M21 ProcessCouplingRiskEngine",
            "M22 FilmAppearanceRiskEngine",
            "M23 CustomerScenarioEngine",
            "M24 RetestDisputeManager",
            "M25 MultiMachineConsistencyEngine",
            "M26 LearningLoopEngine",
            "M27 LifecycleRuleCenter",
            "M28 AutoBoundaryArbitration",
            "M29 BusinessDispositionPlanner",
            "M30 IntegratedLifecycleAssessment",
            "M31 ReportFactory",
            "M32 DataIntegrityGuard",
            "M33 MeasurementSystemGuard(MSA)",
            "M34 SPCMonitor",
            "M35 MetamerismRiskEngine",
            "M36 PostProcessImpactPredictor",
            "M37 StorageTransportStabilityPredictor",
            "M38 LifecycleStateMachine",
            "M39 FailureModeRegistry",
            "M40 AlertCenter",
            "M41 RollLifecycleTracker",
            "M42 RuleImpactSimulator",
            "M43 QualityCaseCenter",
            "M44 RoleViewBuilder",
            "M45 BatchRuleImpactSimulator",
        ],
        "entrypoints": {
            "preflight": "/v1/lifecycle/preflight-check",
            "environment_check": "/v1/lifecycle/environment/check",
            "substrate_compare": "/v1/lifecycle/substrate/compare",
            "wet_dry_predict": "/v1/lifecycle/wet-dry/predict",
            "run_monitor_report": "/v1/lifecycle/run-monitor/report",
            "operator_leaderboard": "/v1/lifecycle/operator/leaderboard",
            "trace_chain": "/v1/lifecycle/trace/chain",
            "integrated_assessment": "/v1/lifecycle/decision/integrated",
            "advanced_manifest": "/v1/lifecycle/advanced/manifest",
            "msa_report": "/v1/lifecycle/msa/report",
            "spc_report": "/v1/lifecycle/spc/report",
            "state_snapshot": "/v1/lifecycle/state/snapshot",
            "roll_summary": "/v1/lifecycle/roll/summary",
            "rule_simulation": "/v1/lifecycle/decision/simulate-rules",
            "case_list": "/v1/lifecycle/case/list",
            "case_sla_report": "/v1/lifecycle/case/sla-report",
            "case_store_status": "/v1/lifecycle/case/store-status",
            "case_store_check": "/v1/lifecycle/case/store-check",
            "role_view": "/v1/lifecycle/decision/role-view",
        },
    }


@app.post("/v1/lifecycle/preflight-check")
def post_lifecycle_preflight_check(payload: dict[str, Any]) -> dict[str, Any]:
    temp = float(payload.get("temp", 25.0))
    humidity = float(payload.get("humidity", 50.0))
    operator = payload.get("operator")
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.pre_flight_check(temp=temp, humidity=humidity, operator=operator)
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.post("/v1/lifecycle/environment/record")
def post_lifecycle_environment_record(payload: dict[str, Any]) -> dict[str, Any]:
    temp = float(payload.get("temp", 25.0))
    humidity = float(payload.get("humidity", 50.0))
    led_hours = payload.get("led_hours")
    led_hours_num = float(led_hours) if led_hours is not None else None
    with ULTIMATE_LOCK:
        ULTIMATE_SYSTEM.env.record_conditions(temp=temp, humidity=humidity, led_hours=led_hours_num)
    return {"enabled": True, "recorded": True, "temp": temp, "humidity": humidity, "led_hours": led_hours_num}


@app.post("/v1/lifecycle/environment/check")
def post_lifecycle_environment_check(payload: dict[str, Any]) -> dict[str, Any]:
    temp = float(payload.get("temp", 25.0))
    humidity = float(payload.get("humidity", 50.0))
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.env.check_environment(temp=temp, humidity=humidity)
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.post("/v1/lifecycle/environment/compensate")
def post_lifecycle_environment_compensate(payload: dict[str, Any]) -> dict[str, Any]:
    lab = _payload_lab_required(payload, "lab")
    temp = float(payload.get("temp", 25.0))
    humidity = float(payload.get("humidity", 50.0))
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.env.compensate_lab(lab=lab, temp=temp, humidity=humidity)
    return {"enabled": True, "system": "ultimate_color_film_system", "input_lab": lab, "result": result}


@app.post("/v1/lifecycle/substrate/register")
def post_lifecycle_substrate_register(payload: dict[str, Any]) -> dict[str, Any]:
    lot_id = _payload_text_required(payload, "lot_id")
    lab = _payload_lab_required(payload, "lab")
    supplier = str(payload.get("supplier", ""))
    material = str(payload.get("material", "pvc"))
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.substrate.register_lot(lot_id=lot_id, lab=lab, supplier=supplier, material=material)
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.post("/v1/lifecycle/substrate/compare")
def post_lifecycle_substrate_compare(payload: dict[str, Any]) -> dict[str, Any]:
    lot_id = _payload_text_required(payload, "lot_id")
    ref_lot_id = payload.get("ref_lot_id")
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.substrate.compare_to_reference(lot_id=lot_id, ref_lot_id=ref_lot_id)
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.post("/v1/lifecycle/wet-dry/predict")
def post_lifecycle_wet_dry_predict(payload: dict[str, Any]) -> dict[str, Any]:
    wet_lab = _payload_lab_required(payload, "wet_lab")
    ink_type = str(payload.get("ink_type", "solvent_gravure"))
    elapsed_hours = float(payload.get("elapsed_hours", 0.0))
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.wet_dry.predict_dry_lab(wet_lab=wet_lab, ink_type=ink_type, elapsed_hours=elapsed_hours)
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.post("/v1/lifecycle/wet-dry/learn")
def post_lifecycle_wet_dry_learn(payload: dict[str, Any]) -> dict[str, Any]:
    wet_lab = _payload_lab_required(payload, "wet_lab")
    dry_lab = _payload_lab_required(payload, "dry_lab")
    ink_type = str(payload.get("ink_type", "solvent_gravure"))
    dry_hours = float(payload.get("dry_hours", 4.0))
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.wet_dry.learn(wet_lab=wet_lab, dry_lab=dry_lab, ink_type=ink_type, dry_hours=dry_hours)
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.post("/v1/lifecycle/run-monitor/target")
def post_lifecycle_run_monitor_target(payload: dict[str, Any]) -> dict[str, Any]:
    target_lab = _payload_lab_required(payload, "target_lab")
    tolerance = float(payload.get("tolerance", 2.5))
    with ULTIMATE_LOCK:
        ULTIMATE_SYSTEM.run_monitor.set_target(lab=target_lab, tolerance=tolerance)
    return {"enabled": True, "target_set": True, "target_lab": target_lab, "tolerance": tolerance}


@app.post("/v1/lifecycle/run-monitor/add-sample")
def post_lifecycle_run_monitor_add_sample(payload: dict[str, Any]) -> dict[str, Any]:
    lab = _payload_lab_required(payload, "lab")
    seq_raw = payload.get("seq")
    seq = int(seq_raw) if seq_raw is not None else None
    timestamp_raw = payload.get("timestamp")
    timestamp = float(timestamp_raw) if timestamp_raw is not None else None
    meter_pos_raw = payload.get("meter_position")
    meter_position = float(meter_pos_raw) if meter_pos_raw is not None else None
    roll_id = str(payload.get("roll_id", ""))
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.run_monitor.add_sample(
            lab=lab,
            seq=seq,
            timestamp=timestamp,
            meter_position=meter_position,
            roll_id=roll_id,
        )
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.get("/v1/lifecycle/run-monitor/report")
def get_lifecycle_run_monitor_report() -> dict[str, Any]:
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.run_monitor.get_report()
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.post("/v1/lifecycle/roll/register")
def post_lifecycle_roll_register(payload: dict[str, Any]) -> dict[str, Any]:
    lot_id = _payload_text_required(payload, "lot_id")
    roll_id = _payload_text_required(payload, "roll_id")
    length_m = float(payload.get("length_m", 1.0))
    parent_roll_id_raw = payload.get("parent_roll_id")
    parent_roll_id = str(parent_roll_id_raw) if parent_roll_id_raw is not None else None
    rework_of_raw = payload.get("rework_of")
    rework_of = str(rework_of_raw) if rework_of_raw is not None else None
    machine_id = str(payload.get("machine_id", ""))
    shift = str(payload.get("shift", ""))
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.register_roll(
            lot_id=lot_id,
            roll_id=roll_id,
            length_m=length_m,
            parent_roll_id=parent_roll_id,
            rework_of=rework_of,
            machine_id=machine_id,
            shift=shift,
        )
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.post("/v1/lifecycle/roll/mark-zone")
def post_lifecycle_roll_mark_zone(payload: dict[str, Any]) -> dict[str, Any]:
    roll_id = _payload_text_required(payload, "roll_id")
    zone_type = _payload_text_required(payload, "zone_type")
    meter_start = float(payload.get("meter_start", 0.0))
    meter_end = float(payload.get("meter_end", 0.0))
    reason = str(payload.get("reason", ""))
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.mark_roll_zone(
            roll_id=roll_id,
            zone_type=zone_type,
            meter_start=meter_start,
            meter_end=meter_end,
            reason=reason,
        )
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.post("/v1/lifecycle/roll/add-measurement")
def post_lifecycle_roll_add_measurement(payload: dict[str, Any]) -> dict[str, Any]:
    roll_id = _payload_text_required(payload, "roll_id")
    meter_pos = float(payload.get("meter_pos", 0.0))
    de = float(payload.get("de", 0.0))
    lab_raw = payload.get("lab")
    lab = lab_raw if isinstance(lab_raw, dict) else None
    source = str(payload.get("source", ""))
    ts_raw = payload.get("timestamp")
    ts = float(ts_raw) if ts_raw is not None else None
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.add_roll_measurement(
            roll_id=roll_id,
            meter_pos=meter_pos,
            de=de,
            lab=lab,
            source=source,
            ts=ts,
        )
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.get("/v1/lifecycle/roll/summary")
def get_lifecycle_roll_summary(roll_id: str) -> dict[str, Any]:
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.get_roll_summary(roll_id=roll_id)
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.get("/v1/lifecycle/roll/lot-summary")
def get_lifecycle_roll_lot_summary(lot_id: str) -> dict[str, Any]:
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.get_lot_roll_summary(lot_id=lot_id)
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.post("/v1/lifecycle/cross-batch/register")
def post_lifecycle_cross_batch_register(payload: dict[str, Any]) -> dict[str, Any]:
    batch_id = _payload_text_required(payload, "batch_id")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise HTTPException(status_code=422, detail="missing field: data")
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.cross_batch.register_batch(batch_id=batch_id, data=data)
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.post("/v1/lifecycle/cross-batch/match")
def post_lifecycle_cross_batch_match(payload: dict[str, Any]) -> dict[str, Any]:
    target_batch_id = _payload_text_required(payload, "target_batch_id")
    current_conditions = payload.get("current_conditions")
    cond = current_conditions if isinstance(current_conditions, dict) else None
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.cross_batch.find_match_recipe(target_batch_id=target_batch_id, current_conditions=cond)
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.post("/v1/lifecycle/ink-lot/register")
def post_lifecycle_ink_lot_register(payload: dict[str, Any]) -> dict[str, Any]:
    ink_model = _payload_text_required(payload, "ink_model")
    lot_id = _payload_text_required(payload, "lot_id")
    lab = _payload_lab_required(payload, "lab")
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.ink_lot.register(ink_model=ink_model, lot_id=lot_id, lab=lab)
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.get("/v1/lifecycle/ink-lot/variation")
def get_lifecycle_ink_lot_variation(ink_model: str) -> dict[str, Any]:
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.ink_lot.lot_variation(ink_model=ink_model)
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.post("/v1/lifecycle/calibration/register")
def post_lifecycle_calibration_register(payload: dict[str, Any]) -> dict[str, Any]:
    source = _payload_text_required(payload, "source")
    interval_hours = float(payload.get("interval_hours", 24.0))
    with ULTIMATE_LOCK:
        ULTIMATE_SYSTEM.cal_guard.register_source(source=source, interval_hours=interval_hours)
    return {"enabled": True, "registered": True, "source": source, "interval_hours": interval_hours}


@app.post("/v1/lifecycle/calibration/record")
def post_lifecycle_calibration_record(payload: dict[str, Any]) -> dict[str, Any]:
    source = _payload_text_required(payload, "source")
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.cal_guard.record_calibration(source=source)
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.get("/v1/lifecycle/calibration/status")
def get_lifecycle_calibration_status() -> dict[str, Any]:
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.cal_guard.check_status()
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.post("/v1/lifecycle/edge/analyze")
def post_lifecycle_edge_analyze(payload: dict[str, Any]) -> dict[str, Any]:
    de_grid = payload.get("de_grid")
    if not isinstance(de_grid, list):
        raise HTTPException(status_code=422, detail="missing field: de_grid")
    shape_obj = payload.get("grid_shape", [6, 8])
    if not isinstance(shape_obj, (list, tuple)) or len(shape_obj) != 2:
        raise HTTPException(status_code=422, detail="grid_shape must be [rows, cols]")
    grid_shape = (max(1, int(shape_obj[0])), max(1, int(shape_obj[1])))
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.edge.analyze(de_grid=de_grid, grid_shape=grid_shape)
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.post("/v1/lifecycle/roller/register")
def post_lifecycle_roller_register(payload: dict[str, Any]) -> dict[str, Any]:
    roller_id = _payload_text_required(payload, "roller_id")
    roller_type = str(payload.get("roller_type", "gravure"))
    max_meters = int(payload.get("max_meters", 500000))
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.roller.register(roller_id=roller_id, roller_type=roller_type, max_meters=max_meters)
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.post("/v1/lifecycle/roller/update")
def post_lifecycle_roller_update(payload: dict[str, Any]) -> dict[str, Any]:
    roller_id = _payload_text_required(payload, "roller_id")
    meters = int(payload.get("meters", 0))
    avg_de_raw = payload.get("avg_de")
    avg_de = float(avg_de_raw) if avg_de_raw is not None else None
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.roller.update_meters(roller_id=roller_id, meters=meters, avg_de=avg_de)
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.get("/v1/lifecycle/roller/status")
def get_lifecycle_roller_status(roller_id: str) -> dict[str, Any]:
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.roller.status(roller_id=roller_id)
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.post("/v1/lifecycle/golden/register")
def post_lifecycle_golden_register(payload: dict[str, Any]) -> dict[str, Any]:
    code = _payload_text_required(payload, "code")
    lab = _payload_lab_required(payload, "lab")
    max_age_days = int(payload.get("max_age_days", 90))
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.golden.register(code=code, lab=lab, max_age_days=max_age_days)
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.post("/v1/lifecycle/golden/check")
def post_lifecycle_golden_check(payload: dict[str, Any]) -> dict[str, Any]:
    code = _payload_text_required(payload, "code")
    measured_lab = _payload_lab_required(payload, "measured_lab")
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.golden.check(code=code, measured_lab=measured_lab)
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.post("/v1/lifecycle/operator/record")
def post_lifecycle_operator_record(payload: dict[str, Any]) -> dict[str, Any]:
    operator = _payload_text_required(payload, "operator")
    attempts = int(payload.get("attempts", 1))
    final_de = float(payload.get("final_de", 0.0))
    target_de = float(payload.get("target_de", 2.5))
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.operator.record_session(
            operator=operator,
            attempts=attempts,
            final_de=final_de,
            target_de=target_de,
        )
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.get("/v1/lifecycle/operator/profile")
def get_lifecycle_operator_profile(operator: str) -> dict[str, Any]:
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.operator.profile(operator=operator)
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.get("/v1/lifecycle/operator/leaderboard")
def get_lifecycle_operator_leaderboard() -> dict[str, Any]:
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.operator.leaderboard()
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.post("/v1/lifecycle/trace/add-event")
def post_lifecycle_trace_add_event(payload: dict[str, Any]) -> dict[str, Any]:
    lot_id = _payload_text_required(payload, "lot_id")
    stage = _payload_text_required(payload, "stage")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise HTTPException(status_code=422, detail="missing field: data")
    event_id_raw = payload.get("event_id")
    event_id = str(event_id_raw) if event_id_raw is not None else None
    actor = str(payload.get("actor", ""))
    links_raw = payload.get("links")
    links = links_raw if isinstance(links_raw, list) else None
    idem_raw = payload.get("idempotency_key")
    idempotency_key = str(idem_raw) if idem_raw is not None else None
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.add_trace_event(
            lot_id=lot_id,
            stage=stage,
            data=data,
            event_id=event_id,
            actor=actor,
            links=links,
            idempotency_key=idempotency_key,
        )
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.get("/v1/lifecycle/trace/chain")
def get_lifecycle_trace_chain(lot_id: str) -> dict[str, Any]:
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.lifecycle.get_chain(lot_id=lot_id)
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.post("/v1/lifecycle/trace/root-cause")
def post_lifecycle_trace_root_cause(payload: dict[str, Any]) -> dict[str, Any]:
    lot_id = _payload_text_required(payload, "lot_id")
    symptom = _payload_text_required(payload, "symptom")
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.lifecycle.find_root_cause(lot_id=lot_id, symptom=symptom)
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.post("/v1/lifecycle/trace/revision")
def post_lifecycle_trace_revision(payload: dict[str, Any]) -> dict[str, Any]:
    lot_id = _payload_text_required(payload, "lot_id")
    target_event_id = _payload_text_required(payload, "target_event_id")
    actor = _payload_text_required(payload, "actor")
    reason = _payload_text_required(payload, "reason")
    patch = payload.get("patch")
    if not isinstance(patch, dict):
        raise HTTPException(status_code=422, detail="missing field: patch")
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.add_trace_revision(
            lot_id=lot_id,
            target_event_id=target_event_id,
            patch=patch,
            actor=actor,
            reason=reason,
        )
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.post("/v1/lifecycle/trace/override")
def post_lifecycle_trace_override(payload: dict[str, Any]) -> dict[str, Any]:
    lot_id = _payload_text_required(payload, "lot_id")
    decision_ref = _payload_text_required(payload, "decision_ref")
    actor = _payload_text_required(payload, "actor")
    approved_by = _payload_text_required(payload, "approved_by")
    reason = _payload_text_required(payload, "reason")
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.add_manual_override_audit(
            lot_id=lot_id,
            decision_ref=decision_ref,
            actor=actor,
            approved_by=approved_by,
            reason=reason,
        )
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.get("/v1/lifecycle/advanced/manifest")
def get_lifecycle_advanced_manifest() -> dict[str, Any]:
    return {
        "enabled": True,
        "system": "ultimate_color_film_system",
        "modules": {
            "time_stability": "/v1/lifecycle/time-stability/*",
            "process_coupling": "/v1/lifecycle/process-coupling/*",
            "appearance": "/v1/lifecycle/appearance/evaluate",
            "metamerism": "/v1/lifecycle/metamerism/evaluate",
            "post_process": "/v1/lifecycle/post-process/evaluate",
            "storage_transport": "/v1/lifecycle/storage/evaluate",
            "customer": "/v1/lifecycle/customer/*",
            "retest": "/v1/lifecycle/retest/*",
            "msa": "/v1/lifecycle/msa/*",
            "spc": "/v1/lifecycle/spc/*",
            "machine": "/v1/lifecycle/machine/*",
            "learning": "/v1/lifecycle/learning/*",
            "state_machine": "/v1/lifecycle/state/*",
            "roll_lifecycle": "/v1/lifecycle/roll/*",
            "failure_modes": "/v1/lifecycle/failure-mode/*",
            "alerts": "/v1/lifecycle/alerts/*",
            "rules": "/v1/lifecycle/rules/*",
            "version_link": "/v1/lifecycle/version-link/*",
            "integrated_decision": "/v1/lifecycle/decision/integrated",
            "decision_replay": "/v1/lifecycle/decision/replay",
            "decision_rule_simulation": "/v1/lifecycle/decision/simulate-rules",
            "decision_rule_batch_simulation": "/v1/lifecycle/decision/simulate-rules-batch",
            "decision_role_view": "/v1/lifecycle/decision/role-view",
            "quality_case_center": "/v1/lifecycle/case/*",
            "reports": "/v1/lifecycle/report/*",
        },
    }


@app.post("/v1/lifecycle/time-stability/record")
def post_lifecycle_time_stability_record(payload: dict[str, Any]) -> dict[str, Any]:
    lot_id = _payload_text_required(payload, "lot_id")
    elapsed_hours = float(payload.get("elapsed_hours", 0.0))
    lab = _payload_lab_required(payload, "lab")
    stage = str(payload.get("stage", "recheck"))
    verdict_raw = payload.get("verdict")
    verdict = str(verdict_raw) if verdict_raw is not None else None
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.record_time_stability(
            lot_id=lot_id,
            elapsed_hours=elapsed_hours,
            lab=lab,
            stage=stage,
            verdict=verdict,
        )
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.get("/v1/lifecycle/time-stability/report")
def get_lifecycle_time_stability_report(lot_id: str) -> dict[str, Any]:
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.get_time_stability_report(lot_id=lot_id)
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.post("/v1/lifecycle/process-coupling/evaluate")
def post_lifecycle_process_coupling_evaluate(payload: dict[str, Any]) -> dict[str, Any]:
    params = payload.get("params")
    if not isinstance(params, dict):
        raise HTTPException(status_code=422, detail="missing field: params")
    route = str(payload.get("route", "gravure"))
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.evaluate_process_coupling(params=params, route=route)
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.post("/v1/lifecycle/process-coupling/reverse-infer")
def post_lifecycle_process_coupling_reverse_infer(payload: dict[str, Any]) -> dict[str, Any]:
    color_symptom = payload.get("color_symptom")
    params = payload.get("params")
    if not isinstance(color_symptom, dict):
        raise HTTPException(status_code=422, detail="missing field: color_symptom")
    if not isinstance(params, dict):
        raise HTTPException(status_code=422, detail="missing field: params")
    route = str(payload.get("route", "gravure"))
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.reverse_infer_process(color_symptom=color_symptom, params=params, route=route)
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.post("/v1/lifecycle/appearance/evaluate")
def post_lifecycle_appearance_evaluate(payload: dict[str, Any]) -> dict[str, Any]:
    lab = _payload_lab_required(payload, "lab")
    film_props = payload.get("film_props")
    if not isinstance(film_props, dict):
        raise HTTPException(status_code=422, detail="missing field: film_props")
    substrate_bases = payload.get("substrate_bases")
    bases = substrate_bases if isinstance(substrate_bases, list) else None
    observer_angles = payload.get("observer_angles")
    angles = observer_angles if isinstance(observer_angles, list) else None
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.evaluate_film_appearance(
            lab=lab,
            film_props=film_props,
            substrate_bases=bases,
            observer_angles=angles,
        )
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.post("/v1/lifecycle/metamerism/evaluate")
def post_lifecycle_metamerism_evaluate(payload: dict[str, Any]) -> dict[str, Any]:
    lab_d65 = _payload_lab_required(payload, "lab_d65")
    alt_lights = payload.get("alt_lights")
    film_props = payload.get("film_props")
    if alt_lights is not None and not isinstance(alt_lights, dict):
        raise HTTPException(status_code=422, detail="alt_lights must be object")
    if film_props is not None and not isinstance(film_props, dict):
        raise HTTPException(status_code=422, detail="film_props must be object")
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.evaluate_metamerism(
            lab_d65=lab_d65,
            alt_lights=alt_lights if isinstance(alt_lights, dict) else None,
            film_props=film_props if isinstance(film_props, dict) else None,
        )
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.post("/v1/lifecycle/post-process/evaluate")
def post_lifecycle_post_process_evaluate(payload: dict[str, Any]) -> dict[str, Any]:
    lab = _payload_lab_required(payload, "lab")
    steps = payload.get("steps")
    context = payload.get("context")
    if steps is not None and not isinstance(steps, list):
        raise HTTPException(status_code=422, detail="steps must be array")
    if context is not None and not isinstance(context, dict):
        raise HTTPException(status_code=422, detail="context must be object")
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.evaluate_post_process_risk(
            lab=lab,
            steps=steps if isinstance(steps, list) else None,
            context=context if isinstance(context, dict) else None,
        )
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.post("/v1/lifecycle/storage/evaluate")
def post_lifecycle_storage_evaluate(payload: dict[str, Any]) -> dict[str, Any]:
    lab = _payload_lab_required(payload, "lab")
    storage_days = float(payload.get("storage_days", 0.0))
    temp_c = float(payload.get("temp_c", 25.0))
    humidity_pct = float(payload.get("humidity_pct", 50.0))
    uv_hours = float(payload.get("uv_hours", 0.0))
    vibration_index = float(payload.get("vibration_index", 0.0))
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.evaluate_storage_transport_risk(
            lab=lab,
            storage_days=storage_days,
            temp_c=temp_c,
            humidity_pct=humidity_pct,
            uv_hours=uv_hours,
            vibration_index=vibration_index,
        )
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.post("/v1/lifecycle/msa/record")
def post_lifecycle_msa_record(payload: dict[str, Any]) -> dict[str, Any]:
    lot_id = _payload_text_required(payload, "lot_id")
    sample_id = _payload_text_required(payload, "sample_id")
    device_id = _payload_text_required(payload, "device_id")
    operator_id = _payload_text_required(payload, "operator_id")
    lab = _payload_lab_required(payload, "lab")
    ts_raw = payload.get("ts")
    ts = float(ts_raw) if ts_raw is not None else None
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.record_measurement_msa(
            lot_id=lot_id,
            sample_id=sample_id,
            device_id=device_id,
            operator_id=operator_id,
            lab=lab,
            ts=ts,
        )
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.get("/v1/lifecycle/msa/report")
def get_lifecycle_msa_report(lot_id: str | None = None, window: int = 500) -> dict[str, Any]:
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.get_msa_report(lot_id=lot_id, window=max(10, int(window)))
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.post("/v1/lifecycle/spc/record")
def post_lifecycle_spc_record(payload: dict[str, Any]) -> dict[str, Any]:
    stream_id = _payload_text_required(payload, "stream_id")
    value = float(payload.get("value", 0.0))
    ts_raw = payload.get("ts")
    ts = float(ts_raw) if ts_raw is not None else None
    meta = payload.get("meta")
    if meta is not None and not isinstance(meta, dict):
        raise HTTPException(status_code=422, detail="meta must be object")
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.record_spc_point(stream_id=stream_id, value=value, ts=ts, meta=meta if isinstance(meta, dict) else None)
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.get("/v1/lifecycle/spc/report")
def get_lifecycle_spc_report(stream_id: str, window: int = 100) -> dict[str, Any]:
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.get_spc_report(stream_id=stream_id, window=max(8, int(window)))
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.post("/v1/lifecycle/customer/register-profile")
def post_lifecycle_customer_register_profile(payload: dict[str, Any]) -> dict[str, Any]:
    customer_id = _payload_text_required(payload, "customer_id")
    profile = payload.get("profile")
    if not isinstance(profile, dict):
        raise HTTPException(status_code=422, detail="missing field: profile")
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.register_customer_profile(customer_id=customer_id, profile=profile)
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.post("/v1/lifecycle/customer/evaluate")
def post_lifecycle_customer_evaluate(payload: dict[str, Any]) -> dict[str, Any]:
    customer_id = _payload_text_required(payload, "customer_id")
    sku = _payload_text_required(payload, "sku")
    scenario = payload.get("scenario")
    metrics = payload.get("metrics")
    if not isinstance(scenario, dict):
        raise HTTPException(status_code=422, detail="missing field: scenario")
    if not isinstance(metrics, dict):
        raise HTTPException(status_code=422, detail="missing field: metrics")
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.evaluate_customer_acceptance(customer_id=customer_id, sku=sku, scenario=scenario, metrics=metrics)
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.post("/v1/lifecycle/retest/record")
def post_lifecycle_retest_record(payload: dict[str, Any]) -> dict[str, Any]:
    lot_id = _payload_text_required(payload, "lot_id")
    test_type = str(payload.get("test_type", "retest"))
    device_id = _payload_text_required(payload, "device_id")
    operator = _payload_text_required(payload, "operator")
    raw_result = payload.get("raw_result")
    compensated_result = payload.get("compensated_result")
    judgment_result = payload.get("judgment_result")
    review_result = payload.get("review_result")
    if not isinstance(raw_result, dict):
        raise HTTPException(status_code=422, detail="missing field: raw_result")
    if compensated_result is not None and not isinstance(compensated_result, dict):
        raise HTTPException(status_code=422, detail="compensated_result must be object")
    if not isinstance(judgment_result, dict):
        raise HTTPException(status_code=422, detail="missing field: judgment_result")
    if review_result is not None and not isinstance(review_result, dict):
        raise HTTPException(status_code=422, detail="review_result must be object")
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.record_retest(
            lot_id=lot_id,
            test_type=test_type,
            device_id=device_id,
            operator=operator,
            raw_result=raw_result,
            compensated_result=compensated_result,
            judgment_result=judgment_result,
            review_result=review_result,
        )
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.get("/v1/lifecycle/retest/dispute-report")
def get_lifecycle_retest_dispute_report(lot_id: str) -> dict[str, Any]:
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.get_dispute_report(lot_id=lot_id)
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.post("/v1/lifecycle/machine/record")
def post_lifecycle_machine_record(payload: dict[str, Any]) -> dict[str, Any]:
    machine_id = _payload_text_required(payload, "machine_id")
    plant_id = str(payload.get("plant_id", "PLANT-UNKNOWN"))
    sku = str(payload.get("sku", "SKU-UNKNOWN"))
    dL = float(payload.get("dL", 0.0))
    da = float(payload.get("da", 0.0))
    db = float(payload.get("db", 0.0))
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.record_machine_bias(machine_id=machine_id, plant_id=plant_id, sku=sku, dL=dL, da=da, db=db)
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.get("/v1/lifecycle/machine/fingerprint")
def get_lifecycle_machine_fingerprint(machine_id: str, sku: str | None = None) -> dict[str, Any]:
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.get_machine_fingerprint(machine_id=machine_id, sku=sku)
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.get("/v1/lifecycle/machine/chronic-bias")
def get_lifecycle_machine_chronic_bias() -> dict[str, Any]:
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.get_chronic_machine_bias_report()
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.post("/v1/lifecycle/learning/record")
def post_lifecycle_learning_record(payload: dict[str, Any]) -> dict[str, Any]:
    context_key = _payload_text_required(payload, "context_key")
    predicted_cause = _payload_text_required(payload, "predicted_cause")
    actual_cause = _payload_text_required(payload, "actual_cause")
    success = bool(payload.get("success", False))
    rule_source = str(payload.get("rule_source", "heuristic"))
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.record_learning_event(
            context_key=context_key,
            predicted_cause=predicted_cause,
            actual_cause=actual_cause,
            success=success,
            rule_source=rule_source,
        )
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.get("/v1/lifecycle/learning/priorities")
def get_lifecycle_learning_priorities(context_key: str) -> dict[str, Any]:
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.get_learning_priorities(context_key=context_key)
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.post("/v1/lifecycle/state/transition")
def post_lifecycle_state_transition(payload: dict[str, Any]) -> dict[str, Any]:
    lot_id = _payload_text_required(payload, "lot_id")
    to_state = _payload_text_required(payload, "to_state")
    actor = _payload_text_required(payload, "actor")
    reason = str(payload.get("reason", ""))
    evidence = payload.get("evidence")
    force = bool(payload.get("force", False))
    if evidence is not None and not isinstance(evidence, dict):
        raise HTTPException(status_code=422, detail="evidence must be object")
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.transition_state(
            lot_id=lot_id,
            to_state=to_state,
            actor=actor,
            reason=reason,
            evidence=evidence if isinstance(evidence, dict) else None,
            force=force,
        )
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.get("/v1/lifecycle/state/snapshot")
def get_lifecycle_state_snapshot(lot_id: str) -> dict[str, Any]:
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.get_state_snapshot(lot_id=lot_id)
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.post("/v1/lifecycle/failure-mode/register")
def post_lifecycle_failure_mode_register(payload: dict[str, Any]) -> dict[str, Any]:
    mode_id = _payload_text_required(payload, "mode_id")
    desc = _payload_text_required(payload, "desc")
    severity = int(payload.get("severity", 5))
    occurrence = int(payload.get("occurrence", 5))
    detectability = int(payload.get("detectability", 5))
    category = str(payload.get("category", "general"))
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.register_failure_mode(
            mode_id=mode_id,
            desc=desc,
            severity=severity,
            occurrence=occurrence,
            detectability=detectability,
            category=category,
        )
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.get("/v1/lifecycle/failure-mode/list")
def get_lifecycle_failure_mode_list() -> dict[str, Any]:
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.list_failure_modes()
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.post("/v1/lifecycle/failure-mode/capa-candidates")
def post_lifecycle_failure_mode_capa_candidates(payload: dict[str, Any]) -> dict[str, Any]:
    triggers = payload.get("triggers")
    if not isinstance(triggers, list):
        raise HTTPException(status_code=422, detail="missing field: triggers")
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.suggest_capa_candidates(triggers=[str(x) for x in triggers])
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.post("/v1/lifecycle/alerts/push")
def post_lifecycle_alerts_push(payload: dict[str, Any]) -> dict[str, Any]:
    alert_type = _payload_text_required(payload, "alert_type")
    severity = str(payload.get("severity", "medium"))
    message = _payload_text_required(payload, "message")
    source = str(payload.get("source", "manual"))
    evidence = payload.get("evidence")
    dedup_key_raw = payload.get("dedup_key")
    dedup_key = str(dedup_key_raw) if dedup_key_raw is not None else None
    if evidence is not None and not isinstance(evidence, dict):
        raise HTTPException(status_code=422, detail="evidence must be object")
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.push_alert(
            alert_type=alert_type,
            severity=severity,
            message=message,
            source=source,
            evidence=evidence if isinstance(evidence, dict) else None,
            dedup_key=dedup_key,
        )
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.get("/v1/lifecycle/alerts/summary")
def get_lifecycle_alerts_summary(last_n: int = 50) -> dict[str, Any]:
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.get_alert_summary(last_n=max(1, int(last_n)))
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.post("/v1/lifecycle/rules/register")
def post_lifecycle_rules_register(payload: dict[str, Any]) -> dict[str, Any]:
    version = _payload_text_required(payload, "version")
    active_from_ts = float(payload.get("active_from_ts", 0.0))
    scope = payload.get("scope")
    params = payload.get("params")
    notes = str(payload.get("notes", ""))
    if scope is not None and not isinstance(scope, dict):
        raise HTTPException(status_code=422, detail="scope must be object")
    if params is not None and not isinstance(params, dict):
        raise HTTPException(status_code=422, detail="params must be object")
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.register_lifecycle_rule_pack(
            version=version,
            active_from_ts=active_from_ts,
            scope=scope if isinstance(scope, dict) else None,
            params=params if isinstance(params, dict) else None,
            notes=notes,
        )
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.get("/v1/lifecycle/rules/list")
def get_lifecycle_rules_list() -> dict[str, Any]:
    with ULTIMATE_LOCK:
        rows = ULTIMATE_SYSTEM.list_lifecycle_rule_packs()
    return {"enabled": True, "system": "ultimate_color_film_system", "count": len(rows), "rows": rows}


@app.post("/v1/lifecycle/version-link/record")
def post_lifecycle_version_link_record(payload: dict[str, Any]) -> dict[str, Any]:
    lot_id = _payload_text_required(payload, "lot_id")
    recipe_code = _payload_text_required(payload, "recipe_code")
    recipe_version = int(payload.get("recipe_version", 1))
    rule_version = _payload_text_required(payload, "rule_version")
    model_version = _payload_text_required(payload, "model_version")
    pipeline_policy_version = str(payload.get("pipeline_policy_version", ""))
    notes = str(payload.get("notes", ""))
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.record_version_link(
            lot_id=lot_id,
            recipe_code=recipe_code,
            recipe_version=recipe_version,
            rule_version=rule_version,
            model_version=model_version,
            pipeline_policy_version=pipeline_policy_version,
            notes=notes,
        )
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.get("/v1/lifecycle/version-link/get")
def get_lifecycle_version_link(lot_id: str) -> dict[str, Any]:
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.get_version_links(lot_id=lot_id)
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.post("/v1/lifecycle/decision/integrated")
def post_lifecycle_decision_integrated(payload: dict[str, Any]) -> dict[str, Any]:
    lot_id = _payload_text_required(payload, "lot_id")
    base_decision = payload.get("base_decision")
    color_metrics = payload.get("color_metrics")
    process_params = payload.get("process_params")
    process_route = str(payload.get("process_route", "gravure"))
    film_props = payload.get("film_props")
    scenario = payload.get("scenario")
    customer_id_raw = payload.get("customer_id")
    customer_id = str(customer_id_raw) if customer_id_raw is not None else None
    sku = str(payload.get("sku", ""))
    current_lab = payload.get("current_lab")
    repeatability_std_raw = payload.get("repeatability_std")
    repeatability_std = float(repeatability_std_raw) if repeatability_std_raw is not None else None
    confidence_raw = payload.get("confidence")
    confidence = float(confidence_raw) if confidence_raw is not None else None
    meta = payload.get("meta")

    if base_decision is not None and not isinstance(base_decision, dict):
        raise HTTPException(status_code=422, detail="base_decision must be object")
    if color_metrics is not None and not isinstance(color_metrics, dict):
        raise HTTPException(status_code=422, detail="color_metrics must be object")
    if process_params is not None and not isinstance(process_params, dict):
        raise HTTPException(status_code=422, detail="process_params must be object")
    if film_props is not None and not isinstance(film_props, dict):
        raise HTTPException(status_code=422, detail="film_props must be object")
    if scenario is not None and not isinstance(scenario, dict):
        raise HTTPException(status_code=422, detail="scenario must be object")
    if meta is not None and not isinstance(meta, dict):
        raise HTTPException(status_code=422, detail="meta must be object")
    if current_lab is not None and not isinstance(current_lab, dict):
        raise HTTPException(status_code=422, detail="current_lab must be object")

    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.integrated_assessment(
            lot_id=lot_id,
            base_decision=base_decision if isinstance(base_decision, dict) else None,
            color_metrics=color_metrics if isinstance(color_metrics, dict) else None,
            process_params=process_params if isinstance(process_params, dict) else None,
            process_route=process_route,
            film_props=film_props if isinstance(film_props, dict) else None,
            scenario=scenario if isinstance(scenario, dict) else None,
            customer_id=customer_id,
            sku=sku,
            current_lab=current_lab if isinstance(current_lab, dict) else None,
            repeatability_std=repeatability_std,
            confidence=confidence,
            meta=meta if isinstance(meta, dict) else None,
            spc_stream_id=str(payload.get("spc_stream_id", "")) or None,
            alt_light_labs=payload.get("alt_light_labs") if isinstance(payload.get("alt_light_labs"), dict) else None,
            post_process_steps=payload.get("post_process_steps") if isinstance(payload.get("post_process_steps"), list) else None,
            storage_context=payload.get("storage_context") if isinstance(payload.get("storage_context"), dict) else None,
        )
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.get("/v1/lifecycle/decision/snapshots")
def get_lifecycle_decision_snapshots(lot_id: str | None = None, last_n: int = 20) -> dict[str, Any]:
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.list_assessment_snapshots(lot_id=lot_id, last_n=max(1, int(last_n)))
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.post("/v1/lifecycle/decision/replay")
def post_lifecycle_decision_replay(payload: dict[str, Any]) -> dict[str, Any]:
    snapshot_id = _payload_text_required(payload, "snapshot_id")
    force_rule = payload.get("force_lifecycle_rule_version")
    force_ver = str(force_rule) if force_rule is not None else None
    meta_patch = payload.get("meta_patch")
    if meta_patch is not None and not isinstance(meta_patch, dict):
        raise HTTPException(status_code=422, detail="meta_patch must be object")
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.replay_assessment(
            snapshot_id=snapshot_id,
            force_lifecycle_rule_version=force_ver,
            meta_patch=meta_patch if isinstance(meta_patch, dict) else None,
        )
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.post("/v1/lifecycle/decision/simulate-rules")
def post_lifecycle_decision_simulate_rules(payload: dict[str, Any]) -> dict[str, Any]:
    snapshot_id = _payload_text_required(payload, "snapshot_id")
    versions = payload.get("rule_versions")
    if not isinstance(versions, list):
        raise HTTPException(status_code=422, detail="missing field: rule_versions")
    meta_patch = payload.get("meta_patch")
    if meta_patch is not None and not isinstance(meta_patch, dict):
        raise HTTPException(status_code=422, detail="meta_patch must be object")
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.simulate_rule_impact(
            snapshot_id=snapshot_id,
            rule_versions=[str(x) for x in versions],
            meta_patch=meta_patch if isinstance(meta_patch, dict) else None,
        )
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.post("/v1/lifecycle/decision/simulate-rules-batch")
def post_lifecycle_decision_simulate_rules_batch(payload: dict[str, Any]) -> dict[str, Any]:
    snapshot_ids = payload.get("snapshot_ids")
    rule_versions = payload.get("rule_versions")
    if not isinstance(snapshot_ids, list):
        raise HTTPException(status_code=422, detail="missing field: snapshot_ids")
    if not isinstance(rule_versions, list):
        raise HTTPException(status_code=422, detail="missing field: rule_versions")
    meta_patch = payload.get("meta_patch")
    if meta_patch is not None and not isinstance(meta_patch, dict):
        raise HTTPException(status_code=422, detail="meta_patch must be object")
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.simulate_rule_impact_batch(
            snapshot_ids=[str(x) for x in snapshot_ids],
            rule_versions=[str(x) for x in rule_versions],
            meta_patch=meta_patch if isinstance(meta_patch, dict) else None,
        )
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.post("/v1/lifecycle/decision/role-view")
def post_lifecycle_decision_role_view(payload: dict[str, Any]) -> dict[str, Any]:
    role = _payload_text_required(payload, "role")
    assessment = payload.get("assessment")
    if not isinstance(assessment, dict):
        raise HTTPException(status_code=422, detail="missing field: assessment")
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.build_role_view(role=role, assessment=assessment)
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.post("/v1/lifecycle/case/open")
def post_lifecycle_case_open(payload: dict[str, Any]) -> dict[str, Any]:
    lot_id = _payload_text_required(payload, "lot_id")
    case_type = str(payload.get("case_type", "nonconformance"))
    issue = _payload_text_required(payload, "issue")
    severity = str(payload.get("severity", "high"))
    source = str(payload.get("source", "manual"))
    created_by = str(payload.get("created_by", "system"))
    linked_snapshot_id_raw = payload.get("linked_snapshot_id")
    linked_snapshot_id = str(linked_snapshot_id_raw) if linked_snapshot_id_raw is not None else None
    linked_decision_code_raw = payload.get("linked_decision_code")
    linked_decision_code = str(linked_decision_code_raw) if linked_decision_code_raw is not None else None
    dedup_key_raw = payload.get("dedup_key")
    dedup_key = str(dedup_key_raw) if dedup_key_raw is not None else None
    metadata = payload.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        raise HTTPException(status_code=422, detail="metadata must be object")
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.open_quality_case(
            lot_id=lot_id,
            case_type=case_type,
            issue=issue,
            severity=severity,
            source=source,
            created_by=created_by,
            linked_snapshot_id=linked_snapshot_id,
            linked_decision_code=linked_decision_code,
            dedup_key=dedup_key,
            metadata=metadata if isinstance(metadata, dict) else None,
        )
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.post("/v1/lifecycle/case/action")
def post_lifecycle_case_action(payload: dict[str, Any]) -> dict[str, Any]:
    case_id = _payload_text_required(payload, "case_id")
    action_type = _payload_text_required(payload, "action_type")
    owner = _payload_text_required(payload, "owner")
    description = _payload_text_required(payload, "description")
    actor = str(payload.get("actor", "system"))
    due_ts_raw = payload.get("due_ts")
    due_ts = float(due_ts_raw) if due_ts_raw is not None else None
    priority_raw = payload.get("priority", 2)
    priority = int(priority_raw)
    mandatory_raw = payload.get("mandatory", True)
    mandatory = bool(mandatory_raw)
    if isinstance(mandatory_raw, str):
        mandatory = mandatory_raw.strip().lower() not in {"0", "false", "no", "off"}
    extra = payload.get("payload")
    if extra is not None and not isinstance(extra, dict):
        raise HTTPException(status_code=422, detail="payload must be object")
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.add_case_action(
            case_id=case_id,
            action_type=action_type,
            owner=owner,
            description=description,
            actor=actor,
            due_ts=due_ts,
            priority=priority,
            mandatory=mandatory,
            payload=extra if isinstance(extra, dict) else None,
        )
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.post("/v1/lifecycle/case/action/complete")
def post_lifecycle_case_action_complete(payload: dict[str, Any]) -> dict[str, Any]:
    case_id = _payload_text_required(payload, "case_id")
    action_id = _payload_text_required(payload, "action_id")
    actor = _payload_text_required(payload, "actor")
    result_payload = payload.get("result")
    if result_payload is not None and not isinstance(result_payload, dict):
        raise HTTPException(status_code=422, detail="result must be object")
    effectiveness_raw = payload.get("effectiveness")
    effectiveness = float(effectiveness_raw) if effectiveness_raw is not None else None
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.complete_case_action(
            case_id=case_id,
            action_id=action_id,
            actor=actor,
            result=result_payload if isinstance(result_payload, dict) else None,
            effectiveness=effectiveness,
        )
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.post("/v1/lifecycle/case/transition")
def post_lifecycle_case_transition(payload: dict[str, Any]) -> dict[str, Any]:
    case_id = _payload_text_required(payload, "case_id")
    to_state = _payload_text_required(payload, "to_state")
    actor = str(payload.get("actor", "system"))
    reason = str(payload.get("reason", ""))
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.transition_case(case_id=case_id, to_state=to_state, actor=actor, reason=reason)
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.post("/v1/lifecycle/case/waiver")
def post_lifecycle_case_waiver(payload: dict[str, Any]) -> dict[str, Any]:
    case_id = _payload_text_required(payload, "case_id")
    actor = _payload_text_required(payload, "actor")
    approved_by = _payload_text_required(payload, "approved_by")
    reason = _payload_text_required(payload, "reason")
    approver_role = str(payload.get("approver_role", "quality_manager"))
    risk_level_raw = payload.get("risk_level")
    risk_level = str(risk_level_raw) if risk_level_raw is not None else None
    customer_tier = str(payload.get("customer_tier", "standard"))
    waiver_type = str(payload.get("waiver_type", "release_with_risk"))
    expiry_ts_raw = payload.get("expiry_ts")
    expiry_ts = float(expiry_ts_raw) if expiry_ts_raw is not None else None
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.add_case_waiver(
            case_id=case_id,
            actor=actor,
            approved_by=approved_by,
            reason=reason,
            approver_role=approver_role,
            risk_level=risk_level,
            customer_tier=customer_tier,
            waiver_type=waiver_type,
            expiry_ts=expiry_ts,
        )
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.post("/v1/lifecycle/case/close")
def post_lifecycle_case_close(payload: dict[str, Any]) -> dict[str, Any]:
    case_id = _payload_text_required(payload, "case_id")
    actor = _payload_text_required(payload, "actor")
    verification = payload.get("verification")
    if verification is not None and not isinstance(verification, dict):
        raise HTTPException(status_code=422, detail="verification must be object")
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.close_quality_case(
            case_id=case_id,
            actor=actor,
            verification=verification if isinstance(verification, dict) else None,
        )
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.get("/v1/lifecycle/case/get")
def get_lifecycle_case_get(case_id: str) -> dict[str, Any]:
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.get_quality_case(case_id=case_id)
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.get("/v1/lifecycle/case/list")
def get_lifecycle_case_list(lot_id: str | None = None, state: str | None = None, last_n: int = 100) -> dict[str, Any]:
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.list_quality_cases(lot_id=lot_id, state=state, last_n=max(1, int(last_n)))
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.get("/v1/lifecycle/case/sla-report")
def get_lifecycle_case_sla_report(
    lot_id: str | None = None,
    case_id: str | None = None,
    now_ts: float | None = None,
) -> dict[str, Any]:
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.get_case_sla_report(lot_id=lot_id, case_id=case_id, now_ts=now_ts)
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.get("/v1/lifecycle/case/store-status")
def get_lifecycle_case_store_status() -> dict[str, Any]:
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.get_case_store_status()
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.get("/v1/lifecycle/case/store-check")
def get_lifecycle_case_store_check() -> dict[str, Any]:
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.get_case_store_consistency()
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.post("/v1/lifecycle/report/release")
def post_lifecycle_report_release(payload: dict[str, Any]) -> dict[str, Any]:
    lot_id = _payload_text_required(payload, "lot_id")
    assessment = payload.get("assessment")
    metrics = payload.get("metrics")
    audience = str(payload.get("audience", "internal"))
    if not isinstance(assessment, dict):
        raise HTTPException(status_code=422, detail="missing field: assessment")
    if not isinstance(metrics, dict):
        raise HTTPException(status_code=422, detail="missing field: metrics")
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.generate_release_report(lot_id=lot_id, assessment=assessment, metrics=metrics, audience=audience)
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.post("/v1/lifecycle/report/complaint")
def post_lifecycle_report_complaint(payload: dict[str, Any]) -> dict[str, Any]:
    lot_id = _payload_text_required(payload, "lot_id")
    symptom = _payload_text_required(payload, "symptom")
    severity = str(payload.get("severity", "medium"))
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.generate_complaint_summary(lot_id=lot_id, symptom=symptom, severity=severity)
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.get("/v1/lifecycle/known-boundaries")
def get_lifecycle_known_boundaries() -> dict[str, Any]:
    with ULTIMATE_LOCK:
        result = ULTIMATE_SYSTEM.known_boundaries()
    return {"enabled": True, "system": "ultimate_color_film_system", "result": result}


@app.post("/v1/strategy/champion-challenger")
def post_strategy_champion_challenger(req: ChampionChallengerRequest) -> dict[str, Any]:
    db_path = Path(req.db_path)
    if not db_path.exists():
        raise HTTPException(status_code=404, detail=f"db not found: {req.db_path}")
    champion_path = Path(req.champion_policy_config) if req.champion_policy_config else None
    challenger_path = Path(req.challenger_policy_config) if req.challenger_policy_config else None
    if champion_path is not None and not champion_path.exists():
        raise HTTPException(status_code=400, detail=f"champion policy config not found: {req.champion_policy_config}")
    if challenger_path is not None and not challenger_path.exists():
        raise HTTPException(status_code=400, detail=f"challenger policy config not found: {req.challenger_policy_config}")
    return champion_challenger_rollout(
        db_path=db_path,
        line_id=req.line_id,
        product_code=req.product_code,
        lot_id=req.lot_id,
        window=max(40, int(req.window)),
        champion_policy_config=champion_path,
        challenger_policy_config=challenger_path,
        challenger_patch=req.challenger_patch,
        canary_ratio=float(req.canary_ratio),
        phase_days=int(req.phase_days),
    )


@app.get("/v1/policy/customer-tier")
def get_policy_customer_tier(
    customer_tier: str | None = None,
    customer_id: str | None = None,
    customer_tier_config: str | None = None,
    decision_policy_config: str | None = None,
) -> dict[str, Any]:
    tier_cfg_path = _resolve_customer_tier_config(customer_tier_config)
    tier_cfg, tier_source = load_customer_tier_config(tier_cfg_path)
    decision_cfg = _resolve_decision_policy_config(enabled=True, explicit_path=decision_policy_config)
    base_policy, base_source = load_decision_policy(decision_cfg)
    applied = apply_customer_tier_to_policy(
        base_policy=base_policy,
        customer_tier_config=tier_cfg,
        customer_tier=customer_tier,
        customer_id=customer_id,
    )
    return {
        "enabled": True,
        "tier_source": tier_source,
        "base_policy_source": base_source,
        "tier": applied.get("tier"),
        "tier_description": applied.get("tier_description"),
        "patch": applied.get("patch"),
        "resolved_policy": applied.get("policy"),
    }


@app.get("/v1/history/overview")
def get_history_overview(
    db_path: str,
    line_id: str | None = None,
    product_code: str | None = None,
    lot_id: str | None = None,
    window: int = 200,
) -> dict[str, Any]:
    path = Path(db_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"db not found: {db_path}")
    return history_overview(
        db_path=path,
        line_id=line_id,
        product_code=product_code,
        lot_id=lot_id,
        window=max(1, int(window)),
    )


@app.get("/v1/history/early-warning")
def get_history_early_warning(
    db_path: str,
    line_id: str | None = None,
    product_code: str | None = None,
    lot_id: str | None = None,
    window: int = 300,
) -> dict[str, Any]:
    path = Path(db_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"db not found: {db_path}")
    result = complaint_early_warning(
        db_path=path,
        line_id=line_id,
        product_code=product_code,
        lot_id=lot_id,
        window=max(50, int(window)),
    )
    level = str(result.get("risk_level", "")).lower()
    if level in {"orange", "red"}:
        _emit_alert(
            level="error" if level == "red" else "warning",
            key=f"early-warning::{line_id or '-'}::{product_code or '-'}::{lot_id or '-'}::{level}",
            title="Complaint early warning elevated",
            payload={
                "risk_level": result.get("risk_level"),
                "complaint_prob_7d": result.get("complaint_prob_7d"),
                "complaint_prob_30d": result.get("complaint_prob_30d"),
                "line_id": line_id,
                "product_code": product_code,
                "lot_id": lot_id,
                "db_path": db_path,
            },
        )
    return result


@app.get("/v1/history/outcomes")
def get_history_outcomes(
    db_path: str,
    line_id: str | None = None,
    product_code: str | None = None,
    lot_id: str | None = None,
    outcome: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    path = Path(db_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"db not found: {db_path}")
    rows = list_outcomes(
        db_path=path,
        line_id=line_id,
        product_code=product_code,
        lot_id=lot_id,
        outcome=outcome,
        limit=max(1, int(limit)),
    )
    return {"count": len(rows), "rows": rows}


@app.get("/v1/history/outcome-kpis")
def get_history_outcome_kpis(
    db_path: str,
    line_id: str | None = None,
    product_code: str | None = None,
    lot_id: str | None = None,
    window: int = 200,
) -> dict[str, Any]:
    path = Path(db_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"db not found: {db_path}")
    return outcome_kpis(
        db_path=path,
        line_id=line_id,
        product_code=product_code,
        lot_id=lot_id,
        window=max(1, int(window)),
    )


@app.get("/v1/history/policy-recommendation")
def get_history_policy_recommendation(
    db_path: str,
    line_id: str | None = None,
    product_code: str | None = None,
    lot_id: str | None = None,
    window: int = 200,
    policy_config: str | None = None,
) -> dict[str, Any]:
    path = Path(db_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"db not found: {db_path}")
    rec = recommend_policy_adjustments(
        db_path=path,
        line_id=line_id,
        product_code=product_code,
        lot_id=lot_id,
        window=max(1, int(window)),
    )
    try:
        policy_path = Path(policy_config) if policy_config else None
        if policy_path is not None and not policy_path.exists():
            raise HTTPException(status_code=400, detail=f"policy config not found: {policy_config}")
        base_policy, source = load_decision_policy(policy_path)
        rec["base_policy_source"] = source
        rec["suggested_policy"] = apply_policy_patch(base_policy, rec.get("policy_patch", {}))
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001
        pass
    return rec


@app.get("/v1/history/policy-lab")
def get_history_policy_lab(
    db_path: str,
    line_id: str | None = None,
    product_code: str | None = None,
    lot_id: str | None = None,
    window: int = 250,
    policy_config: str | None = None,
) -> dict[str, Any]:
    path = Path(db_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"db not found: {db_path}")
    policy_path = Path(policy_config) if policy_config else None
    if policy_path is not None and not policy_path.exists():
        raise HTTPException(status_code=400, detail=f"policy config not found: {policy_config}")
    return run_policy_lab(
        db_path=path,
        line_id=line_id,
        product_code=product_code,
        lot_id=lot_id,
        window=max(30, int(window)),
        policy_config=policy_path,
    )


@app.get("/v1/history/counterfactual-twin")
def get_history_counterfactual_twin(
    db_path: str,
    line_id: str | None = None,
    product_code: str | None = None,
    lot_id: str | None = None,
    window: int = 260,
    policy_config: str | None = None,
    max_scenarios: int = 260,
) -> dict[str, Any]:
    path = Path(db_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"db not found: {db_path}")
    policy_path = Path(policy_config) if policy_config else None
    if policy_path is not None and not policy_path.exists():
        raise HTTPException(status_code=400, detail=f"policy config not found: {policy_config}")
    return run_counterfactual_twin(
        db_path=path,
        line_id=line_id,
        product_code=product_code,
        lot_id=lot_id,
        window=max(30, int(window)),
        policy_config=policy_path,
        max_scenarios=max(30, int(max_scenarios)),
    )


@app.get("/v1/history/open-bandit-policy")
def get_history_open_bandit_policy(
    db_path: str,
    line_id: str | None = None,
    product_code: str | None = None,
    lot_id: str | None = None,
    window: int = 360,
    policy_config: str | None = None,
    alpha: float = 0.35,
    avg_ratio: float | None = None,
    p95_ratio: float | None = None,
    confidence: float | None = None,
    decision_risk: float | None = None,
) -> dict[str, Any]:
    path = Path(db_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"db not found: {db_path}")
    policy_path = Path(policy_config) if policy_config else None
    if policy_path is not None and not policy_path.exists():
        raise HTTPException(status_code=400, detail=f"policy config not found: {policy_config}")
    return recommend_open_bandit_policy(
        db_path=path,
        line_id=line_id,
        product_code=product_code,
        lot_id=lot_id,
        window=max(60, int(window)),
        policy_config=policy_path,
        alpha=float(alpha),
        avg_ratio=avg_ratio,
        p95_ratio=p95_ratio,
        confidence=confidence,
        decision_risk=decision_risk,
    )


@app.get("/v1/history/executive")
def get_history_executive(
    db_path: str,
    line_id: str | None = None,
    product_code: str | None = None,
    lot_id: str | None = None,
    window: int = 200,
) -> dict[str, Any]:
    path = Path(db_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"db not found: {db_path}")
    return executive_kpis(
        db_path=path,
        line_id=line_id,
        product_code=product_code,
        lot_id=lot_id,
        window=max(1, int(window)),
    )


@app.get("/v1/history/executive-export")
def get_history_executive_export(
    db_path: str,
    line_id: str | None = None,
    product_code: str | None = None,
    lot_id: str | None = None,
    window: int = 200,
) -> PlainTextResponse:
    path = Path(db_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"db not found: {db_path}")
    safe_window = max(1, int(window))
    executive = executive_kpis(
        db_path=path,
        line_id=line_id,
        product_code=product_code,
        lot_id=lot_id,
        window=safe_window,
    )
    early = complaint_early_warning(
        db_path=path,
        line_id=line_id,
        product_code=product_code,
        lot_id=lot_id,
        window=max(20, safe_window),
    )
    outcomes = outcome_kpis(
        db_path=path,
        line_id=line_id,
        product_code=product_code,
        lot_id=lot_id,
        window=max(20, safe_window),
    )
    rows: list[tuple[str, str]] = []
    _flatten_metrics("executive", executive, rows)
    _flatten_metrics("early_warning", early, rows)
    _flatten_metrics("outcome_kpis", outcomes, rows)
    csv_lines = ["metric,value"] + [f"{_csv_escape(k)},{_csv_escape(v)}" for k, v in rows]
    csv_text = "\n".join(csv_lines)
    filename = f"executive_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return PlainTextResponse(
        content=csv_text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/v1/history/runs")
def get_history_runs(
    db_path: str,
    line_id: str | None = None,
    product_code: str | None = None,
    lot_id: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    path = Path(db_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"db not found: {db_path}")
    rows = list_recent_runs(
        db_path=path,
        line_id=line_id,
        product_code=product_code,
        lot_id=lot_id,
        limit=max(1, int(limit)),
    )
    return {"count": len(rows), "rows": rows}


# ══════════════════════════════════════════════════════════
# New Production Endpoints
# ══════════════════════════════════════════════════════════


@app.get("/v1/config/status")
def get_config_status() -> dict[str, Any]:
    """Return hot-reload status for all registered policy configs."""
    return {"ok": True, "configs": CONFIG_STORE.status()}


@app.post("/v1/config/reload")
def reload_config(name: str | None = None) -> dict[str, Any]:
    """Force-reload a specific config or all configs."""
    if name:
        data = CONFIG_STORE.reload(name)
        return {"ok": True, "name": name, "keys": len(data)}
    CONFIG_STORE.reload_all()
    return {"ok": True, "reloaded": "all"}


@app.get("/v1/images/usage")
def get_image_usage() -> dict[str, Any]:
    """Return image storage disk usage statistics."""
    return IMAGE_STORE.disk_usage()


@app.get("/v1/images/by-lot")
def get_images_by_lot(lot_id: str, limit: int = 100) -> dict[str, Any]:
    """List stored images for a given lot."""
    rows = IMAGE_STORE.list_by_lot(lot_id, limit=max(1, min(limit, 500)))
    return {"lot_id": lot_id, "count": len(rows), "images": rows}


@app.post("/v1/images/cleanup")
def cleanup_old_images(max_age_days: int = 180) -> dict[str, Any]:
    """Delete images older than max_age_days."""
    days = max(30, min(max_age_days, 730))
    deleted = IMAGE_STORE.cleanup(max_age_days=days)
    return {"ok": True, "deleted": deleted, "max_age_days": days}


@app.post("/v1/report/pdf")
def generate_pdf_report(
    db_path: str = "",
    run_id: str = "",
    company_name: str = "SENIA",
    language: str = "zh",
) -> Response:
    """Generate a PDF/HTML inspection report for a specific run."""
    if not run_id:
        raise HTTPException(status_code=400, detail="run_id is required")
    # Try to load the report from quality history
    report_data: dict[str, Any] = {}
    if db_path:
        from elite_quality_history import load_run_report
        try:
            report_data = load_run_report(Path(db_path), run_id) or {}
        except Exception:
            pass
    if not report_data:
        report_data = {"run_id": run_id, "result": {"summary": {}}, "decision": {}, "profile": {}}
    out_dir = _ensure_output_dir("reports")
    output_path = out_dir / f"report_{run_id}"
    result_path = generate_report(report_data, output_path, company_name, language)
    media = "application/pdf" if result_path.suffix == ".pdf" else "text/html"
    return FileResponse(str(result_path), media_type=media, filename=result_path.name)


@app.get("/v1/events/dead-letters")
def get_event_dead_letters() -> dict[str, Any]:
    """Return events that failed delivery to all subscribers."""
    letters = EVENT_BUS.get_dead_letters()
    return {"count": len(letters), "dead_letters": letters[-100:]}


@app.get("/v1/events/status")
def get_event_bus_status() -> dict[str, Any]:
    """Return event bus status."""
    return {
        "subscriber_count": EVENT_BUS.subscriber_count(),
        "dead_letter_count": len(EVENT_BUS.get_dead_letters()),
    }


@app.post("/v1/backup/create")
def create_backup() -> dict[str, Any]:
    """Create a new backup of all databases and configs."""
    result = BACKUP_MANAGER.backup()
    _log.info("backup_created", path=str(result.backup_path),
              size_mb=round(result.size_bytes / 1048576, 2))
    return {
        "ok": True,
        "path": str(result.backup_path),
        "size_bytes": result.size_bytes,
        "sha256": result.sha256,
        "duration_sec": result.duration_sec,
        "sources": result.sources,
    }


@app.post("/v1/backup/rotate")
def rotate_backups(keep: int = 7) -> dict[str, Any]:
    """Rotate old backups, keeping only the most recent N."""
    safe_keep = max(1, min(keep, 30))
    deleted = BACKUP_MANAGER.rotate(keep=safe_keep)
    return {"ok": True, "deleted": deleted, "kept": safe_keep}


@app.get("/v1/backup/list")
def list_backups() -> dict[str, Any]:
    """List all available backups."""
    backups = BACKUP_MANAGER.list_backups()
    return {"count": len(backups), "backups": backups}


@app.get("/v1/backup/status")
def get_backup_status() -> dict[str, Any]:
    """Return backup system status."""
    return BACKUP_MANAGER.status()


@app.get("/v1/i18n/locales")
def get_available_locales() -> dict[str, Any]:
    """Return supported locales."""
    from elite_i18n import available_locales, all_keys
    return {"locales": available_locales(), "message_count": len(all_keys())}


@app.post("/v1/batch/parallel")
async def run_parallel_batch_endpoint(
    batch_dir: str = Form(""),
    profile: str = Form("auto"),
    max_workers: int = Form(4),
    glob_pattern: str = Form("*.jpg"),
) -> dict[str, Any]:
    """Run parallel batch analysis on a directory of images."""
    if not batch_dir:
        raise HTTPException(status_code=400, detail="batch_dir is required")
    dir_path = Path(batch_dir)
    if not dir_path.is_dir():
        raise HTTPException(status_code=404, detail=f"directory not found: {batch_dir}")
    image_paths = sorted(dir_path.glob(glob_pattern))
    if not image_paths:
        return {"ok": True, "total": 0, "message": "no images found"}
    safe_workers = max(1, min(max_workers, 16))
    result = run_parallel_batch(
        image_paths=image_paths,
        mode="single",
        profile=profile,
        max_workers=safe_workers,
    )
    _log.info("batch_complete", total=result.total, success=result.success,
              failed=result.failed, elapsed=result.elapsed_sec)
    return {
        "ok": True,
        **result.summary(),
        "results": result.results[:50],
        "errors": result.errors[:20],
    }


@app.post("/v1/senia/analyze")
async def senia_analyze_endpoint(
    image: UploadFile = File(...),
    profile: str = Form("auto"),
    lot_id: str = Form(""),
    product_code: str = Form(""),
    grid: str = Form("6x8"),
) -> dict[str, Any]:
    """
    SENIA 全自动对色: 上传一张照片, 返回判定+偏差方向+调色建议.

    三级判定: PASS (合格) / MARGINAL (临界) / FAIL (不合格)
    偏差方向: 偏红/偏黄/偏暗/偏灰/饱和度不足
    调色建议: 减红/减白/查刮刀... (区分配方问题 vs 工艺问题)
    """
    # 文件类型验证
    filename = (image.filename or "").lower()
    allowed_exts = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp", ".dng"}
    if filename and not any(filename.endswith(ext) for ext in allowed_exts):
        raise HTTPException(status_code=400,
                            detail=f"Unsupported file type. Allowed: {', '.join(sorted(allowed_exts))}")

    raw = await image.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"image too large (max {MAX_UPLOAD_BYTES // 1024 // 1024}MB)")
    if len(raw) < 1000:
        raise HTTPException(status_code=400, detail="file too small, likely not a valid image")

    arr = np.frombuffer(raw, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(status_code=400,
                            detail="Cannot decode image. Supported formats: JPG, PNG, BMP, TIFF, WebP. "
                                   "PDF and other document formats are not supported.")

    # 网格参数验证
    rows, cols = 6, 8
    try:
        parts = grid.split("x")
        rows = max(2, min(int(parts[0]), 12))
        cols = max(2, min(int(parts[1]), 16))
    except (ValueError, IndexError):
        pass

    # 并发控制: 最多3个同时分析 (OpenCV/numpy 非线程安全)
    async with SENIA_ANALYZE_SEMAPHORE:
        out_dir = _ensure_output_dir(f"senia_{lot_id or 'auto'}_{int(time.time())}")
        img_path = out_dir / (image.filename or "upload.jpg")
        img_path.write_bytes(raw)

        try:
            report = senia_analyze_photo(
                image_path=img_path,
                profile_name=profile,
                output_dir=out_dir,
                grid_rows=rows,
                grid_cols=cols,
                lot_id=lot_id,
                product_code=product_code,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    summary = report.get("result", {}).get("summary", {})
    tier = report.get("tier", "UNKNOWN")
    avg_de = summary.get("avg_delta_e00", 0.0)
    used_profile = report.get("profile", {}).get("used", "auto")

    _log.info("senia_analyze", tier=tier, dE00=avg_de, profile=used_profile, lot_id=lot_id)

    # ── 持久化: 写入质量历史数据库 ──
    try:
        run_id = f"senia_{int(time.time())}_{lot_id or 'auto'}"
        record_run(
            db_path=DEFAULT_HISTORY_DB, report=report,
            line_id=report.get("detection", {}).get("sample_source", ""),
            product_code=product_code, lot_id=lot_id,
        )
    except Exception:
        _log.warning("senia_record_run_failed", lot_id=lot_id)

    # ── 事件总线 + 图片存储 ──
    try:
        EVENT_BUS.publish(QualityDecisionEvent(
            lot_id=lot_id, product_code=product_code, decision=tier,
            avg_delta_e=avg_de, profile=used_profile,
        ))
    except Exception:
        pass
    try:
        IMAGE_STORE.save(data=raw, lot_id=lot_id, category="senia_analysis",
                         product_code=product_code, filename=image.filename or "upload.jpg")
    except Exception:
        pass

    # ── 历史对比 ──
    try:
        baseline = compare_with_baseline(avg_de, DEFAULT_HISTORY_DB, lot_id, product_code)
        report["history"] = baseline
    except Exception:
        report["history"] = {"has_baseline": False}

    return report


@app.post("/v1/senia/dual-shot")
async def senia_dual_shot_endpoint(
    reference: UploadFile = File(...),
    sample: UploadFile = File(...),
    profile: str = Form("auto"),
    lot_id: str = Form(""),
    product_code: str = Form(""),
) -> dict[str, Any]:
    """
    双拍模式: 分别上传标样照片和大货照片, 精度最高.
    不需要把标样放在大货上面, 分别拍即可.
    """
    ref_raw = await reference.read()
    smp_raw = await sample.read()

    out_dir = _ensure_output_dir(f"dual_{lot_id or 'auto'}_{int(time.time())}")
    ref_path = out_dir / (reference.filename or "reference.jpg")
    smp_path = out_dir / (sample.filename or "sample.jpg")
    ref_path.write_bytes(ref_raw)
    smp_path.write_bytes(smp_raw)

    try:
        report = senia_dual_shot(
            reference_path=ref_path, sample_path=smp_path,
            profile_name=profile, output_dir=out_dir,
            lot_id=lot_id, product_code=product_code,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    _log.info("senia_dual_shot", tier=report["tier"],
              dE00=report["result"]["summary"]["avg_delta_e00"])
    return report


@app.post("/v1/senia/calibrate")
async def senia_calibrate_endpoint(
    image: UploadFile = File(...),
) -> dict[str, Any]:
    """
    ColorChecker 自动校准: 上传含色卡的照片, 返回 3×3 CCM.
    """
    raw = await image.read()
    arr = np.frombuffer(raw, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(status_code=400, detail="invalid image")
    result = calibrate_from_photo(img)
    _log.info("senia_calibrate", found=result.get("found"), quality=result.get("ccm_quality"))
    return result


@app.get("/v1/senia/lot-trend")
def senia_lot_trend(
    lot_id: str = "",
    product_code: str = "",
    limit: int = 30,
) -> dict[str, Any]:
    """查询批次/产品的色差趋势和漂移检测."""
    return compute_lot_trend(DEFAULT_HISTORY_DB, lot_id, product_code, min(limit, 200))


@app.get("/v1/senia/thresholds")
def senia_get_thresholds(
    profile: str = "solid",
    product_code: str = "",
    customer_id: str = "",
) -> dict[str, Any]:
    """获取当前阈值配置 (考虑产品/客户覆盖)."""
    t = THRESHOLD_STORE.get(profile, product_code, customer_id)
    return {
        "pass_dE": t.pass_dE,
        "marginal_dE": t.marginal_dE,
        "defect_marginal": t.defect_marginal,
        "defect_fail": t.defect_fail,
        "profile": profile,
        "product_code": product_code,
        "customer_id": customer_id,
    }


@app.post("/v1/senia/thresholds/product")
def senia_set_product_threshold(
    product_code: str = Form(...),
    pass_dE: float = Form(None),
    marginal_dE: float = Form(None),
) -> dict[str, Any]:
    """设置产品级阈值覆盖."""
    result = THRESHOLD_STORE.set_product_override(product_code, pass_dE=pass_dE, marginal_dE=marginal_dE)
    return {"ok": True, "product_code": product_code, "thresholds": result}


@app.post("/v1/senia/thresholds/customer")
def senia_set_customer_threshold(
    customer_id: str = Form(...),
    pass_dE: float = Form(None),
    marginal_dE: float = Form(None),
) -> dict[str, Any]:
    """设置客户级阈值覆盖."""
    result = THRESHOLD_STORE.set_customer_override(customer_id, pass_dE=pass_dE, marginal_dE=marginal_dE)
    return {"ok": True, "customer_id": customer_id, "thresholds": result}


@app.get("/v1/senia/thresholds/all")
def senia_list_thresholds() -> dict[str, Any]:
    """列出所有阈值覆盖."""
    return THRESHOLD_STORE.status()


# ── 自学习 API ──────────────────────────────────────────

@app.post("/v1/senia/feedback")
def senia_record_feedback(
    run_id: str = Form(...),
    system_tier: str = Form(...),
    operator_tier: str = Form(...),
    dE00: float = Form(...),
    profile: str = Form("solid"),
) -> dict[str, Any]:
    """
    操作员反馈: 覆盖系统判定, 系统自动学习调整阈值.
    例: 系统判 MARGINAL, 操作员认为应该 PASS → 系统学习放宽阈值.
    """
    return ONLINE_LEARNER.record_feedback(run_id, system_tier, operator_tier, dE00, profile)


@app.get("/v1/senia/learning/stats")
def senia_learning_stats() -> dict[str, Any]:
    """查看自学习统计: 反馈总数、一致率、累积调整."""
    return ONLINE_LEARNER.stats()


@app.post("/v1/senia/recipe-twin/record")
def senia_recipe_twin_record(
    product_code: str = Form(...),
    recipe_json: str = Form(...),
    measured_L: float = Form(...),
    measured_a: float = Form(...),
    measured_b: float = Form(...),
) -> dict[str, Any]:
    """记录 配方→色值 数据, 积累训练配方数字孪生."""
    try:
        recipe = json.loads(recipe_json)
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"invalid recipe_json: {exc}") from exc
    return RECIPE_TWIN.record_sample(product_code, recipe, (measured_L, measured_a, measured_b))


@app.post("/v1/senia/recipe-twin/predict")
def senia_recipe_twin_predict(
    product_code: str = Form(...),
    recipe_json: str = Form(...),
) -> dict[str, Any]:
    """从配方预测色值 (需要先积累≥10组数据)."""
    try:
        recipe = json.loads(recipe_json)
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"invalid recipe_json: {exc}") from exc
    return RECIPE_TWIN.predict(product_code, recipe)


@app.post("/v1/senia/batch-memory/remember")
def senia_batch_memory_remember(
    product_code: str = Form(...),
    lot_id: str = Form(...),
    L: float = Form(...),
    a: float = Form(...),
    b: float = Form(...),
) -> dict[str, Any]:
    """记住一个批次的色值, 用于未来追加订单匹配."""
    return BATCH_MEMORY.remember(product_code, lot_id, (L, a, b))


@app.get("/v1/senia/batch-memory/find")
def senia_batch_memory_find(
    product_code: str,
    L: float,
    a: float,
    b: float,
    top_k: int = 3,
) -> dict[str, Any]:
    """找到最接近目标色值的历史批次 (客户追加订单时用)."""
    results = BATCH_MEMORY.find_closest(product_code, (L, a, b), min(top_k, 10))
    return {"product_code": product_code, "target_lab": [L, a, b], "matches": results}


@app.get("/v1/senia/aging-predict")
def senia_aging_predict(
    current_dE: float,
    current_dL: float = 0.0,
    current_db: float = 0.0,
    profile: str = "wood",
    months: int = 12,
) -> dict[str, Any]:
    """预测色差随时间变化 + 老化感知验收建议."""
    return predict_aging_acceptance(current_dE, current_dL, current_db, profile, min(months, 60))


# ── 管理 API ──────────────────────────────────────────

# ── 即时对色 (微信/钉钉机器人) ──────────────────────────

@app.post("/v1/senia/instant")
async def senia_instant_endpoint(
    image: UploadFile = File(...),
    lot_id: str = Form(""),
    profile: str = Form("auto"),
) -> dict[str, Any]:
    """
    即时对色: 3秒出结果, 返回可直接发送到微信/钉钉的消息.
    """
    raw = await image.read()
    if len(raw) < 1000:
        return {"error": "文件太小", "text": "❌ 文件太小, 不是有效图片"}
    result = process_instant(raw, lot_id=lot_id, profile=profile)
    return {
        "tier": result.tier,
        "dE00": result.dE00,
        "directions": result.directions,
        "text_message": result.to_text_message(),
        "voice_text": result.to_voice_text(),
        "wecom_card": result.to_wecom_card(),
        "elapsed_sec": result.elapsed_sec,
        "error": result.error,
    }


# ── 生产前预测 (配方→颜色) ──────────────────────────────

@app.post("/v1/senia/predict/record")
def senia_predict_record(
    product_code: str = Form(...),
    recipe_json: str = Form(...),
    measured_L: float = Form(...),
    measured_a: float = Form(...),
    measured_b: float = Form(...),
    machine_json: str = Form("{}"),
    env_json: str = Form("{}"),
) -> dict[str, Any]:
    """记录 配方+机台+环境→色值 数据, 用于训练预测模型."""
    try:
        recipe = json.loads(recipe_json)
        machine = json.loads(machine_json) if machine_json != "{}" else None
        env = json.loads(env_json) if env_json != "{}" else None
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"invalid JSON: {exc}") from exc
    return PRODUCTION_PREDICTOR.record(product_code, recipe, (measured_L, measured_a, measured_b), machine, env)


@app.post("/v1/senia/predict/color")
def senia_predict_color(
    product_code: str = Form(...),
    recipe_json: str = Form(...),
    machine_json: str = Form("{}"),
    env_json: str = Form("{}"),
) -> dict[str, Any]:
    """生产前预测: 输入配方, 预测颜色."""
    try:
        recipe = json.loads(recipe_json)
        machine = json.loads(machine_json) if machine_json != "{}" else None
        env = json.loads(env_json) if env_json != "{}" else None
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"invalid JSON: {exc}") from exc
    pred = PRODUCTION_PREDICTOR.predict(product_code, recipe, machine, env)
    return {
        "predicted_L": pred.predicted_L, "predicted_a": pred.predicted_a, "predicted_b": pred.predicted_b,
        "confidence": pred.confidence, "rmse": pred.rmse,
        "suggestion": pred.suggestion, "sample_count": pred.sample_count,
    }


@app.post("/v1/senia/predict/optimize-recipe")
def senia_optimize_recipe(
    product_code: str = Form(...),
    target_L: float = Form(...),
    target_a: float = Form(...),
    target_b: float = Form(...),
    current_recipe_json: str = Form(...),
    machine_json: str = Form("{}"),
    env_json: str = Form("{}"),
) -> dict[str, Any]:
    """逆向优化: 给定目标色, 求最优配方."""
    try:
        current = json.loads(current_recipe_json)
        machine = json.loads(machine_json) if machine_json != "{}" else None
        env = json.loads(env_json) if env_json != "{}" else None
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"invalid JSON: {exc}") from exc
    result = PRODUCTION_PREDICTOR.optimize_recipe(product_code, (target_L, target_a, target_b), current, machine, env)
    return {
        "optimized_recipe": result.optimized_recipe,
        "adjustments": result.adjustments,
        "predicted_dE": result.predicted_dE,
        "confidence": result.confidence,
        "iterations": result.iterations,
    }


# ── 设备指纹 ────────────────────────────────────────────

@app.post("/v1/senia/device/learn")
def senia_device_learn(
    device_id: str = Form(...),
    patches_json: str = Form(...),
) -> dict[str, Any]:
    """从 ColorChecker 校准学习设备色彩指纹."""
    try:
        patches = json.loads(patches_json)
        measured = [(int(p[0]), int(p[1]), int(p[2])) for p in patches]
    except (json.JSONDecodeError, ValueError, IndexError) as exc:
        raise HTTPException(status_code=400, detail=f"invalid patches_json: {exc}") from exc
    return DEVICE_FINGERPRINT.learn_from_calibration(device_id, measured)


# ── QR 色彩护照 ─────────────────────────────────────────

@app.post("/v1/senia/passport/generate")
def senia_passport_generate(
    lot_id: str = Form(...),
    product_code: str = Form(...),
    tier: str = Form(...),
    dE00: float = Form(...),
    L: float = Form(...),
    a: float = Form(...),
    b: float = Form(...),
    directions: str = Form(""),
    profile: str = Form(""),
) -> dict[str, Any]:
    """生成数字色彩护照 (附防伪签名)."""
    dirs = [d.strip() for d in directions.split(",") if d.strip()] if directions else []
    return generate_passport(lot_id, product_code, tier, dE00, dirs, (L, a, b), profile)


@app.get("/v1/senia/passport/verify")
def senia_passport_verify(passport_json: str = "") -> dict[str, Any]:
    """验证色彩护照签名."""
    try:
        data = json.loads(passport_json)
    except (json.JSONDecodeError, ValueError):
        return {"valid": False, "error": "invalid JSON"}
    return verify_passport(data)


@app.get("/v1/senia/passport/view", response_class=HTMLResponse)
def senia_passport_view(passport_json: str = "") -> str:
    """渲染可视化色彩护照 (买家扫码看到这个页面)."""
    try:
        data = json.loads(passport_json)
    except (json.JSONDecodeError, ValueError):
        return "<h1>Invalid passport</h1>"
    return render_passport_html(data)


# ── 管理 API ──────────────────────────────────────────

# ── 知识引擎 ────────────────────────────────────────────

@app.post("/v1/senia/knowledge/optimize")
def senia_knowledge_optimize() -> dict[str, Any]:
    """运行自动优化: 从公开知识库更新阈值/材质参数/老化模型."""
    return KNOWLEDGE_ENGINE.auto_optimize()


@app.get("/v1/senia/knowledge/status")
def senia_knowledge_status() -> dict[str, Any]:
    """知识引擎状态."""
    return KNOWLEDGE_ENGINE.status()


@app.get("/v1/senia/knowledge/material")
def senia_knowledge_material(material: str = "wood_oak_gray") -> dict[str, Any]:
    """查询材质参考数据."""
    data = KNOWLEDGE_ENGINE.get_material_reference(material)
    if data is None:
        from senia_knowledge_crawler import MATERIAL_COLOR_PROFILES
        return {"found": False, "available": list(MATERIAL_COLOR_PROFILES.keys())}
    return {"found": True, "material": material, "data": data}


@app.post("/v1/senia/knowledge/crawl")
def senia_knowledge_crawl() -> dict[str, Any]:
    """手动触发爬虫: 从公开数据源抓取色彩科学数据."""
    results = WEB_CRAWLER.crawl_all()
    return {
        "ok": True,
        "sources": len(results),
        "succeeded": sum(1 for r in results if r.success),
        "total_records": sum(r.records_fetched for r in results),
        "details": [
            {"source": r.source, "success": r.success, "records": r.records_fetched,
             "new": r.records_new, "error": r.error}
            for r in results
        ],
    }


@app.post("/v1/senia/knowledge/auto-upgrade")
def senia_knowledge_auto_upgrade() -> dict[str, Any]:
    """
    完整自动升级: 爬取→验证→合并→优化.
    系统从网上自动学习公开数据, 更新模型参数.
    """
    report = AUTO_UPGRADER.run_full_upgrade()
    _log.info("auto_upgrade_complete",
              success=report.get("success"),
              steps=len(report.get("steps", [])))
    return report


@app.get("/v1/senia/knowledge/upgrade-history")
def senia_knowledge_upgrade_history() -> dict[str, Any]:
    """查看自动升级历史."""
    history = AUTO_UPGRADER.get_upgrade_history()
    return {"count": len(history), "history": history}


@app.get("/v1/senia/knowledge/standard")
def senia_knowledge_standard(name: str = "decorative_film_industry") -> dict[str, Any]:
    """查询行业标准."""
    data = KNOWLEDGE_ENGINE.get_industry_standard(name)
    if data is None:
        from senia_knowledge_crawler import INDUSTRY_STANDARDS
        return {"found": False, "available": list(INDUSTRY_STANDARDS.keys())}
    return {"found": True, "standard": name, "data": data}


# ── 管理 API ──────────────────────────────────────────

# ── 终身学习 ─────────────────────────────────────────────

@app.post("/v1/senia/learn/feedback")
def senia_learn_feedback(
    profile: str = Form(...), dE: float = Form(...), actual_tier: str = Form(...),
) -> dict[str, Any]:
    """L1 即时学习: 每次反馈都让阈值更准."""
    return LIFELONG.learn_from_feedback(profile, dE, actual_tier)


@app.post("/v1/senia/learn/batch")
def senia_learn_batch(
    product_code: str = Form(...), samples_json: str = Form(...),
) -> dict[str, Any]:
    """L2 批次学习: 每批结束后汇总提取知识."""
    try:
        samples = json.loads(samples_json)
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return LIFELONG.learn_from_batch(product_code, samples)


@app.post("/v1/senia/learn/refresh")
def senia_learn_refresh() -> dict[str, Any]:
    """L3 周期学习: 重新拟合所有模型 (建议每周运行)."""
    return LIFELONG.refresh_models()


@app.post("/v1/senia/learn/transfer")
def senia_learn_transfer(
    source: str = Form(...), target: str = Form(...), similarity: float = Form(0.8),
) -> dict[str, Any]:
    """L4 迁移学习: 新产品从已有产品迁移知识."""
    return LIFELONG.transfer(source, target, max(0.1, min(1.0, similarity)))


@app.get("/v1/senia/learn/distill")
def senia_learn_distill() -> dict[str, Any]:
    """L5 知识蒸馏: 把所有学到的知识压缩成人类可读规则."""
    return LIFELONG.distill(AI_MEMORY)


@app.get("/v1/senia/learn/status")
def senia_learn_status() -> dict[str, Any]:
    """终身学习状态总览."""
    return LIFELONG.status()


# ── AI 推理引擎 ──────────────────────────────────────────

@app.post("/v1/senia/ai/reason")
def senia_ai_reason(
    dE: float = Form(...), dL: float = Form(0), da: float = Form(0), db: float = Form(0),
    profile: str = Form("wood"), customer_id: str = Form(""),
    lot_id: str = Form(""), product_code: str = Form(""),
    context_tags: str = Form(""),
) -> dict[str, Any]:
    """
    AI 推理链: 像经验丰富的调色师傅一样, 一步步思考给出建议.
    不是简单的阈值判定, 而是综合考虑历史案例+上下文+趋势.
    """
    tags = [t.strip() for t in context_tags.split(",") if t.strip()] if context_tags else []
    return expert_reasoning_chain(dE, dL, da, db, profile, customer_id, lot_id, product_code, tags, AI_MEMORY)


@app.post("/v1/senia/ai/remember")
def senia_ai_remember(
    dE: float = Form(...), dL: float = Form(0), da: float = Form(0), db: float = Form(0),
    profile: str = Form("wood"), product_code: str = Form(""),
    lot_id: str = Form(""), customer_id: str = Form(""),
    system_tier: str = Form(""), operator_override: str = Form(""),
    context_tags: str = Form(""), notes: str = Form(""),
) -> dict[str, Any]:
    """记录一个决策案例到 AI 经验记忆库."""
    tags = [t.strip() for t in context_tags.split(",") if t.strip()] if context_tags else []
    case = CaseMemory(
        dE=dE, dL=dL, da=da, db=db, profile=profile,
        product_code=product_code, lot_id=lot_id, customer_id=customer_id,
        system_tier=system_tier, operator_override=operator_override,
        context_tags=tags, notes=notes,
    )
    AI_MEMORY.remember(case)
    return {"ok": True, "case_id": case.case_id}


@app.post("/v1/senia/ai/close-case")
def senia_ai_close_case(
    case_id: str = Form(...), customer_accepted: bool = Form(...), notes: str = Form(""),
) -> dict[str, Any]:
    """案例闭环: 记录客户最终是否接受, 用于系统学习."""
    AI_MEMORY.learn_from_outcome(case_id, customer_accepted, notes)
    return {"ok": True}


@app.get("/v1/senia/ai/error-patterns")
def senia_ai_error_patterns() -> dict[str, Any]:
    """分析系统判错的模式: 什么情况下判错最多?"""
    return AI_MEMORY.get_error_patterns()


@app.post("/v1/senia/ai/parse-text")
def senia_ai_parse_text(text: str = Form(...)) -> dict[str, Any]:
    """自然语言理解: 把操作员的话转为结构化数据."""
    return parse_operator_input(text)


@app.get("/v1/senia/ai/suggestions")
def senia_ai_suggestions(
    dE: float = 1.5, dL: float = 0, da: float = 0, db: float = 0,
    profile: str = "wood",
) -> dict[str, Any]:
    """主动建议: 不等操作员问, 系统主动提醒该注意什么."""
    return {"suggestions": proactive_suggestions(dE, dL, da, db, profile, memory=AI_MEMORY)}


# ── 智能决策 (能力叠加) ──────────────────────────────────

@app.post("/v1/senia/smart-decision")
def senia_smart_decision(
    dE: float = Form(...), dL: float = Form(0), da: float = Form(0), db: float = Form(0),
    profile: str = Form("wood"), customer_id: str = Form(""),
    illuminant: str = Form("D65"), batch_sqm: float = Form(500),
) -> dict[str, Any]:
    """
    智能决策中心: 综合色差+客户+光源+季节+批次, 给出最终建议.
    所有能力联合叠加, 比任何单一判断都更准确.
    """
    sensitivity = None
    if customer_id:
        sensitivity = CUSTOMER_PROFILES.get_sensitivity(customer_id)
        if not sensitivity.get("analyzed"):
            sensitivity = None
    return smart_decision(dE, dL, da, db, profile, customer_id, sensitivity, illuminant, batch_sqm)


@app.post("/v1/senia/predictive-maintenance")
def senia_predictive_maintenance(
    drift_json: str = Form(...),
    threshold: float = Form(2.5),
) -> dict[str, Any]:
    """
    预测性维护: 色差趋势+设备诊断 = 提前告诉你哪个部件要出问题.
    """
    try:
        data = json.loads(drift_json)
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return predictive_maintenance(data, threshold)


@app.post("/v1/senia/one-click-match")
def senia_one_click_match(
    L: float = Form(...), a: float = Form(...), b: float = Form(...),
) -> dict[str, Any]:
    """
    一键配色: 搜索+逆向+预测, 从目标颜色到推荐配方.
    """
    return one_click_color_match((L, a, b), COLOR_SEARCH, RECIPE_TWIN)


# ── V2 创新功能 ──────────────────────────────────────────

@app.post("/v1/senia/drift-warning/record")
def senia_drift_record(line_id: str = Form(...), dE: float = Form(...)) -> dict[str, Any]:
    """记录色差数据点, 用于趋势预警."""
    DRIFT_WARNING.record(line_id, dE)
    return {"ok": True}


@app.get("/v1/senia/drift-warning/predict")
def senia_drift_predict(line_id: str, threshold: float = 2.5) -> dict[str, Any]:
    """色差趋势预警: 预测几小时后是否超标."""
    return DRIFT_WARNING.predict(line_id, threshold)


@app.post("/v1/senia/color-search/index")
def senia_color_search_index(
    product_code: str = Form(...), L: float = Form(...),
    a: float = Form(...), b: float = Form(...), name: str = Form(""),
) -> dict[str, Any]:
    """索引一个产品到色彩搜索引擎."""
    COLOR_SEARCH.index(product_code, (L, a, b), name)
    return {"ok": True, "total_indexed": COLOR_SEARCH.count()}


@app.get("/v1/senia/color-search/find")
def senia_color_search_find(
    L: float, a: float, b: float, top_k: int = 5,
) -> dict[str, Any]:
    """色彩搜索: 找和目标颜色最接近的产品."""
    return {"results": COLOR_SEARCH.search((L, a, b), min(top_k, 20))}


@app.post("/v1/senia/customer-profile/record")
def senia_customer_record(
    customer_id: str = Form(...), dL: float = Form(...),
    da: float = Form(...), db: float = Form(...), accepted: bool = Form(...),
) -> dict[str, Any]:
    """记录客户接受/退货决定, 用于学习客户偏好."""
    CUSTOMER_PROFILES.record_decision(customer_id, dL, da, db, accepted)
    return {"ok": True}


@app.get("/v1/senia/customer-profile/sensitivity")
def senia_customer_sensitivity(customer_id: str) -> dict[str, Any]:
    """分析客户色彩敏感度: 对哪个方向最挑剔?"""
    return CUSTOMER_PROFILES.get_sensitivity(customer_id)


@app.get("/v1/senia/machine-diagnosis")
def senia_machine_diagnosis(
    slope_dL: float = 0, slope_da: float = 0, slope_db: float = 0,
) -> dict[str, Any]:
    """从色差漂移诊断印刷机状态."""
    return diagnose_machine_from_drift(slope_dL, slope_da, slope_db)


@app.get("/v1/senia/seasonal-compensation")
def senia_seasonal(
    month: int = 6, base_dE: float = 1.5,
    humidity: float | None = None, temperature: float | None = None,
) -> dict[str, Any]:
    """季节性色差补偿建议."""
    return seasonal_compensation(month, base_dE, humidity, temperature)


@app.get("/v1/senia/anisotropy")
def senia_anisotropy(
    dE_0deg: float = 1.5, dE_45deg: float | None = None, dE_90deg: float | None = None,
) -> dict[str, Any]:
    """多角度色差分析 (纹理各向异性)."""
    return anisotropy_analysis(dE_0deg, dE_45deg, dE_90deg)


@app.get("/v1/senia/ar-preview")
def senia_ar_preview(
    L: float = 55, a: float = 0, b: float = 8, illuminant: str = "A",
) -> dict[str, Any]:
    """AR预览: 生成指定光源下的地板颜色数据 (给前端WebGL渲染)."""
    return generate_ar_preview_data((L, a, b), illuminant)


# ── Next-Gen 创新功能 ────────────────────────────────────

@app.get("/v1/senia/metamerism-risk")
def senia_metamerism_check(
    L: float, a: float, b: float,
    L_a: float | None = None, a_a: float | None = None, b_a: float | None = None,
) -> dict[str, Any]:
    """同色异谱预警: 在工厂灯下合格, 到客户家会不会变色?"""
    lab_a = (L_a, a_a, b_a) if L_a is not None and a_a is not None and b_a is not None else None
    return metamerism_risk((L, a, b), lab_a)


@app.get("/v1/senia/cost-risk")
def senia_cost_risk(
    dE: float, batch_sqm: float = 500, unit_cost: float = 15, customer_tier: str = "standard",
) -> dict[str, Any]:
    """色差成本量化: 这个 ΔE 会导致多少退货和索赔?"""
    return delta_e_to_cost(dE, batch_sqm, unit_cost, customer_tier)


@app.post("/v1/senia/batch-consistency")
def senia_batch_consistency(
    samples_json: str = Form(...),
) -> dict[str, Any]:
    """批内一致性指数: 这批货铺在一起会不会看到色差?"""
    try:
        samples = [float(x) for x in json.loads(samples_json)]
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=f"invalid samples_json: {exc}") from exc
    return batch_consistency_index(samples)


# ── 环境光学习 ──────────────────────────────────────────

@app.post("/v1/senia/ambient/record")
def senia_ambient_record(
    station_id: str = Form(...),
    r_gain: float = Form(...),
    g_gain: float = Form(...),
    b_gain: float = Form(...),
) -> dict[str, Any]:
    """记录一次色卡校准的白平衡增益 (用于学习工位光源模式)."""
    AMBIENT_LEARNER.record_calibration(station_id, r_gain, g_gain, b_gain)
    return {"ok": True, "station_id": station_id}


@app.get("/v1/senia/ambient/predict")
def senia_ambient_predict(station_id: str = "") -> dict[str, Any]:
    """预测工位的白平衡增益 (无色卡场景)."""
    gains = AMBIENT_LEARNER.predict_gains(station_id)
    if gains is None:
        return {"predicted": False, "reason": "insufficient calibration history (need ≥3)"}
    return {"predicted": True, "r_gain": round(gains[0], 4), "g_gain": round(gains[1], 4), "b_gain": round(gains[2], 4)}


# ── Edge SDK (离线分析) ──────────────────────────────────

@app.post("/v1/senia/edge/analyze")
def senia_edge_analyze(
    ref_pixels_json: str = Form(...),
    sample_pixels_json: str = Form(...),
    profile: str = Form("wood"),
) -> dict[str, Any]:
    """
    Edge SDK 离线分析: 输入 RGB 像素列表, 返回判定.
    用于手机/嵌入式端离线对色后同步到云端验证.
    """
    try:
        ref = [tuple(p) for p in json.loads(ref_pixels_json)]
        smp = [tuple(p) for p in json.loads(sample_pixels_json)]
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=f"invalid pixel JSON: {exc}") from exc
    return edge_analyze_offline(ref, smp, profile)


# ── 拍摄工位指南 ────────────────────────────────────────

@app.get("/v1/senia/capture-station/guide")
def senia_capture_guide() -> dict[str, Any]:
    """返回拍摄工位搭建指南 (BOM + 步骤 + iPhone设置)."""
    return {
        "bom": CAPTURE_STATION_BOM,
        "build_steps": BUILD_STEPS,
        "iphone_settings": IPHONE_CAMERA_SETTINGS,
    }


# ── 管理 API ──────────────────────────────────────────

@app.get("/v1/senia/admin/status")
def senia_admin_status() -> dict[str, Any]:
    """系统完整状态: 所有模块运行情况."""
    return {
        "version": APP_VERSION,
        "learning": ONLINE_LEARNER.stats(),
        "thresholds": THRESHOLD_STORE.status(),
        "images": IMAGE_STORE.disk_usage(),
        "backup": BACKUP_MANAGER.status(),
        "config": CONFIG_STORE.status(),
        "event_bus": {"subscribers": EVENT_BUS.subscriber_count(),
                      "dead_letters": len(EVENT_BUS.get_dead_letters())},
    }


@app.post("/v1/senia/admin/reset-learning")
def senia_admin_reset_learning() -> dict[str, Any]:
    """重置自学习状态 (清除所有反馈和阈值调整)."""
    global ONLINE_LEARNER  # noqa: PLW0603
    ONLINE_LEARNER = OnlineLearner(store_path=DEFAULT_OUTPUT_ROOT / "senia_feedback.json")
    _log.info("senia_learning_reset")
    return {"ok": True, "message": "learning state reset"}


@app.get("/v1/senia/admin/disk-check")
def senia_admin_disk_check() -> dict[str, Any]:
    """磁盘使用检查 + 清理建议."""
    usage = IMAGE_STORE.disk_usage()
    backups = BACKUP_MANAGER.list_backups()
    total_mb = usage.get("total_mb", 0)
    warnings = []
    if total_mb > 5000:
        warnings.append(f"Image archive is {total_mb:.0f}MB, consider running cleanup")
    if len(backups) > 10:
        warnings.append(f"{len(backups)} backups exist, consider rotation (keep=7)")
    return {
        "images": usage,
        "backup_count": len(backups),
        "warnings": warnings,
        "suggestion": "POST /v1/images/cleanup and POST /v1/backup/rotate" if warnings else "disk usage normal",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "elite_api:app",
        host=SETTINGS.api_host,
        port=SETTINGS.api_port,
        log_level=SETTINGS.log_level,
        reload=False,
    )

