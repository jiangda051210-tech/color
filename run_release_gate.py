from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


def _tail_lines(text: str, max_lines: int = 40) -> str:
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text
    return "\n".join(lines[-max_lines:])


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Run Elite release gate: quick-check + full E2E + optional role boundary.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8877", help="API base URL.")
    parser.add_argument("--history-db", default=str((root / "quality_history.sqlite").resolve()), help="History DB path.")
    parser.add_argument(
        "--report-out",
        default=str((root / "out_e2e_flow" / "release_gate_result.json").resolve()),
        help="Where to write the gate result JSON.",
    )
    parser.add_argument("--api-key", default="", help="Generic API key used by quick-check and E2E.")
    parser.add_argument("--admin-key", default="", help="Admin key used by E2E alert-test and role boundary.")
    parser.add_argument("--tenant-id", default="", help="Tenant id for quick-check/E2E shared requests.")
    parser.add_argument("--tenant-header", default="x-tenant-id", help="Tenant header name.")
    parser.add_argument("--viewer-key", default="", help="Viewer key for role boundary checks.")
    parser.add_argument("--operator-key", default="", help="Operator key for role boundary checks.")
    parser.add_argument("--role-tenant", default="", help="Allowed tenant for role boundary checks.")
    parser.add_argument("--wrong-tenant", default="tenant-not-allowed", help="Denied tenant for negative role checks.")
    parser.add_argument("--skip-role-boundary", action="store_true", help="Skip role boundary checks.")
    parser.add_argument(
        "--require-role-boundary",
        action="store_true",
        help="Fail release gate if role boundary checks cannot be executed.",
    )
    parser.add_argument("--strict-alert-test", action="store_true", help="Treat 403 alert-test as E2E failure.")
    parser.add_argument(
        "--quick-check",
        action="store_true",
        help="Compatibility flag for CI/Makefile. Currently equivalent to default behavior.",
    )
    parser.add_argument("--slo-availability-target", type=float, default=99.5, help="SLO target for availability percentage.")
    parser.add_argument("--slo-p95-target-ms", type=float, default=1200.0, help="SLO target for p95 latency in ms.")
    parser.add_argument("--require-slo-healthy", action="store_true", help="Fail if /v1/system/slo status is not healthy.")
    return parser.parse_args(argv)


def _request(
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    payload: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> tuple[int, Any]:
    req_headers = dict(headers or {})
    data: bytes | None = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, method=method.upper(), data=data, headers=req_headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:  # noqa: S310
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                body = json.loads(raw)
            except Exception:
                body = raw
            return int(resp.status), body
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw)
        except Exception:
            body = raw
        return int(exc.code), body
    except Exception as exc:  # noqa: BLE001
        return -1, {"error": str(exc)}


def _build_headers(api_key: str = "", tenant_id: str = "", tenant_header: str = "x-tenant-id") -> dict[str, str]:
    headers = {"Accept": "application/json"}
    key = api_key.strip()
    if key:
        headers["x-api-key"] = key
    tenant = tenant_id.strip()
    if tenant:
        headers[tenant_header.strip() or "x-tenant-id"] = tenant
    return headers


def _url_with_query(base_url: str, path: str, params: dict[str, Any] | None = None) -> str:
    url = f"{base_url.rstrip('/')}{path}"
    if not params:
        return url
    query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    if not query:
        return url
    return f"{url}?{query}"


def _run_subprocess(name: str, cmd: list[str], cwd: Path, env: dict[str, str]) -> dict[str, Any]:
    started = time.time()
    proc = subprocess.run(cmd, cwd=str(cwd), env=env, capture_output=True, text=True, errors="replace")
    elapsed = round(time.time() - started, 3)
    return {
        "name": name,
        "status": "passed" if proc.returncode == 0 else "failed",
        "exit_code": int(proc.returncode),
        "elapsed_sec": elapsed,
        "command": cmd,
        "stdout_tail": _tail_lines(proc.stdout, max_lines=80),
        "stderr_tail": _tail_lines(proc.stderr, max_lines=80),
    }


def _parse_host_port(base_url: str) -> tuple[str, int]:
    parsed = urllib.parse.urlsplit(base_url.strip())
    if not parsed.scheme or not parsed.hostname:
        raise ValueError(f"invalid base url: {base_url}")
    if parsed.port:
        return parsed.hostname, int(parsed.port)
    return parsed.hostname, 443 if parsed.scheme.lower() == "https" else 80


def _role_case(
    name: str,
    method: str,
    url: str,
    expected: int,
    headers: dict[str, str],
) -> dict[str, Any]:
    status, body = _request(method, url, headers=headers)
    return {
        "name": name,
        "expected": expected,
        "actual": status,
        "pass": status == expected,
        "body": body,
    }


def _run_role_boundary(
    *,
    base_url: str,
    history_db: str,
    tenant_header: str,
    role_tenant: str,
    wrong_tenant: str,
    viewer_key: str,
    operator_key: str,
    admin_key: str,
    tenant_enforced: bool,
    allowed_tenant_count: int,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    db_url = _url_with_query(base_url, "/v1/system/ops-summary", {"db_path": history_db})

    if tenant_enforced:
        checks.append(
            _role_case(
                "viewer missing tenant auth-info",
                "GET",
                _url_with_query(base_url, "/v1/system/auth-info"),
                400,
                _build_headers(api_key=viewer_key, tenant_id="", tenant_header=tenant_header),
            )
        )
    if allowed_tenant_count > 0:
        denied_tenant = wrong_tenant if wrong_tenant != role_tenant else f"{wrong_tenant}-x"
        checks.append(
            _role_case(
                "viewer denied tenant auth-info",
                "GET",
                _url_with_query(base_url, "/v1/system/auth-info"),
                403,
                _build_headers(api_key=viewer_key, tenant_id=denied_tenant, tenant_header=tenant_header),
            )
        )

    checks.extend(
        [
            _role_case(
                "viewer allowed tenant auth-info",
                "GET",
                _url_with_query(base_url, "/v1/system/auth-info"),
                200,
                _build_headers(api_key=viewer_key, tenant_id=role_tenant, tenant_header=tenant_header),
            ),
            _role_case(
                "viewer allowed tenant ops-summary",
                "GET",
                db_url,
                403,
                _build_headers(api_key=viewer_key, tenant_id=role_tenant, tenant_header=tenant_header),
            ),
            _role_case(
                "operator allowed tenant ops-summary",
                "GET",
                db_url,
                200,
                _build_headers(api_key=operator_key, tenant_id=role_tenant, tenant_header=tenant_header),
            ),
            _role_case(
                "operator allowed tenant alert-test",
                "POST",
                _url_with_query(base_url, "/v1/system/alert-test", {"level": "warning", "title": "gate", "message": "operator"}),
                403,
                _build_headers(api_key=operator_key, tenant_id=role_tenant, tenant_header=tenant_header),
            ),
            _role_case(
                "admin allowed tenant alert-test",
                "POST",
                _url_with_query(base_url, "/v1/system/alert-test", {"level": "warning", "title": "gate", "message": "admin"}),
                200,
                _build_headers(api_key=admin_key, tenant_id=role_tenant, tenant_header=tenant_header),
            ),
        ]
    )
    passed = sum(1 for row in checks if row.get("pass"))
    return {
        "status": "passed" if passed == len(checks) else "failed",
        "passed_count": passed,
        "total_count": len(checks),
        "checks": checks,
    }


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    root = Path(__file__).resolve().parent
    out_path = Path(args.report_out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    started_ts = time.time()
    result: dict[str, Any] = {
        "ok": False,
        "started_at": started_at,
        "base_url": args.base_url,
        "steps": [],
    }

    host, port = _parse_host_port(args.base_url)
    env = dict(os.environ)

    quick_cmd = [
        "powershell",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str((root / "system_quick_check.ps1").resolve()),
        "-ApiHost",
        host,
        "-Port",
        str(port),
        "-HistoryDbPath",
        str(Path(args.history_db).resolve()),
    ]
    if args.api_key:
        quick_cmd.extend(["-ApiKey", args.api_key])
    if args.admin_key:
        quick_cmd.extend(["-AdminKey", args.admin_key])
    if args.tenant_id:
        quick_cmd.extend(["-TenantId", args.tenant_id, "-TenantHeaderName", args.tenant_header])
    quick_step = _run_subprocess("quick_check", quick_cmd, cwd=root, env=env)
    result["steps"].append(quick_step)

    e2e_cmd = [sys.executable, str((root / "run_full_e2e_flow.py").resolve()), "--base-url", args.base_url]
    if args.api_key:
        e2e_cmd.extend(["--api-key", args.api_key])
    if args.admin_key:
        e2e_cmd.extend(["--admin-key", args.admin_key])
    if args.tenant_id:
        e2e_cmd.extend(["--tenant-id", args.tenant_id, "--tenant-header", args.tenant_header])
    if args.strict_alert_test:
        e2e_cmd.append("--strict-alert-test")
    e2e_step = _run_subprocess("full_e2e", e2e_cmd, cwd=root, env=env)
    result["steps"].append(e2e_step)

    probe_key = args.api_key or args.operator_key or args.admin_key or args.viewer_key
    auth_status, auth_body = _request(
        "GET",
        _url_with_query(args.base_url, "/v1/system/auth-info"),
        headers=_build_headers(probe_key, args.tenant_id, args.tenant_header),
    )
    auth_step = {
        "name": "auth_probe",
        "status": "passed" if auth_status == 200 else "failed",
        "http_status": auth_status,
        "body": auth_body,
    }
    result["steps"].append(auth_step)

    admin_probe_key = args.admin_key or probe_key
    dead_status, dead_body = _request(
        "GET",
        _url_with_query(args.base_url, "/v1/system/alert-dead-letter", {"limit": 20}),
        headers=_build_headers(admin_probe_key, args.tenant_id, args.tenant_header),
    )
    dead_step = {
        "name": "alert_dead_letter_probe",
        "status": "failed",
        "http_status": dead_status,
        "body": dead_body,
    }
    if dead_status == 200:
        dead_step["status"] = "passed"
    elif dead_status == 403 and not args.admin_key:
        dead_step["status"] = "skipped"
        dead_step["reason"] = "admin key required"
    result["steps"].append(dead_step)

    slo_status_code, slo_body = _request(
        "GET",
        _url_with_query(
            args.base_url,
            "/v1/system/slo",
            {
                "availability_target_pct": float(args.slo_availability_target),
                "latency_p95_target_ms": float(args.slo_p95_target_ms),
            },
        ),
        headers=_build_headers(probe_key, args.tenant_id, args.tenant_header),
    )
    slo_step = {
        "name": "slo_gate",
        "status": "failed",
        "http_status": slo_status_code,
        "body": slo_body,
        "require_slo_healthy": bool(args.require_slo_healthy),
    }
    if slo_status_code == 200 and isinstance(slo_body, dict):
        observed = str(slo_body.get("status", "unknown")).lower()
        if args.require_slo_healthy and observed != "healthy":
            slo_step["status"] = "failed"
            slo_step["reason"] = f"slo status is {observed}"
        else:
            slo_step["status"] = "passed"
            slo_step["observed_status"] = observed
    result["steps"].append(slo_step)

    brief_status, brief_body = _request(
        "GET",
        _url_with_query(
            args.base_url,
            "/v1/system/executive-brief",
            {"db_path": str(Path(args.history_db).resolve()), "window": 120},
        ),
        headers=_build_headers(probe_key, args.tenant_id, args.tenant_header),
    )
    brief_step = {
        "name": "executive_brief_probe",
        "status": "passed" if brief_status == 200 else "failed",
        "http_status": brief_status,
        "body": brief_body,
    }
    result["steps"].append(brief_step)

    brief_page_status, brief_page_body = _request(
        "GET",
        _url_with_query(
            args.base_url,
            "/v1/web/executive-brief",
            {"db_path": str(Path(args.history_db).resolve()), "window": 120},
        ),
        headers=_build_headers(probe_key, args.tenant_id, args.tenant_header),
    )
    brief_page_step = {
        "name": "executive_brief_page_probe",
        "status": "passed" if brief_page_status == 200 else "failed",
        "http_status": brief_page_status,
        "body_preview": str(brief_page_body)[:200],
    }
    result["steps"].append(brief_page_step)

    auth_active = bool(isinstance(auth_body, dict) and auth_body.get("auth_active"))
    tenant_enforced = bool(isinstance(auth_body, dict) and auth_body.get("tenant_enforced"))
    allowed_tenant_count = int(auth_body.get("allowed_tenant_count", 0)) if isinstance(auth_body, dict) else 0

    role_step: dict[str, Any]
    if args.skip_role_boundary:
        role_step = {"name": "role_boundary", "status": "skipped", "reason": "disabled by flag"}
    elif not auth_active:
        role_step = {"name": "role_boundary", "status": "skipped", "reason": "api key auth not active"}
    else:
        viewer_key = args.viewer_key or args.api_key
        operator_key = args.operator_key or args.api_key
        admin_key = args.admin_key
        if not viewer_key or not operator_key or not admin_key:
            role_step = {
                "name": "role_boundary",
                "status": "failed" if args.require_role_boundary else "skipped",
                "reason": "missing viewer/operator/admin keys for role boundary checks",
            }
        else:
            role_tenant = args.role_tenant or args.tenant_id or "tenant-a"
            role_step = {"name": "role_boundary"}
            role_step.update(
                _run_role_boundary(
                    base_url=args.base_url,
                    history_db=str(Path(args.history_db).resolve()),
                    tenant_header=args.tenant_header,
                    role_tenant=role_tenant,
                    wrong_tenant=args.wrong_tenant,
                    viewer_key=viewer_key,
                    operator_key=operator_key,
                    admin_key=admin_key,
                    tenant_enforced=tenant_enforced,
                    allowed_tenant_count=allowed_tenant_count,
                )
            )
    result["steps"].append(role_step)

    failed_steps = [step for step in result["steps"] if step.get("status") == "failed"]
    result["ok"] = len(failed_steps) == 0
    result["ended_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    result["elapsed_sec"] = round(time.time() - started_ts, 3)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"release gate report: {out_path}")
    print(f"overall ok: {result['ok']}")
    for step in result["steps"]:
        name = step.get("name", "unknown")
        status = step.get("status", "unknown")
        print(f"- {name}: {status}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
