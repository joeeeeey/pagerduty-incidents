#!/usr/bin/env python3
"""PagerDuty REST and Events API CLI with explicit mutation gates."""

from __future__ import annotations

from safety import SafeError, secret, scrub, api_url, request
import argparse
import json
import os
import pathlib
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


REST_API_HOST = "api.pagerduty.com"
EVENTS_API_URL = "https://events.pagerduty.com/v2/enqueue"
USER_AGENT = "pagerduty-ops/1.0"


def _eprint(*args: object) -> None:
    print(*args, file=sys.stderr)


# ---------- secrets ----------


def _resolve_api_key():
    return secret("PAGERDUTY_API_KEY", "PAGERDUTY_API_KEY_FILE")


def _resolve_routing_key():
    return secret("PAGERDUTY_EVENTS_ROUTING_KEY", "PAGERDUTY_EVENTS_ROUTING_KEY_FILE")


def _rest_get(path, params=None, *, timeout_s=30):
    status, data = request(
        api_url("https://" + REST_API_HOST, path, params),
        headers={
            "Authorization": "Token token=" + _resolve_api_key(),
            "Accept": "application/vnd.pagerduty+json;version=2",
        },
        timeout=timeout_s,
    )
    return status, json.dumps(data)


def _events_post(payload, *, timeout_s=15):
    status, data = request(
        EVENTS_API_URL, method="POST", body=payload, timeout=timeout_s
    )
    return status, json.dumps(data)


def _print_response(status: int, body: str, *, raw: bool) -> None:
    if raw:
        print(body)
        return
    try:
        data: Any = json.loads(body)
        print(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))
    except Exception:
        if body.strip():
            print(body)
        else:
            _eprint(f"(empty body, status={status})")


def _parse_kv_pairs(pairs: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for pair in pairs or []:
        if "=" not in pair:
            raise ValueError(f"--param must be key=value, got: {pair}")
        key, value = pair.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"--param key cannot be empty: {pair}")
        out[key] = value.strip()
    return out


# ---------- read commands ----------


def _cmd_validate(args: argparse.Namespace) -> int:
    status, body = _rest_get("/users/me")
    if status == 200:
        try:
            data = json.loads(body)
            user = data.get("user", {})
            print(
                json.dumps(
                    {
                        "valid": True,
                        "user": {
                            "id": user.get("id"),
                            "name": user.get("name"),
                            "email": user.get("email"),
                            "role": user.get("role"),
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        except Exception:
            pass
    _eprint(f"HTTP {status}")
    _print_response(status, body, raw=args.raw)
    return 1 if status >= 400 else 0


def _cmd_get(args: argparse.Namespace) -> int:
    params = _parse_kv_pairs(args.param)
    status, body = _rest_get(args.path, params=params or None)
    if status >= 400:
        _eprint(f"HTTP {status}")
    _print_response(status, body, raw=args.raw)
    return 0 if status < 400 else 1


def _cmd_services_list(args: argparse.Namespace) -> int:
    params: dict[str, Any] = {"limit": args.limit}
    if args.query:
        params["query"] = args.query
    extra = _parse_kv_pairs(args.param)
    params.update(extra)
    status, body = _rest_get("/services", params=params)
    if args.summary and status == 200:
        try:
            data = json.loads(body)
            for s in data.get("services", []):
                integrations = (
                    ", ".join(
                        f"{i.get('summary', '?')} ({i.get('type', '?')})"
                        for i in s.get("integrations", [])
                    )
                    or "-"
                )
                print(
                    f"{s['id']} | {s.get('status', '?'):10} | {s['name']} | integrations: {integrations}"
                )
            return 0
        except Exception:
            pass
    if status >= 400:
        _eprint(f"HTTP {status}")
    _print_response(status, body, raw=args.raw)
    return 0 if status < 400 else 1


def _cmd_services_get(args: argparse.Namespace) -> int:
    status, body = _rest_get(f"/services/{args.service_id}")
    if status >= 400:
        _eprint(f"HTTP {status}")
    _print_response(status, body, raw=args.raw)
    return 0 if status < 400 else 1


def _cmd_incidents_list(args: argparse.Namespace) -> int:
    params: dict[str, Any] = {"limit": args.limit, "sort_by": "created_at:desc"}
    if args.service_id:
        params["service_ids[]"] = args.service_id
    if args.statuses:
        # comma separated
        for s in args.statuses.split(","):
            s = s.strip()
            if s:
                params.setdefault("statuses[]", [])
                if isinstance(params["statuses[]"], list):
                    params["statuses[]"].append(s)
                else:
                    params["statuses[]"] = [params["statuses[]"], s]
    if args.since:
        params["since"] = args.since
    if args.until:
        params["until"] = args.until
    extra = _parse_kv_pairs(args.param)
    params.update(extra)
    status, body = _rest_get("/incidents", params=params)
    if args.summary and status == 200:
        try:
            data = json.loads(body)
            for i in data.get("incidents", []):
                assignees = (
                    ", ".join(
                        a.get("assignee", {}).get("summary", "?")
                        for a in i.get("assignments", [])
                    )
                    or "-"
                )
                print(
                    f"{i['id']} | {i.get('status', '?'):12} | {i.get('urgency', '?'):5} | {i.get('created_at', '')[:19]} | {i.get('title', '')[:70]} | {assignees}"
                )
            return 0
        except Exception:
            pass
    if status >= 400:
        _eprint(f"HTTP {status}")
    _print_response(status, body, raw=args.raw)
    return 0 if status < 400 else 1


def _cmd_incidents_get(args: argparse.Namespace) -> int:
    status, body = _rest_get(f"/incidents/{args.incident_id}")
    if status >= 400:
        _eprint(f"HTTP {status}")
    _print_response(status, body, raw=args.raw)
    return 0 if status < 400 else 1


def _cmd_incidents_alerts(args: argparse.Namespace) -> int:
    """Fetch alerts for an incident. The `alert_key` field = the dedup_key that
    Events API v2 used when triggering the incident. This is the canonical way to
    discover what dedup_key to resolve a given incident by."""
    status, body = _rest_get(f"/incidents/{args.incident_id}/alerts")
    if args.summary and status == 200:
        try:
            data = json.loads(body)
            for a in data.get("alerts", []):
                print(
                    f"  alert_id={a['id']} alert_key={a.get('alert_key')} status={a.get('status', '?')}"
                )
            if not data.get("alerts"):
                _eprint(
                    "(no alerts on this incident — it may have been created directly, not via Events API)"
                )
            return 0
        except Exception:
            pass
    if status >= 400:
        _eprint(f"HTTP {status}")
    _print_response(status, body, raw=args.raw)
    return 0 if status < 400 else 1


# ---------- write commands: Events API v2 ----------


def _build_events_payload(
    action: str,
    *,
    routing_key: str,
    dedup_key: str,
    summary: str | None = None,
    severity: str | None = None,
    source: str | None = None,
    custom_details: dict | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "routing_key": routing_key,
        "event_action": action,
        "dedup_key": dedup_key,
    }
    if action == "trigger":
        if not summary or not severity or not source:
            raise ValueError("trigger events require --summary, --severity, --source")
        inner: dict[str, Any] = {
            "summary": summary,
            "severity": severity,
            "source": source,
        }
        if custom_details:
            inner["custom_details"] = custom_details
        payload["payload"] = inner
    return payload


def _redact_payload_for_preview(payload):
    return scrub(payload)


def _events_dispatch(action: str, args: argparse.Namespace) -> int:
    try:
        routing_key = _resolve_routing_key() if args.execute else "[REDACTED]"
    except (SafeError, ValueError, OSError) as e:
        _eprint(str(e))
        return 2
    custom_details: dict | None = None
    if getattr(args, "custom_details", None):
        try:
            custom_details = json.loads(args.custom_details)
        except Exception as e:
            _eprint(f"--custom-details is not valid JSON: {e}")
            return 2
    try:
        payload = _build_events_payload(
            action,
            routing_key=routing_key,
            dedup_key=args.dedup_key,
            summary=getattr(args, "summary", None),
            severity=getattr(args, "severity", None),
            source=getattr(args, "source", None),
            custom_details=custom_details,
        )
    except ValueError as e:
        _eprint(str(e))
        return 2

    print(
        f"=== Events API v2 {action} (dry-run)"
        + ("" if args.execute else "; re-run with --execute to send")
        + " ==="
    )
    print(
        json.dumps(_redact_payload_for_preview(payload), ensure_ascii=False, indent=2)
    )

    if not args.execute:
        return 0

    status, body = _events_post(payload)
    print(f"--- response ---")
    print(f"HTTP {status}")
    _print_response(status, body, raw=False)
    return 0 if status == 202 else 1


def _cmd_events_resolve(args: argparse.Namespace) -> int:
    return _events_dispatch("resolve", args)


def _cmd_events_trigger(args: argparse.Namespace) -> int:
    return _events_dispatch("trigger", args)


def _cmd_events_acknowledge(args: argparse.Namespace) -> int:
    return _events_dispatch("acknowledge", args)


def _cmd_events_batch_resolve(args: argparse.Namespace) -> int:
    """Batch-resolve: one dedup_key per line (# = comment, blank line = skip)."""
    try:
        routing_key = _resolve_routing_key() if args.execute else "[REDACTED]"
    except (SafeError, ValueError, OSError) as e:
        _eprint(str(e))
        return 2

    path = pathlib.Path(args.file)
    if not path.exists():
        _eprint(f"file not found: {args.file}")
        return 2
    keys: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        keys.append(s) if s not in keys else None

    if not keys or len(keys) > 100:
        raise SafeError("Batch must contain 1 to 100 unique dedup keys")

    print(
        f"=== batch-resolve: {len(keys)} dedup_keys"
        + ("" if args.execute else "; re-run with --execute --confirm to send")
        + " ==="
    )
    for k in keys:
        print(f"  dedup_key: {k}")

    if not args.execute:
        return 0
    if not args.confirm:
        _eprint("refusing to batch-resolve without --confirm in addition to --execute")
        return 2

    rc_all = 0
    for k in keys:
        payload = _build_events_payload("resolve", routing_key=routing_key, dedup_key=k)
        status, body = _events_post(payload)
        print(f"  {k}  HTTP {status}")
        if status != 202:
            rc_all = 1
            break
    return rc_all


# ---------- write command: REST incidents update (alternative path) ----------


def _cmd_incidents_update(args: argparse.Namespace) -> int:
    """Update incident(s) via REST API (alternative to Events API resolve).
    Requires From header with an email of a PagerDuty user; pass via --from."""
    body_obj: dict[str, Any] = {
        "incident": {
            "type": "incident_reference",
            "status": args.status,
        }
    }
    if args.resolution:
        body_obj["incident"]["resolution"] = args.resolution

    print(
        f"=== PUT /incidents/{args.incident_id} (dry-run)"
        + ("" if args.execute else "; re-run with --execute to send")
        + " ==="
    )
    print(json.dumps(scrub(body_obj), ensure_ascii=False, indent=2))

    if not args.execute:
        return 0

    api_key = _resolve_api_key()
    from_email = args.from_email or os.environ.get("PD_FROM_EMAIL", "").strip()
    if not from_email:
        _eprint("REST incident update requires --from EMAIL (or PD_FROM_EMAIL env)")
        return 2
    status, data = request(
        api_url("https://" + REST_API_HOST, "/incidents/" + args.incident_id),
        method="PUT",
        body=body_obj,
        headers={
            "Authorization": "Token token=" + api_key,
            "From": from_email,
            "Accept": "application/vnd.pagerduty+json;version=2",
        },
    )
    body = json.dumps(data)

    print(f"HTTP {status}")
    _print_response(status, body, raw=False)
    return 0 if status < 400 else 1


# ---------- parser ----------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pd_api.py",
        description="PagerDuty REST + Events API direct CLI (read + write, dry-run by default)",
    )
    p.add_argument(
        "--raw", action="store_true", help="print raw response (skip JSON pretty-print)"
    )

    sp = p.add_subparsers(dest="cmd", required=True)

    # validate
    sp_validate = sp.add_parser("validate", help="verify API key via GET /users/me")
    sp_validate.set_defaults(func=_cmd_validate)

    # generic GET escape hatch
    sp_get = sp.add_parser("get", help="raw GET on any REST path, e.g. 'get /teams'")
    sp_get.add_argument("path", help="API path, must start with '/'")
    sp_get.add_argument(
        "--param", action="append", help="query param key=value, repeatable"
    )
    sp_get.set_defaults(func=_cmd_get)

    # services
    sp_services = sp.add_parser("services", help="PagerDuty services (read)")
    sp_services_sub = sp_services.add_subparsers(dest="sub", required=True)
    sp_s_list = sp_services_sub.add_parser("list", help="list services")
    sp_s_list.add_argument("--query", help="filter by name/query string")
    sp_s_list.add_argument("--limit", type=int, default=25)
    sp_s_list.add_argument(
        "--param", action="append", help="extra query param key=value"
    )
    sp_s_list.add_argument(
        "--summary", action="store_true", help="compact one-line-per-service output"
    )
    sp_s_list.set_defaults(func=_cmd_services_list)
    sp_s_get = sp_services_sub.add_parser("get", help="get a specific service")
    sp_s_get.add_argument("service_id")
    sp_s_get.set_defaults(func=_cmd_services_get)

    # incidents
    sp_incidents = sp.add_parser(
        "incidents", help="PagerDuty incidents (read + update)"
    )
    sp_incidents_sub = sp_incidents.add_subparsers(dest="sub", required=True)

    sp_i_list = sp_incidents_sub.add_parser("list", help="list incidents")
    sp_i_list.add_argument(
        "--service-id", help="filter by service id (provider service ID)"
    )
    sp_i_list.add_argument(
        "--statuses",
        help="comma-separated, e.g. triggered,acknowledged,resolved (default: open only)",
        default="triggered,acknowledged",
    )
    sp_i_list.add_argument("--since", help="ISO8601 start time (optional)")
    sp_i_list.add_argument("--until", help="ISO8601 end time (optional)")
    sp_i_list.add_argument("--limit", type=int, default=25)
    sp_i_list.add_argument(
        "--param", action="append", help="extra query param key=value"
    )
    sp_i_list.add_argument(
        "--summary", action="store_true", help="compact one-line-per-incident output"
    )
    sp_i_list.set_defaults(func=_cmd_incidents_list)

    sp_i_get = sp_incidents_sub.add_parser("get", help="get one incident")
    sp_i_get.add_argument("incident_id")
    sp_i_get.set_defaults(func=_cmd_incidents_get)

    sp_i_alerts = sp_incidents_sub.add_parser(
        "alerts",
        help="list alerts on an incident; alert_key == Events v2 dedup_key",
    )
    sp_i_alerts.add_argument("incident_id")
    sp_i_alerts.add_argument(
        "--summary",
        action="store_true",
        default=True,
        help="one-line output (default on)",
    )
    sp_i_alerts.set_defaults(func=_cmd_incidents_alerts)

    sp_i_update = sp_incidents_sub.add_parser(
        "update",
        help="REST PUT /incidents/{id} (alternative to Events v2 resolve). Dry-run unless --execute.",
    )
    sp_i_update.add_argument("incident_id")
    sp_i_update.add_argument(
        "--status", choices=["acknowledged", "resolved"], required=True
    )
    sp_i_update.add_argument(
        "--resolution", help="resolution text (status=resolved only)"
    )
    sp_i_update.add_argument(
        "--from",
        dest="from_email",
        help="PagerDuty user email for 'From' header (or PD_FROM_EMAIL env)",
    )
    sp_i_update.add_argument(
        "--execute",
        action="store_true",
        help="actually send; without this flag it is a dry-run",
    )
    sp_i_update.set_defaults(func=_cmd_incidents_update)

    # events api v2 (write)
    sp_events = sp.add_parser(
        "events", help="PagerDuty Events API v2 (write). Dry-run unless --execute."
    )
    sp_events_sub = sp_events.add_subparsers(dest="sub", required=True)

    def _common_events_args(
        ap: argparse.ArgumentParser, *, want_full_payload: bool
    ) -> None:

        ap.add_argument(
            "--dedup-key",
            required=True,
            help="unique key to de-duplicate / correlate trigger+resolve",
        )
        if want_full_payload:
            ap.add_argument("--summary", help="short summary (trigger only)")
            ap.add_argument(
                "--severity",
                choices=["critical", "error", "warning", "info"],
                help="severity (trigger only)",
            )
            ap.add_argument("--source", help="source hostname/service (trigger only)")
            ap.add_argument(
                "--custom-details",
                help="JSON blob for payload.custom_details (trigger only)",
            )
        ap.add_argument(
            "--execute",
            action="store_true",
            help="actually send; without this flag it is a dry-run",
        )

    sp_e_resolve = sp_events_sub.add_parser(
        "resolve", help="send event_action=resolve for a dedup_key"
    )
    _common_events_args(sp_e_resolve, want_full_payload=False)
    sp_e_resolve.set_defaults(func=_cmd_events_resolve)

    sp_e_trigger = sp_events_sub.add_parser(
        "trigger", help="send event_action=trigger (requires summary/severity/source)"
    )
    _common_events_args(sp_e_trigger, want_full_payload=True)
    sp_e_trigger.set_defaults(func=_cmd_events_trigger)

    sp_e_ack = sp_events_sub.add_parser(
        "acknowledge", help="send event_action=acknowledge for a dedup_key"
    )
    _common_events_args(sp_e_ack, want_full_payload=False)
    sp_e_ack.set_defaults(func=_cmd_events_acknowledge)

    sp_e_batch = sp_events_sub.add_parser(
        "batch-resolve",
        help="batch resolve from a file of dedup_keys (one per line; # = comment). Requires --execute AND --confirm.",
    )

    sp_e_batch.add_argument(
        "--file", required=True, help="path to file with one dedup_key per line"
    )
    sp_e_batch.add_argument("--execute", action="store_true", help="actually send")
    sp_e_batch.add_argument(
        "--confirm",
        action="store_true",
        help="extra guard on top of --execute for batch ops",
    )
    sp_e_batch.set_defaults(func=_cmd_events_batch_resolve)

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.func(args))
    except (SafeError, ValueError, OSError) as e:
        _eprint(str(e))
        return 2
    except KeyboardInterrupt:
        _eprint("interrupted")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
