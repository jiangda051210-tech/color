from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Elite API full end-to-end verification flow.",
    )
    parser.add_argument(
        "legacy_base_url",
        nargs="?",
        help="Optional positional base URL for backward compatibility.",
    )
    parser.add_argument(
        "--base-url",
        dest="base_url",
        default="",
        help="API base URL, e.g. http://127.0.0.1:8877",
    )
    parser.add_argument(
        "--api-key",
        default="",
        help="Set ELITE_E2E_API_KEY for this run.",
    )
    parser.add_argument(
        "--admin-key",
        default="",
        help="Set ELITE_E2E_ADMIN_KEY for this run.",
    )
    parser.add_argument(
        "--tenant-id",
        default="",
        help="Set ELITE_E2E_TENANT for this run.",
    )
    parser.add_argument(
        "--tenant-header",
        default="",
        help="Set ELITE_E2E_TENANT_HEADER for this run (default x-tenant-id).",
    )
    parser.add_argument(
        "--strict-alert-test",
        action="store_true",
        help="Treat 403 on /v1/system/alert-test as failure.",
    )
    args = parser.parse_args(argv)

    chosen_base = (args.base_url or args.legacy_base_url or "").strip()
    args.base_url = chosen_base or "http://127.0.0.1:8877"

    if args.api_key:
        os.environ["ELITE_E2E_API_KEY"] = args.api_key
    if args.admin_key:
        os.environ["ELITE_E2E_ADMIN_KEY"] = args.admin_key
    if args.tenant_id:
        os.environ["ELITE_E2E_TENANT"] = args.tenant_id
    if args.tenant_header:
        os.environ["ELITE_E2E_TENANT_HEADER"] = args.tenant_header
    return args


def _base_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    api_key = os.getenv("ELITE_E2E_API_KEY", "").strip()
    if api_key:
        headers["x-api-key"] = api_key
    tenant_id = os.getenv("ELITE_E2E_TENANT", "").strip()
    if tenant_id:
        tenant_header = os.getenv("ELITE_E2E_TENANT_HEADER", "x-tenant-id").strip() or "x-tenant-id"
        headers[tenant_header] = tenant_id
    if extra:
        headers.update(extra)
    return headers


def _request(
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
    timeout: float = 30.0,
    headers_extra: dict[str, str] | None = None,
) -> tuple[int, Any]:
    data = None
    headers = _base_headers(headers_extra)
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, method=method.upper(), data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        raw = resp.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw)
        except Exception:
            body = raw
        return resp.status, body


def _get(
    base: str,
    path: str,
    params: dict[str, Any] | None = None,
    headers_extra: dict[str, str] | None = None,
) -> tuple[int, Any]:
    url = f"{base}{path}"
    if params:
        q = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        if q:
            url = f"{url}?{q}"
    return _request("GET", url, None, headers_extra=headers_extra)


def _post(base: str, path: str, payload: dict[str, Any]) -> tuple[int, Any]:
    return _request("POST", f"{base}{path}", payload)


def _post_multipart(
    base: str,
    path: str,
    fields: dict[str, Any] | None = None,
    files: dict[str, Path] | None = None,
    timeout: float = 60.0,
) -> tuple[int, Any]:
    boundary = f"----SENIA-E2E-{int(time.time() * 1000)}"
    chunks: list[bytes] = []
    crlf = b"\r\n"

    for key, value in (fields or {}).items():
        if value is None:
            continue
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"))
        chunks.append(str(value).encode("utf-8"))
        chunks.append(crlf)

    for key, fp in (files or {}).items():
        content_type = mimetypes.guess_type(fp.name)[0] or "application/octet-stream"
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(f'Content-Disposition: form-data; name="{key}"; filename="{fp.name}"\r\n'.encode("utf-8"))
        chunks.append(f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"))
        chunks.append(fp.read_bytes())
        chunks.append(crlf)

    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    body = b"".join(chunks)
    req = urllib.request.Request(
        f"{base}{path}",
        method="POST",
        data=body,
        headers=_base_headers({"Content-Type": f"multipart/form-data; boundary={boundary}"}),
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        raw = resp.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = raw
        return resp.status, parsed


def _assert_200(name: str, status: int, body: Any) -> None:
    if status != 200:
        raise RuntimeError(f"{name} failed: status={status}, body={body}")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    base = args.base_url
    root = Path(__file__).resolve().parent
    ref = (root / "demo_data" / "sample_reference.png").resolve()
    film = (root / "demo_data" / "film_capture.png").resolve()
    out_dir = (root / "out_e2e_flow").resolve()
    history_db = (root / "quality_history.sqlite").resolve()
    innovation_db = (root / "innovation_state.sqlite").resolve()

    run_tag = time.strftime("%Y%m%d_%H%M%S")
    line_id = "SMIS-E2E"
    product_code = "oak-gray-e2e"
    lot_id = f"LOT-E2E-{run_tag}"
    customer_id = "CUST-E2E-001"
    admin_key = os.getenv("ELITE_E2E_ADMIN_KEY", "").strip()
    admin_headers = {"x-api-key": admin_key} if admin_key else None

    print("=== E2E start ===")
    status, body = _get(base, "/health")
    _assert_200("health", status, body)
    print("health ok")

    status, body = _get(base, "/ready")
    _assert_200("ready", status, body)
    if not isinstance(body, dict) or not body.get("ok", False):
        raise RuntimeError(f"readiness check failed: {body}")
    print("readiness ok")

    status, body = _get(base, "/v1/system/status")
    _assert_200("system_status", status, body)
    if isinstance(body, dict):
        output_root_raw = (
            body.get("paths", {}).get("output_root")
            if isinstance(body.get("paths"), dict)
            else None
        )
        if output_root_raw:
            output_root = Path(str(output_root_raw)).resolve()
            out_dir = (output_root / "out_e2e_flow").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    print("system status ok")

    status, body = _get(base, "/v1/system/self-test", headers_extra=admin_headers)
    if status == 403 and not admin_key:
        print("system self-test skipped (admin role required)")
    else:
        _assert_200("system_self_test", status, body)
        if not isinstance(body, dict) or not body.get("ok", False):
            raise RuntimeError(f"system self test failed: {body}")
        print("system self-test ok")

    status, body = _get(base, "/v1/system/metrics", {"top_n": 12})
    _assert_200("system_metrics", status, body)
    print("system metrics ok")

    status, body = _get(base, "/v1/system/slo", {"availability_target_pct": 99.5, "latency_p95_target_ms": 1200})
    _assert_200("system_slo", status, body)
    print("system slo ok")

    status, body = _get(base, "/v1/system/auth-info")
    _assert_200("system_auth_info", status, body)
    print("system auth info ok")

    status, body = _get(base, "/v1/system/tenant-info")
    _assert_200("system_tenant_info", status, body)
    print("system tenant info ok")

    status, body = _get(base, "/v1/system/audit-tail", {"limit": 20}, headers_extra=admin_headers)
    if status == 403 and not admin_key:
        print("system audit tail skipped (admin role required)")
    else:
        _assert_200("system_audit_tail", status, body)
        print("system audit tail ok")

    if admin_key:
        status, body = _request("POST", f"{base}/v1/system/alert-test", None, headers_extra={"x-api-key": admin_key})
    else:
        status, body = _request("POST", f"{base}/v1/system/alert-test", None)
    if status == 403 and not args.strict_alert_test:
        print("system alert test skipped (admin role required)")
    else:
        _assert_200("system_alert_test", status, body)
        print("system alert test ok")

    status, body = _get(base, "/v1/system/alert-dead-letter", headers_extra=admin_headers)
    if status == 403 and not admin_key:
        print("system alert dead-letter skipped (admin role required)")
    else:
        _assert_200("system_alert_dead_letter", status, body)
        print("system alert dead-letter ok")

    status, body = _get(
        base,
        "/v1/system/ops-summary",
        {
            "db_path": str(history_db),
            "line_id": line_id,
            "product_code": product_code,
            "window": 120,
            "audit_limit": 20,
        },
    )
    _assert_200("system_ops_summary", status, body)
    print("system ops summary ok")

    status, body = _get(
        base,
        "/v1/system/executive-brief",
        {
            "db_path": str(history_db),
            "line_id": line_id,
            "product_code": product_code,
            "window": 120,
        },
    )
    _assert_200("system_executive_brief", status, body)
    print("system executive brief ok")

    status, body = _get(
        base,
        "/v1/system/executive-weekly-card",
        {
            "db_path": str(history_db),
            "line_id": line_id,
            "product_code": product_code,
            "window": 200,
        },
    )
    _assert_200("system_executive_weekly_card", status, body)
    print("system executive weekly card ok")

    status, body = _get(
        base,
        "/v1/system/cockpit-snapshot",
        {
            "db_path": str(history_db),
            "line_id": line_id,
            "product_code": product_code,
            "window": 200,
            "weekly_window": 500,
            "audit_limit": 20,
        },
    )
    _assert_200("system_cockpit_snapshot", status, body)
    print("system cockpit snapshot ok")

    status, body = _get(
        base,
        "/v1/system/next-best-action",
        {
            "db_path": str(history_db),
            "line_id": line_id,
            "product_code": product_code,
            "window": 200,
            "weekly_window": 500,
            "ui_role": "operator",
        },
    )
    _assert_200("system_next_best_action", status, body)
    print("system next best action ok")

    status, body = _get(base, "/v1/system/release-gate-report")
    _assert_200("system_release_gate_report", status, body)
    print("system release gate report ok")

    status, body = _get(base, "/")
    _assert_200("home", status, body)
    print("home page ok")

    status, body = _get(
        base,
        "/v1/web/executive-dashboard",
        {
            "db_path": str(history_db),
            "line_id": line_id,
            "product_code": product_code,
            "window": 120,
        },
    )
    _assert_200("web_executive_dashboard", status, body)
    print("executive dashboard ok")

    status, body = _get(
        base,
        "/v1/web/executive-brief",
        {
            "db_path": str(history_db),
            "line_id": line_id,
            "product_code": product_code,
            "window": 120,
        },
    )
    _assert_200("web_executive_brief", status, body)
    print("executive brief page ok")

    status, body = _get(
        base,
        "/v1/web/innovation-v3",
        {
            "db_path": str(history_db),
            "line_id": line_id,
            "product_code": product_code,
        },
    )
    _assert_200("web_innovation_v3", status, body)
    print("innovation v3 page ok")

    status, body = _get(base, "/v1/web/precision-observatory")
    _assert_200("web_precision_observatory", status, body)
    if isinstance(body, str) and "Live Command Pod" not in body:
        raise RuntimeError("web_precision_observatory missing live pod")
    print("precision observatory page ok")

    status, body = _get(base, "/v1/web/assets/observatory-module.js")
    _assert_200("web_precision_observatory_module", status, body)
    if isinstance(body, str) and "EliteObservatory" not in body:
        raise RuntimeError("web_precision_observatory_module invalid payload")
    print("precision observatory module ok")

    status, body = _get(
        base,
        "/v1/history/executive-export",
        {
            "db_path": str(history_db),
            "line_id": line_id,
            "product_code": product_code,
            "window": 120,
        },
    )
    _assert_200("history_executive_export", status, body)
    if isinstance(body, str) and "metric,value" not in body:
        raise RuntimeError("history_executive_export invalid csv payload")
    print("executive export ok")

    status, web_dual = _post_multipart(
        base,
        "/v1/web/analyze/dual-upload",
        fields={
            "profile": "auto",
            "grid": "3x4",
            "output_dir": str(out_dir / "web_dual"),
            "html_report": "true",
            "with_innovation_engine": "true",
            "with_decision_center": "true",
            "with_process_advice": "true",
            "customer_id": customer_id,
            "customer_tier": "vip",
            "innovation_context_json": json.dumps({"environment": "indoor_window", "channel": "web_upload"}),
        },
        files={
            "reference": ref,
            "film": film,
        },
    )
    _assert_200("web_dual_upload", status, web_dual)
    html_path = web_dual.get("html_path") if isinstance(web_dual, dict) else None
    if html_path:
        status, body = _get(base, "/v1/report/html", {"path": html_path})
        _assert_200("report_html", status, body)
    print("web dual upload ok")

    status, body = _post_multipart(
        base,
        "/v1/web/analyze/single-upload",
        fields={
            "profile": "auto",
            "grid": "3x4",
            "output_dir": str(out_dir / "web_single"),
            "html_report": "false",
            "with_innovation_engine": "true",
            "with_decision_center": "true",
            "with_process_advice": "true",
            "customer_id": customer_id,
            "customer_tier": "standard",
        },
        files={"image": ref},
    )
    _assert_200("web_single_upload", status, body)
    print("web single upload ok")

    dual_payload = {
        "reference": {"path": str(ref)},
        "film": {"path": str(film)},
        "grid": "3x4",
        "output_dir": str(out_dir / "dual"),
        "html_report": False,
        "include_report": True,
        "with_process_advice": True,
        "with_decision_center": True,
        "with_innovation_engine": True,
        "innovation_context": {
            "customer_id": customer_id,
            "material": "pvc_film",
            "sample_material": "melamine",
            "film_material": "pvc_film",
            "environment": "indoor_window",
            "current_ink_recipe": {"C": 42, "M": 31, "Y": 26, "K": 7},
        },
        "customer_id": customer_id,
        "customer_tier": "vip",
        "history": {
            "db_path": str(history_db),
            "line_id": line_id,
            "product_code": product_code,
            "lot_id": lot_id,
            "window": 60,
        },
    }
    status, dual = _post(base, "/v1/analyze/dual", dual_payload)
    _assert_200("analyze_dual", status, dual)
    report_path = dual.get("report_path")
    if not report_path:
        raise RuntimeError("analyze_dual missing report_path")
    print("dual analyze ok")

    batch_payload = {
        "image_paths": [str(ref), str(film)],
        "grid": "3x4",
        "output_dir": str(out_dir / "batch"),
        "with_decision_center": True,
        "with_innovation_engine": False,
        "history": {
            "db_path": str(history_db),
            "line_id": line_id,
            "product_code": product_code,
            "lot_id": lot_id,
            "window": 60,
        },
    }
    status, body = _post(base, "/v1/analyze/batch", batch_payload)
    _assert_200("analyze_batch", status, body)
    print("batch analyze ok")

    ensemble_payload = {
        "ensemble_images": [str(ref), str(film), str(ref)],
        "grid": "3x4",
        "output_dir": str(out_dir / "ensemble"),
        "with_decision_center": True,
        "with_innovation_engine": True,
        "innovation_context": {"customer_id": customer_id, "environment": "indoor_window"},
        "history": {
            "db_path": str(history_db),
            "line_id": line_id,
            "product_code": product_code,
            "lot_id": lot_id,
            "window": 60,
        },
    }
    status, body = _post(base, "/v1/analyze/ensemble", ensemble_payload)
    _assert_200("analyze_ensemble", status, body)
    print("ensemble analyze ok")

    status, runs = _get(base, "/v1/history/runs", {
        "db_path": str(history_db),
        "line_id": line_id,
        "product_code": product_code,
        "lot_id": lot_id,
        "limit": 10,
    })
    _assert_200("history_runs", status, runs)
    rows = runs.get("rows", []) if isinstance(runs, dict) else []
    run_id = rows[0].get("id") if rows else None
    if run_id is not None:
        status, body = _post(base, "/v1/outcome/record", {
            "db_path": str(history_db),
            "run_id": run_id,
            "outcome": "accepted",
            "severity": 0.0,
            "realized_cost": 0.0,
            "customer_rating": 90,
            "note": "e2e auto record",
        })
        _assert_200("outcome_record", status, body)
        print("outcome record ok")

    for path, params in [
        ("/v1/history/overview", {"db_path": str(history_db), "line_id": line_id, "product_code": product_code, "window": 200}),
        ("/v1/history/early-warning", {"db_path": str(history_db), "line_id": line_id, "product_code": product_code, "window": 200}),
        ("/v1/history/outcome-kpis", {"db_path": str(history_db), "line_id": line_id, "product_code": product_code, "window": 200}),
        ("/v1/history/policy-recommendation", {"db_path": str(history_db), "line_id": line_id, "product_code": product_code, "window": 200}),
        ("/v1/history/policy-lab", {"db_path": str(history_db), "line_id": line_id, "product_code": product_code, "window": 120}),
        ("/v1/history/counterfactual-twin", {"db_path": str(history_db), "line_id": line_id, "product_code": product_code, "window": 120}),
        ("/v1/history/open-bandit-policy", {"db_path": str(history_db), "line_id": line_id, "product_code": product_code, "window": 120}),
        ("/v1/history/drift-prediction", {"db_path": str(history_db), "line_id": line_id, "product_code": product_code, "window": 120, "threshold": 3.0}),
        ("/v1/history/executive", {"db_path": str(history_db), "line_id": line_id, "product_code": product_code, "window": 200}),
    ]:
        status, body = _get(base, path, params)
        _assert_200(path, status, body)
    print("history suite ok")

    status, body = _post(base, "/v1/analyze/spectral", {"sample_rgb": [160, 150, 130], "film_rgb": [163, 152, 128]})
    _assert_200("analyze_spectral", status, body)
    status, body = _post(base, "/v1/analyze/texture-aware", {
        "standard_delta_e": 2.5,
        "sample_texture_std": 22,
        "film_texture_std": 20,
        "texture_similarity": 0.88,
        "material_type": "wood",
    })
    _assert_200("texture_aware", status, body)
    status, body = _post(base, "/v1/predict/aging", {
        "lab": {"L": 64.1, "a": 3.8, "b": 16.1},
        "material": "pvc_film",
        "environment": "indoor_window",
    })
    _assert_200("predict_aging", status, body)
    status, body = _post(base, "/v1/predict/differential-aging", {
        "sample_lab": {"L": 62.5, "a": 3.2, "b": 14.8},
        "film_lab": {"L": 64.1, "a": 3.8, "b": 16.1},
        "sample_material": "melamine",
        "film_material": "pvc_film",
        "environment": "indoor_window",
    })
    _assert_200("predict_differential_aging", status, body)
    status, body = _post(base, "/v1/correct/ink-recipe", {
        "dL": 1.35,
        "dC": 0.86,
        "dH": -0.36,
        "current_recipe": {"C": 42, "M": 31, "Y": 26, "K": 7},
        "confidence": 0.85,
    })
    _assert_200("correct_ink_recipe", status, body)
    status, body = _post(base, "/v1/optimize/batch-blend", {
        "batches": [
            {"batch_id": "B001", "lab": {"L": 62.0, "a": 3.0, "b": 14.5}, "quantity": 100},
            {"batch_id": "B002", "lab": {"L": 63.5, "a": 3.5, "b": 15.0}, "quantity": 80},
            {"batch_id": "B003", "lab": {"L": 61.8, "a": 2.8, "b": 14.2}, "quantity": 120},
            {"batch_id": "B004", "lab": {"L": 64.2, "a": 3.9, "b": 16.0}, "quantity": 90},
            {"batch_id": "B005", "lab": {"L": 62.8, "a": 3.3, "b": 15.5}, "quantity": 110},
        ],
        "n_groups": 2,
        "customer_tiers": ["vip", "standard"],
    })
    _assert_200("optimize_batch_blend", status, body)
    print("innovation suite ok")

    for de, complained in [(1.1, False), (2.5, False), (3.2, True), (2.9, True)]:
        status, body = _post(base, "/v1/customer/acceptance-record", {
            "customer_id": customer_id,
            "delta_e": de,
            "complained": complained,
            "db_path": str(innovation_db),
        })
        _assert_200("acceptance_record", status, body)
    for path, params in [
        ("/v1/customer/acceptance-profile", {"customer_id": customer_id, "db_path": str(innovation_db)}),
        ("/v1/customer/complaint-probability", {"customer_id": customer_id, "delta_e": 2.8, "db_path": str(innovation_db)}),
        ("/v1/customer/dynamic-threshold", {"customer_id": customer_id, "target_complaint_rate": 0.05, "db_path": str(innovation_db)}),
    ]:
        status, body = _get(base, path, params)
        _assert_200(path, status, body)
    print("customer learning suite ok")

    status, body = _post(base, "/v1/passport/generate", {
        "lot_id": lot_id,
        "report_path": report_path,
        "db_path": str(innovation_db),
        "context": {"camera_id": "CAM-E2E", "illuminant": "D65"},
    })
    _assert_200("passport_generate", status, body)
    passport = body.get("passport", {}) if isinstance(body, dict) else {}
    passport_id = passport.get("passport_id")
    if not passport_id:
        raise RuntimeError("passport_generate missing passport_id")
    status, body = _post(base, "/v1/passport/verify", {
        "passport_id": passport_id,
        "db_path": str(innovation_db),
        "new_lab": {"L": 57.8, "a": 0.8, "b": 0.3},
    })
    _assert_200("passport_verify", status, body)
    print("passport suite ok")

    status, body = _post(base, "/v1/analyze/full-innovation", {
        "report_path": report_path,
        "context": {"customer_id": customer_id, "environment": "indoor_window"},
    })
    _assert_200("full_innovation", status, body)

    status, body = _post(base, "/v1/strategy/champion-challenger", {
        "db_path": str(history_db),
        "line_id": line_id,
        "product_code": product_code,
        "lot_id": lot_id,
        "window": 120,
    })
    _assert_200("champion_challenger", status, body)
    print("strategy suite ok")

    status, body = _post(base, "/v1/analyze/multi-observer", {
        "sample_lab": {"L": 62.5, "a": 3.2, "b": 14.8},
        "film_lab": {"L": 64.1, "a": 3.8, "b": 16.1},
        "target_age": 65,
        "sensitivity": "high",
    })
    _assert_200("multi_observer", status, body)

    status, body = _get(base, "/v1/quality/spc/from-history", {
        "db_path": str(history_db),
        "line_id": line_id,
        "product_code": product_code,
        "window": 120,
        "subgroup_size": 5,
        "spec_lower": 0.0,
        "spec_upper": 3.0,
    })
    _assert_200("spc_from_history", status, body)

    status, body = _post(base, "/v1/quality/spc/analyze", {
        "subgroups": [
            [1.52, 1.44, 1.61, 1.58, 1.49],
            [1.67, 1.72, 1.63, 1.68, 1.71],
            [1.75, 1.69, 1.73, 1.78, 1.70],
            [1.82, 1.79, 1.88, 1.81, 1.84],
            [1.91, 1.86, 1.95, 1.89, 1.92],
        ],
        "spec_lower": 0.0,
        "spec_upper": 3.0,
    })
    _assert_200("spc_analyze", status, body)

    status, body = _get(base, "/v1/report/shift/from-history", {
        "db_path": str(history_db),
        "line_id": line_id,
        "product_code": product_code,
        "window": 120,
        "hours": 8,
    })
    _assert_200("shift_report_from_history", status, body)

    status, body = _post(base, "/v1/report/shift/generate", {
        "shift_id": f"SHIFT-{run_tag}",
        "line_id": line_id,
        "hours": 8,
        "runs": [
            {"avg_de": 1.55, "pass": True, "decision": "AUTO_RELEASE", "confidence": 0.91, "product_code": product_code, "lot_id": lot_id, "dL": 0.12, "dC": -0.08, "dH": 0.04},
            {"avg_de": 2.11, "pass": True, "decision": "MANUAL_REVIEW", "confidence": 0.86, "product_code": product_code, "lot_id": lot_id, "dL": 0.25, "dC": -0.15, "dH": 0.09},
            {"avg_de": 2.65, "pass": False, "decision": "RECAPTURE_REQUIRED", "confidence": 0.58, "product_code": product_code, "lot_id": lot_id, "dL": 0.41, "dC": -0.26, "dH": 0.13},
        ],
    })
    _assert_200("shift_report_generate", status, body)

    for sid, de, passed in [("SUP-A", 1.52, True), ("SUP-A", 1.81, True), ("SUP-B", 2.66, False), ("SUP-B", 2.41, True)]:
        status, body = _post(base, "/v1/supplier/record", {
            "supplier_id": sid,
            "delta_e": de,
            "product": product_code,
            "passed": passed,
            "db_path": str(innovation_db),
        })
        _assert_200("supplier_record", status, body)
    status, body = _get(base, "/v1/supplier/scorecard", {"db_path": str(innovation_db)})
    _assert_200("supplier_scorecard_all", status, body)
    status, body = _get(base, "/v1/supplier/scorecard", {"supplier_id": "SUP-A", "db_path": str(innovation_db)})
    _assert_200("supplier_scorecard_one", status, body)

    std_code = f"STD-{run_tag}"
    status, body = _post(base, "/v1/standards/register", {
        "code": std_code,
        "lab": {"L": 62.5, "a": 3.2, "b": 14.8},
        "source": "e2e",
        "notes": "v1 baseline",
        "db_path": str(innovation_db),
    })
    _assert_200("standards_register_v1", status, body)
    status, body = _post(base, "/v1/standards/register", {
        "code": std_code,
        "lab": {"L": 62.9, "a": 3.4, "b": 15.0},
        "source": "e2e",
        "notes": "v2 revise",
        "db_path": str(innovation_db),
    })
    _assert_200("standards_register_v2", status, body)
    status, body = _get(base, "/v1/standards/get", {"code": std_code, "db_path": str(innovation_db)})
    _assert_200("standards_get", status, body)
    status, body = _post(base, "/v1/standards/compare", {
        "code": std_code,
        "measured_lab": {"L": 63.6, "a": 3.9, "b": 15.9},
        "db_path": str(innovation_db),
    })
    _assert_200("standards_compare", status, body)
    status, body = _get(base, "/v1/standards/version-drift", {"code": std_code, "db_path": str(innovation_db)})
    _assert_200("standards_version_drift", status, body)
    status, body = _get(base, "/v1/standards/list", {"db_path": str(innovation_db)})
    _assert_200("standards_list", status, body)
    print("v3 innovation suite ok")

    status, body = _get(base, "/v1/mvp2/manifest")
    _assert_200("mvp2_manifest", status, body)
    measured_rgb_24 = [
        [80 + (i * 7) % 150, 70 + (i * 9) % 150, 60 + (i * 11) % 150]
        for i in range(24)
    ]
    status, body = _post(base, "/v1/mvp2/ccm/calibrate", {"measured_rgb_24": measured_rgb_24})
    _assert_200("mvp2_ccm_calibrate", status, body)
    status, body = _post(base, "/v1/mvp2/matcher/strategy", {"scene": {"has_aruco": False, "pattern_type": "repeating", "sku_count": 20}})
    _assert_200("mvp2_matcher_strategy", status, body)
    status, body = _post(base, "/v1/mvp2/matcher/evaluate", {
        "match_result": {
            "method": "orb_ransac",
            "inlier_count": 42,
            "inlier_ratio": 0.78,
            "reproj_error": 0.9,
        }
    })
    _assert_200("mvp2_matcher_evaluate", status, body)
    ref_grid_mvp = [{"L": 62.0 + ((i % 6) - 3) * 0.05, "a": 3.2 + ((i % 5) - 2) * 0.03, "b": 14.8 + ((i % 7) - 3) * 0.04} for i in range(48)]
    sample_grid_mvp = [{"L": x["L"] + 0.6, "a": x["a"] + 0.4, "b": x["b"] + 0.2} for x in ref_grid_mvp]
    status, body = _post(base, "/v1/mvp2/pipeline/run", {
        "ref_grid": ref_grid_mvp,
        "sample_grid": sample_grid_mvp,
        "grid_shape": [6, 8],
        "capture_quality": "GOOD",
        "meta": {"product_code": product_code, "lot_id": lot_id, "operator": "E2E-OP"},
    })
    _assert_200("mvp2_pipeline_run", status, body)
    status, body = _get(base, "/v1/mvp2/sop", {"product_type": "decorative_film"})
    _assert_200("mvp2_sop", status, body)
    status, body = _get(base, "/v1/mvp2/sessions", {"last_n": 5})
    _assert_200("mvp2_sessions", status, body)
    print("mvp2 suite ok")

    status, body = _get(base, "/v1/lifecycle/manifest")
    _assert_200("lifecycle_manifest", status, body)
    status, body = _post(base, "/v1/lifecycle/preflight-check", {"temp": 28, "humidity": 65, "operator": "E2E-OP"})
    _assert_200("lifecycle_preflight", status, body)
    status, body = _post(base, "/v1/lifecycle/environment/record", {"temp": 28, "humidity": 65, "led_hours": 2200})
    _assert_200("lifecycle_environment_record", status, body)
    status, body = _post(base, "/v1/lifecycle/environment/check", {"temp": 28, "humidity": 65})
    _assert_200("lifecycle_environment_check", status, body)
    status, body = _post(base, "/v1/lifecycle/environment/compensate", {
        "lab": {"L": 62.0, "a": 3.2, "b": 14.8},
        "temp": 28,
        "humidity": 65,
    })
    _assert_200("lifecycle_environment_compensate", status, body)

    lot_a = f"SUB-{run_tag}-A"
    lot_b = f"SUB-{run_tag}-B"
    status, body = _post(base, "/v1/lifecycle/substrate/register", {"lot_id": lot_a, "lab": {"L": 95.2, "a": -0.3, "b": 1.8}, "supplier": "SUP-A", "material": "pvc"})
    _assert_200("lifecycle_substrate_register_a", status, body)
    status, body = _post(base, "/v1/lifecycle/substrate/register", {"lot_id": lot_b, "lab": {"L": 94.1, "a": -0.1, "b": 3.2}, "supplier": "SUP-A", "material": "pvc"})
    _assert_200("lifecycle_substrate_register_b", status, body)
    status, body = _post(base, "/v1/lifecycle/substrate/compare", {"lot_id": lot_b, "ref_lot_id": lot_a})
    _assert_200("lifecycle_substrate_compare", status, body)

    status, body = _post(base, "/v1/lifecycle/wet-dry/predict", {
        "wet_lab": {"L": 64.0, "a": 3.5, "b": 15.2},
        "ink_type": "solvent_gravure",
        "elapsed_hours": 1.0,
    })
    _assert_200("lifecycle_wet_dry_predict", status, body)
    status, body = _post(base, "/v1/lifecycle/wet-dry/learn", {
        "wet_lab": {"L": 64.0, "a": 3.5, "b": 15.2},
        "dry_lab": {"L": 63.0, "a": 3.8, "b": 15.5},
        "ink_type": "solvent_gravure",
        "dry_hours": 4.0,
    })
    _assert_200("lifecycle_wet_dry_learn", status, body)

    status, body = _post(base, "/v1/lifecycle/run-monitor/target", {"target_lab": {"L": 62.0, "a": 3.2, "b": 14.8}, "tolerance": 2.5})
    _assert_200("lifecycle_run_monitor_target", status, body)
    for idx in range(1, 9):
        status, body = _post(base, "/v1/lifecycle/run-monitor/add-sample", {
            "seq": idx,
            "lab": {"L": 62.0 + idx * 0.05, "a": 3.2 + idx * 0.02, "b": 14.8 + idx * 0.03},
        })
        _assert_200("lifecycle_run_monitor_add_sample", status, body)
    status, body = _get(base, "/v1/lifecycle/run-monitor/report")
    _assert_200("lifecycle_run_monitor_report", status, body)

    batch_id = f"BATCH-{run_tag}-A"
    status, body = _post(base, "/v1/lifecycle/cross-batch/register", {
        "batch_id": batch_id,
        "data": {
            "lab": {"L": 62.0, "a": 3.2, "b": 14.8},
            "recipe": {"C": 42, "M": 35, "Y": 26, "K": 7},
            "temp": 24,
            "substrate_lab": {"L": 95.2, "a": -0.3, "b": 1.8},
            "ink_lot": "INK-E2E-A",
        },
    })
    _assert_200("lifecycle_cross_batch_register", status, body)
    status, body = _post(base, "/v1/lifecycle/cross-batch/match", {
        "target_batch_id": batch_id,
        "current_conditions": {
            "temp": 30,
            "substrate_lab": {"L": 94.1, "a": -0.1, "b": 3.2},
            "ink_lot": "INK-E2E-B",
        },
    })
    _assert_200("lifecycle_cross_batch_match", status, body)

    for lot_id_ink, lab in [
        ("INK-E2E-A", {"L": 55.0, "a": -30.0, "b": -40.0}),
        ("INK-E2E-B", {"L": 54.6, "a": -29.5, "b": -39.2}),
        ("INK-E2E-C", {"L": 55.2, "a": -30.3, "b": -40.4}),
    ]:
        status, body = _post(base, "/v1/lifecycle/ink-lot/register", {"ink_model": "CYAN-PRO", "lot_id": lot_id_ink, "lab": lab})
        _assert_200("lifecycle_ink_lot_register", status, body)
    status, body = _get(base, "/v1/lifecycle/ink-lot/variation", {"ink_model": "CYAN-PRO"})
    _assert_200("lifecycle_ink_lot_variation", status, body)

    status, body = _post(base, "/v1/lifecycle/calibration/register", {"source": "lightbox_d65", "interval_hours": 168})
    _assert_200("lifecycle_calibration_register", status, body)
    status, body = _get(base, "/v1/lifecycle/calibration/status")
    _assert_200("lifecycle_calibration_status", status, body)
    status, body = _post(base, "/v1/lifecycle/calibration/record", {"source": "lightbox_d65"})
    _assert_200("lifecycle_calibration_record", status, body)

    edge_grid = [1.5 + (0.35 if (i % 8 == 0 or i % 8 == 7 or i < 8 or i >= 40) else 0.0) for i in range(48)]
    status, body = _post(base, "/v1/lifecycle/edge/analyze", {"de_grid": edge_grid, "grid_shape": [6, 8]})
    _assert_200("lifecycle_edge_analyze", status, body)

    roller_id = f"ROLLER-{run_tag}"
    status, body = _post(base, "/v1/lifecycle/roller/register", {"roller_id": roller_id, "roller_type": "gravure", "max_meters": 500000})
    _assert_200("lifecycle_roller_register", status, body)
    status, body = _post(base, "/v1/lifecycle/roller/update", {"roller_id": roller_id, "meters": 380000, "avg_de": 1.8})
    _assert_200("lifecycle_roller_update", status, body)
    status, body = _get(base, "/v1/lifecycle/roller/status", {"roller_id": roller_id})
    _assert_200("lifecycle_roller_status", status, body)

    golden_code = f"GOLD-{run_tag}"
    status, body = _post(base, "/v1/lifecycle/golden/register", {"code": golden_code, "lab": {"L": 62.0, "a": 3.2, "b": 14.8}, "max_age_days": 90})
    _assert_200("lifecycle_golden_register", status, body)
    status, body = _post(base, "/v1/lifecycle/golden/check", {"code": golden_code, "measured_lab": {"L": 62.4, "a": 3.3, "b": 15.1}})
    _assert_200("lifecycle_golden_check", status, body)

    status, body = _post(base, "/v1/lifecycle/operator/record", {"operator": "E2E-OP", "attempts": 1, "final_de": 1.3, "target_de": 2.5})
    _assert_200("lifecycle_operator_record_1", status, body)
    status, body = _post(base, "/v1/lifecycle/operator/record", {"operator": "E2E-OP", "attempts": 2, "final_de": 1.9, "target_de": 2.5})
    _assert_200("lifecycle_operator_record_2", status, body)
    status, body = _get(base, "/v1/lifecycle/operator/profile", {"operator": "E2E-OP"})
    _assert_200("lifecycle_operator_profile", status, body)
    status, body = _get(base, "/v1/lifecycle/operator/leaderboard")
    _assert_200("lifecycle_operator_leaderboard", status, body)

    trace_lot = f"TRACE-{run_tag}"
    for stage, data in [
        ("ink_receipt", {"ink_model": "CYAN-PRO", "lot": "INK-E2E-B"}),
        ("substrate_receipt", {"lot": lot_b, "substrate_db": 1.4}),
        ("printing", {"dry_temp": 72, "line_speed": 90}),
        ("inspection", {"avg_de": 2.1, "tier": "MARGINAL"}),
    ]:
        status, body = _post(base, "/v1/lifecycle/trace/add-event", {
            "lot_id": trace_lot,
            "stage": stage,
            "data": data,
            "idempotency_key": f"trace-{trace_lot}-{stage}",
        })
        _assert_200("lifecycle_trace_add_event", status, body)
    status, body = _get(base, "/v1/lifecycle/trace/chain", {"lot_id": trace_lot})
    _assert_200("lifecycle_trace_chain", status, body)
    status, body = _post(base, "/v1/lifecycle/trace/root-cause", {"lot_id": trace_lot, "symptom": "偏黄"})
    _assert_200("lifecycle_trace_root_cause", status, body)
    status, body = _post(base, "/v1/lifecycle/trace/add-event", {
        "lot_id": trace_lot,
        "stage": "inspection",
        "data": {"avg_de": 2.1, "tier": "MARGINAL"},
        "idempotency_key": f"trace-{trace_lot}-inspection",
    })
    _assert_200("lifecycle_trace_add_event_idempotent", status, body)
    print("lifecycle blindspot suite ok")

    status, body = _get(base, "/v1/lifecycle/advanced/manifest")
    _assert_200("lifecycle_advanced_manifest", status, body)
    status, body = _post(base, "/v1/lifecycle/time-stability/record", {
        "lot_id": trace_lot,
        "elapsed_hours": 1.0,
        "lab": {"L": 62.0, "a": 3.2, "b": 14.8},
        "stage": "first",
        "verdict": "PASS",
    })
    _assert_200("lifecycle_time_stability_record_1", status, body)
    status, body = _post(base, "/v1/lifecycle/time-stability/record", {
        "lot_id": trace_lot,
        "elapsed_hours": 4.0,
        "lab": {"L": 61.3, "a": 3.5, "b": 15.6},
        "stage": "recheck",
        "verdict": "FAIL",
    })
    _assert_200("lifecycle_time_stability_record_2", status, body)
    status, body = _get(base, "/v1/lifecycle/time-stability/report", {"lot_id": trace_lot})
    _assert_200("lifecycle_time_stability_report", status, body)

    status, body = _post(base, "/v1/lifecycle/process-coupling/evaluate", {
        "route": "gravure",
        "params": {"viscosity": 29, "line_speed": 116, "dry_temp": 77, "tension": 28, "pressure": 3.7},
    })
    _assert_200("lifecycle_process_coupling_evaluate", status, body)
    status, body = _post(base, "/v1/lifecycle/process-coupling/reverse-infer", {
        "route": "gravure",
        "color_symptom": {"dL": -0.8, "db": 1.1},
        "params": {"viscosity": 29, "line_speed": 116, "dry_temp": 77, "tension": 28, "pressure": 3.7},
    })
    _assert_200("lifecycle_process_coupling_reverse_infer", status, body)

    status, body = _post(base, "/v1/lifecycle/appearance/evaluate", {
        "lab": {"L": 62.0, "a": 3.2, "b": 14.8},
        "film_props": {"opacity": 0.42, "haze": 20, "gloss": 66, "thickness_um": 88, "emboss_direction": "md"},
    })
    _assert_200("lifecycle_appearance_evaluate", status, body)
    status, body = _post(base, "/v1/lifecycle/metamerism/evaluate", {
        "lab_d65": {"L": 62.0, "a": 3.2, "b": 14.8},
        "alt_lights": {
            "A_2856K": {"L": 61.4, "a": 3.4, "b": 15.4},
            "F11_store": {"L": 61.7, "a": 3.35, "b": 15.2},
        },
        "film_props": {"opacity": 0.42, "haze": 20, "gloss": 66},
    })
    _assert_200("lifecycle_metamerism_evaluate", status, body)
    status, body = _post(base, "/v1/lifecycle/post-process/evaluate", {
        "lab": {"L": 62.0, "a": 3.2, "b": 14.8},
        "steps": ["lamination", "adhesive", "hot_press"],
        "context": {"press_temp": 78, "storage_days": 12},
    })
    _assert_200("lifecycle_post_process_evaluate", status, body)
    status, body = _post(base, "/v1/lifecycle/storage/evaluate", {
        "lab": {"L": 62.0, "a": 3.2, "b": 14.8},
        "storage_days": 45,
        "temp_c": 34,
        "humidity_pct": 76,
        "uv_hours": 18,
        "vibration_index": 0.8,
    })
    _assert_200("lifecycle_storage_evaluate", status, body)

    for ridx in range(1, 7):
        status, body = _post(base, "/v1/lifecycle/msa/record", {
            "lot_id": trace_lot,
            "sample_id": f"S-{1 + (ridx % 2)}",
            "device_id": "E2E-DEV-A" if ridx % 2 else "E2E-DEV-B",
            "operator_id": "E2E-OP" if ridx <= 3 else "E2E-OP-2",
            "lab": {"L": 62.0 + ridx * 0.03, "a": 3.2 + ridx * 0.01, "b": 14.8 + ridx * 0.02},
        })
        _assert_200("lifecycle_msa_record", status, body)
    status, body = _get(base, "/v1/lifecycle/msa/report", {"lot_id": trace_lot})
    _assert_200("lifecycle_msa_report", status, body)

    for v in [1.2, 1.25, 1.22, 1.28, 1.35, 1.4, 1.48, 1.55, 1.62]:
        status, body = _post(base, "/v1/lifecycle/spc/record", {"stream_id": trace_lot, "value": v})
        _assert_200("lifecycle_spc_record", status, body)
    status, body = _get(base, "/v1/lifecycle/spc/report", {"stream_id": trace_lot})
    _assert_200("lifecycle_spc_report", status, body)

    status, body = _post(base, "/v1/lifecycle/roll/register", {
        "lot_id": trace_lot,
        "roll_id": f"{trace_lot}-R1",
        "length_m": 180.0,
        "machine_id": "E2E-MC-A",
        "shift": "night",
    })
    _assert_200("lifecycle_roll_register", status, body)
    status, body = _post(base, "/v1/lifecycle/roll/mark-zone", {
        "roll_id": f"{trace_lot}-R1",
        "zone_type": "restart_zone",
        "meter_start": 0,
        "meter_end": 20,
        "reason": "restart",
    })
    _assert_200("lifecycle_roll_mark_zone", status, body)
    for i in range(1, 22):
        meter = i * 8.0
        de_val = 1.2 if i <= 14 else 2.5 + (i - 14) * 0.08
        status, body = _post(base, "/v1/lifecycle/roll/add-measurement", {
            "roll_id": f"{trace_lot}-R1",
            "meter_pos": meter,
            "de": de_val,
            "source": "e2e",
        })
        _assert_200("lifecycle_roll_add_measurement", status, body)
    status, body = _get(base, "/v1/lifecycle/roll/summary", {"roll_id": f"{trace_lot}-R1"})
    _assert_200("lifecycle_roll_summary", status, body)
    status, body = _get(base, "/v1/lifecycle/roll/lot-summary", {"lot_id": trace_lot})
    _assert_200("lifecycle_roll_lot_summary", status, body)

    status, body = _post(base, "/v1/lifecycle/customer/register-profile", {
        "customer_id": "E2E-CUST-VIP",
        "profile": {
            "default_tolerance": 2.2,
            "sku_tolerance": {product_code: 1.9},
            "sensitivity": {"yellow": 1.3, "uniformity": 1.2},
        },
    })
    _assert_200("lifecycle_customer_register_profile", status, body)
    status, body = _post(base, "/v1/lifecycle/customer/evaluate", {
        "customer_id": "E2E-CUST-VIP",
        "sku": product_code,
        "scenario": {"light_source": "warm"},
        "metrics": {"avg_de": 1.9, "max_de": 3.2, "db": 0.9, "uniformity_std": 0.45},
    })
    _assert_200("lifecycle_customer_evaluate", status, body)

    status, body = _post(base, "/v1/lifecycle/retest/record", {
        "lot_id": trace_lot,
        "test_type": "first",
        "device_id": "E2E-DEV-A",
        "operator": "E2E-OP",
        "raw_result": {"avg_de": 1.2},
        "compensated_result": {"avg_de": 1.0},
        "judgment_result": {"tier": "PASS"},
    })
    _assert_200("lifecycle_retest_record_1", status, body)
    status, body = _post(base, "/v1/lifecycle/retest/record", {
        "lot_id": trace_lot,
        "test_type": "retest",
        "device_id": "E2E-DEV-B",
        "operator": "E2E-OP-2",
        "raw_result": {"avg_de": 2.9},
        "compensated_result": {"avg_de": 2.7},
        "judgment_result": {"tier": "FAIL"},
    })
    _assert_200("lifecycle_retest_record_2", status, body)
    status, body = _get(base, "/v1/lifecycle/retest/dispute-report", {"lot_id": trace_lot})
    _assert_200("lifecycle_retest_dispute_report", status, body)

    status, body = _post(base, "/v1/lifecycle/machine/record", {
        "machine_id": "E2E-MC-A",
        "plant_id": "P1",
        "sku": product_code,
        "dL": -0.5,
        "da": 0.1,
        "db": 0.7,
    })
    _assert_200("lifecycle_machine_record", status, body)
    status, body = _get(base, "/v1/lifecycle/machine/fingerprint", {"machine_id": "E2E-MC-A"})
    _assert_200("lifecycle_machine_fingerprint", status, body)
    status, body = _get(base, "/v1/lifecycle/machine/chronic-bias")
    _assert_200("lifecycle_machine_chronic_bias", status, body)

    status, body = _post(base, "/v1/lifecycle/learning/record", {
        "context_key": f"{product_code}|E2E-MC-A",
        "predicted_cause": "ink_lot",
        "actual_cause": "substrate",
        "success": False,
        "rule_source": "heuristic",
    })
    _assert_200("lifecycle_learning_record", status, body)
    status, body = _get(base, "/v1/lifecycle/learning/priorities", {"context_key": f"{product_code}|E2E-MC-A"})
    _assert_200("lifecycle_learning_priorities", status, body)

    status, body = _post(base, "/v1/lifecycle/state/transition", {
        "lot_id": trace_lot,
        "to_state": "material_received",
        "actor": "E2E-OP",
        "reason": "materials checked",
    })
    _assert_200("lifecycle_state_transition_1", status, body)
    status, body = _post(base, "/v1/lifecycle/state/transition", {
        "lot_id": trace_lot,
        "to_state": "recipe_prepared",
        "actor": "E2E-OP",
        "reason": "recipe loaded",
        "force": True,
    })
    _assert_200("lifecycle_state_transition_2", status, body)
    status, body = _get(base, "/v1/lifecycle/state/snapshot", {"lot_id": trace_lot})
    _assert_200("lifecycle_state_snapshot", status, body)

    status, body = _post(base, "/v1/lifecycle/failure-mode/register", {
        "mode_id": "FM-E2E-CUSTOM",
        "desc": "custom failure mode",
        "severity": 7,
        "occurrence": 3,
        "detectability": 4,
        "category": "process",
    })
    _assert_200("lifecycle_failure_mode_register", status, body)
    status, body = _get(base, "/v1/lifecycle/failure-mode/list")
    _assert_200("lifecycle_failure_mode_list", status, body)
    status, body = _post(base, "/v1/lifecycle/failure-mode/capa-candidates", {
        "triggers": ["calibration_overdue", "trace_missing_required_events"],
    })
    _assert_200("lifecycle_failure_mode_capa_candidates", status, body)

    status, body = _post(base, "/v1/lifecycle/alerts/push", {
        "alert_type": "E2E_MANUAL_ALERT",
        "severity": "high",
        "message": "manual alert check",
        "source": "e2e",
        "dedup_key": f"e2e|{trace_lot}|manual-alert",
    })
    _assert_200("lifecycle_alerts_push", status, body)
    status, body = _get(base, "/v1/lifecycle/alerts/summary", {"last_n": 20})
    _assert_200("lifecycle_alerts_summary", status, body)

    status, body = _post(base, "/v1/lifecycle/rules/register", {
        "version": "LIFE-RULE-E2E-R2",
        "active_from_ts": 0,
        "scope": {"sku_prefixes": ["SKU"]},
        "params": {"process_risk_review": 0.4},
        "notes": "e2e",
    })
    _assert_200("lifecycle_rules_register", status, body)
    status, body = _get(base, "/v1/lifecycle/rules/list")
    _assert_200("lifecycle_rules_list", status, body)

    status, body = _post(base, "/v1/lifecycle/version-link/record", {
        "lot_id": trace_lot,
        "recipe_code": product_code,
        "recipe_version": 2,
        "rule_version": "LIFE-RULE-E2E-R2",
        "model_version": "MODEL-COLOR-V3.2",
        "pipeline_policy_version": "POLICY-2026.04-R2",
        "notes": "e2e link",
    })
    _assert_200("lifecycle_version_link_record", status, body)
    status, body = _get(base, "/v1/lifecycle/version-link/get", {"lot_id": trace_lot})
    _assert_200("lifecycle_version_link_get", status, body)

    status, body = _post(base, "/v1/lifecycle/trace/revision", {
        "lot_id": trace_lot,
        "target_event_id": f"{trace_lot}-00002",
        "actor": "E2E-QA",
        "reason": "补录供应商信息",
        "patch": {"supplier": "SUP-E2E"},
    })
    _assert_200("lifecycle_trace_revision", status, body)
    status, body = _post(base, "/v1/lifecycle/trace/override", {
        "lot_id": trace_lot,
        "decision_ref": "E2E-DEC-001",
        "actor": "E2E-QA",
        "approved_by": "E2E-MANAGER",
        "reason": "客户紧急让步放行",
    })
    _assert_200("lifecycle_trace_override", status, body)

    status, body = _post(base, "/v1/lifecycle/decision/integrated", {
        "lot_id": trace_lot,
        "base_decision": {"tier": "PASS", "confidence": 0.72, "quality_gate": {"valid": True, "suspicious_ratio": 0.04}},
        "color_metrics": {"avg_de": 1.8, "max_de": 3.2, "db": 0.9, "uniformity_std": 0.47},
        "process_params": {"viscosity": 29, "line_speed": 116, "dry_temp": 77, "tension": 28, "pressure": 3.7},
        "process_route": "gravure",
        "film_props": {"opacity": 0.42, "haze": 20, "gloss": 66, "thickness_um": 88, "emboss_direction": "md"},
        "scenario": {"light_source": "warm"},
        "customer_id": "E2E-CUST-VIP",
        "sku": product_code,
        "current_lab": {"L": 62.0, "a": 3.2, "b": 14.8},
        "alt_light_labs": {
            "A_2856K": {"L": 61.4, "a": 3.4, "b": 15.4},
            "F11_store": {"L": 61.7, "a": 3.35, "b": 15.2},
        },
        "post_process_steps": ["lamination", "adhesive", "hot_press"],
        "storage_context": {"storage_days": 45, "temp_c": 34, "humidity_pct": 76, "uv_hours": 18, "vibration_index": 0.8},
        "spc_stream_id": trace_lot,
        "meta": {"environment_severity": 0.52, "golden_status": "ok", "symptom": "yellow shift", "roll_id": f"{trace_lot}-R1", "idempotency_key": f"e2e-int-{trace_lot}"},
    })
    _assert_200("lifecycle_decision_integrated", status, body)
    assess_result = body.get("result", {})
    status, body = _post(base, "/v1/lifecycle/decision/role-view", {
        "role": "quality_manager",
        "assessment": assess_result,
    })
    _assert_200("lifecycle_decision_role_view", status, body)
    status, body = _get(base, "/v1/lifecycle/decision/snapshots", {"lot_id": trace_lot, "last_n": 5})
    _assert_200("lifecycle_decision_snapshots", status, body)
    rows = body.get("result", {}).get("rows", [])
    if rows:
        sid = rows[-1].get("snapshot_id")
        if sid:
            status, body = _post(base, "/v1/lifecycle/decision/replay", {
                "snapshot_id": sid,
                "force_lifecycle_rule_version": "LIFE-RULE-E2E-R2",
                "meta_patch": {"golden_status": "ok"},
            })
            _assert_200("lifecycle_decision_replay", status, body)
            status, body = _post(base, "/v1/lifecycle/decision/simulate-rules", {
                "snapshot_id": sid,
                "rule_versions": ["LIFE-RULE-E2E-R2"],
                "meta_patch": {"golden_status": "ok"},
            })
            _assert_200("lifecycle_decision_simulate_rules", status, body)
            status, body = _post(base, "/v1/lifecycle/decision/simulate-rules-batch", {
                "snapshot_ids": [sid],
                "rule_versions": ["LIFE-RULE-E2E-R2"],
                "meta_patch": {"golden_status": "ok"},
            })
            _assert_200("lifecycle_decision_simulate_rules_batch", status, body)
    status, body = _get(base, "/v1/lifecycle/case/list", {"lot_id": trace_lot, "last_n": 10})
    _assert_200("lifecycle_case_list", status, body)
    case_rows = body.get("result", {}).get("rows", [])
    if not case_rows:
        status, body = _post(base, "/v1/lifecycle/case/open", {
            "lot_id": trace_lot,
            "case_type": "nonconformance",
            "issue": "manual e2e case bootstrap",
            "severity": "high",
            "source": "e2e",
            "created_by": "E2E-QA",
        })
        _assert_200("lifecycle_case_open", status, body)
        status, body = _get(base, "/v1/lifecycle/case/list", {"lot_id": trace_lot, "last_n": 10})
        _assert_200("lifecycle_case_list_after_open", status, body)
        case_rows = body.get("result", {}).get("rows", [])
    if case_rows:
        cid = case_rows[-1].get("case_id")
        if cid:
            status, body = _get(base, "/v1/lifecycle/case/get", {"case_id": cid})
            _assert_200("lifecycle_case_get", status, body)
            action_id = None
            status, body = _post(base, "/v1/lifecycle/case/action", {
                "case_id": cid,
                "action_type": "temporary_containment",
                "owner": "E2E-QA",
                "description": "hold shipment and remeasure tail segment",
                "actor": "E2E-QA",
                "priority": 1,
                "mandatory": True,
                "due_ts": time.time() + 7200,
            })
            _assert_200("lifecycle_case_action", status, body)
            action_id = body.get("result", {}).get("action_id")
            status, body = _post(base, "/v1/lifecycle/case/transition", {
                "case_id": cid,
                "to_state": "investigating",
                "actor": "E2E-QA",
                "reason": "start investigation",
            })
            _assert_200("lifecycle_case_transition", status, body)
            status, body = _post(base, "/v1/lifecycle/case/transition", {
                "case_id": cid,
                "to_state": "action_planned",
                "actor": "E2E-QA",
                "reason": "plan containment",
            })
            _assert_200("lifecycle_case_transition_plan", status, body)
            status, body = _post(base, "/v1/lifecycle/case/transition", {
                "case_id": cid,
                "to_state": "action_in_progress",
                "actor": "E2E-QA",
                "reason": "execute containment",
            })
            _assert_200("lifecycle_case_transition_execute", status, body)
            if action_id:
                status, body = _post(base, "/v1/lifecycle/case/action/complete", {
                    "case_id": cid,
                    "action_id": action_id,
                    "actor": "E2E-QA",
                    "result": {"note": "shipment held and tail segment quarantined"},
                    "effectiveness": 0.84,
                })
                _assert_200("lifecycle_case_action_complete", status, body)
            status, body = _post(base, "/v1/lifecycle/case/waiver", {
                "case_id": cid,
                "actor": "E2E-QA",
                "approved_by": "E2E-MANAGER",
                "reason": "urgent shipment with customer confirmation",
                "approver_role": "quality_manager",
                "risk_level": "high",
                "customer_tier": "standard",
                "waiver_type": "release_with_risk",
            })
            _assert_200("lifecycle_case_waiver", status, body)
            status, body = _get(base, "/v1/lifecycle/case/sla-report", {"case_id": cid})
            _assert_200("lifecycle_case_sla_report", status, body)
            status, body = _get(base, "/v1/lifecycle/case/store-status")
            _assert_200("lifecycle_case_store_status", status, body)
            status, body = _get(base, "/v1/lifecycle/case/store-check")
            _assert_200("lifecycle_case_store_check", status, body)
            if not bool(body.get("result", {}).get("ok", False)):
                raise RuntimeError(f"lifecycle_case_store_check returned not ok: {body}")
            status, body = _post(base, "/v1/lifecycle/case/transition", {
                "case_id": cid,
                "to_state": "verification",
                "actor": "E2E-QA",
                "reason": "verify closure",
            })
            _assert_200("lifecycle_case_transition_verify", status, body)
            status, body = _post(base, "/v1/lifecycle/case/close", {
                "case_id": cid,
                "actor": "E2E-QA",
                "verification": {"result": "effective", "evidence": "e2e closure path"},
            })
            _assert_200("lifecycle_case_close", status, body)
            if not bool(body.get("result", {}).get("ok", False)):
                raise RuntimeError(f"lifecycle_case_close returned not ok: {body}")
    status, body = _post(base, "/v1/lifecycle/report/release", {
        "lot_id": trace_lot,
        "assessment": assess_result,
        "metrics": {"avg_de": 1.8, "max_de": 3.2},
        "audience": "internal",
    })
    _assert_200("lifecycle_report_release", status, body)
    status, body = _post(base, "/v1/lifecycle/report/complaint", {
        "lot_id": trace_lot,
        "symptom": "yellow shift",
        "severity": "high",
    })
    _assert_200("lifecycle_report_complaint", status, body)
    status, body = _get(base, "/v1/lifecycle/known-boundaries")
    _assert_200("lifecycle_known_boundaries", status, body)
    print("lifecycle advanced suite ok")

    print("=== E2E PASSED ===")
    print(f"base_url: {base}")
    print(f"report_path: {report_path}")
    print(f"history_db: {history_db}")
    print(f"innovation_db: {innovation_db}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
