#!/usr/bin/env python3
"""syncToken delta spike — THROWAWAY. Do not merge.

Answers one question: does resending Apple's `syncToken` on a CloudKit
`records/query` yield a true delta (only changed records), a cache-validity
signal, or nothing at all?

Secondary probes in the same session:
  * does `continuationMarker` work as a paging cursor in place of `startRank`?
  * how cheap/responsive is the `HyperionIndexCountLookup` count probe as a
    change detector?

Output discipline: every raw request/response goes to files under
--artifacts. Nothing that could carry a credential is printed to stdout —
the console only ever gets structural summaries (counts, lengths, booleans).

Usage
-----
  # 1. authenticate once (interactive 2FA), persists a session cookie
  python spike/synctoken_spike.py auth

  # 2. baseline + resend + continuationMarker + count probe
  python spike/synctoken_spike.py probe

  # 3. now add or delete ONE photo via iCloud.com, then:
  python spike/synctoken_spike.py delta

Env:
  ICLOUD_USERNAME   apple id           (required)
  ICLOUD_PASSWORD   password           (optional; prompted if absent)
  ICLOUD_COOKIE_DIR session dir        (default: ./spike/.state/cookies)
"""

from __future__ import annotations

import argparse
import getpass
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib.parse import urlencode

_REPO_SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(_REPO_SRC))

from icloudpd.authentication import request_2fa  # noqa: E402
from pyicloud_ipd.base import PyiCloudService  # noqa: E402

SPIKE_DIR = Path(__file__).resolve().parent
STATE_DIR = SPIKE_DIR / ".state"
DEFAULT_COOKIE_DIR = STATE_DIR / "cookies"
STATE_FILE = STATE_DIR / "spike-state.json"

logger = logging.getLogger("synctoken-spike")


# --------------------------------------------------------------------------
# redaction helpers — the console must never carry anything credential-shaped
# --------------------------------------------------------------------------

_SENSITIVE_PARAM_KEYS = {"dsid", "clientId", "clientInstanceId", "syncToken"}


def fingerprint(value: Any) -> str:
    """A safe, comparable stand-in for an opaque token."""
    if value is None:
        return "<absent>"
    s = str(value)
    return f"<len={len(s)} head={s[:6]!r} tail={s[-4:]!r}>"


def redact_params(params: Dict[str, Any]) -> Dict[str, Any]:
    return {
        k: (fingerprint(v) if k in _SENSITIVE_PARAM_KEYS else v) for k, v in params.items()
    }


# --------------------------------------------------------------------------
# auth
# --------------------------------------------------------------------------


def build_service() -> PyiCloudService:
    username = os.environ.get("ICLOUD_USERNAME")
    if not username:
        raise SystemExit("ICLOUD_USERNAME is not set")

    cookie_dir = os.environ.get("ICLOUD_COOKIE_DIR") or str(DEFAULT_COOKIE_DIR)
    Path(cookie_dir).mkdir(parents=True, exist_ok=True)

    captured: List[str] = []

    def password_provider() -> str | None:
        pw = os.environ.get("ICLOUD_PASSWORD")
        if not pw:
            pw = getpass.getpass(f"iCloud password for {username}: ")
        captured.append(pw)
        return pw

    svc = PyiCloudService(
        "com",
        username,
        password_provider,
        cookie_directory=cookie_dir,
    )

    if svc.requires_2fa:
        request_2fa(svc, logger)
    elif svc.requires_2sa:
        raise SystemExit("account needs 2SA; spike only handles 2FA")

    del captured[:]
    return svc


# --------------------------------------------------------------------------
# raw query plumbing
# --------------------------------------------------------------------------


def post_query(
    svc: PyiCloudService,
    endpoint: str,
    params: Dict[str, Any],
    body: Dict[str, Any],
) -> Tuple[int, Dict[str, Any]]:
    url = f"{endpoint}/records/query?{urlencode(params)}"
    resp = svc.session.post(url, data=json.dumps(body), headers={"Content-type": "text/plain"})
    try:
        return resp.status_code, resp.json()
    except ValueError:
        return resp.status_code, {"_non_json_body_len": len(resp.content)}


def post_batch(
    svc: PyiCloudService,
    endpoint: str,
    params: Dict[str, Any],
    body: Dict[str, Any],
) -> Tuple[int, Dict[str, Any]]:
    url = f"{endpoint}/internal/records/query/batch?{urlencode(params)}"
    resp = svc.session.post(url, data=json.dumps(body), headers={"Content-type": "text/plain"})
    try:
        return resp.status_code, resp.json()
    except ValueError:
        return resp.status_code, {"_non_json_body_len": len(resp.content)}


def summarize(response: Dict[str, Any]) -> Dict[str, Any]:
    """Structural view of a records/query response. No field values."""
    records = response.get("records") or []
    by_type: Dict[str, int] = {}
    names: List[str] = []
    deleted_flags = 0
    for rec in records:
        rt = rec.get("recordType", "<none>")
        by_type[rt] = by_type.get(rt, 0) + 1
        rn = rec.get("recordName")
        if rn:
            names.append(rn)
        # CloudKit reports tombstones either as a deleted recordType or an
        # explicit flag; count both shapes so we can tell removals apart.
        if rec.get("deleted") is True or "Delete" in rt:
            deleted_flags += 1

    return {
        "http_record_count": len(records),
        "records_by_type": by_type,
        "record_names": names,
        "tombstone_like_count": deleted_flags,
        "has_syncToken": "syncToken" in response,
        "syncToken_fp": fingerprint(response.get("syncToken")),
        "has_continuationMarker": "continuationMarker" in response,
        "continuationMarker_fp": fingerprint(response.get("continuationMarker")),
        "top_level_keys": sorted(response.keys()),
    }


def dump(artifacts: Path, name: str, payload: Any) -> None:
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / f"{name}.json").write_text(json.dumps(payload, indent=2, sort_keys=True))


def load_state() -> Dict[str, Any]:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_state(state: Dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True))
    STATE_FILE.chmod(0o600)


# --------------------------------------------------------------------------
# probes
# --------------------------------------------------------------------------


def get_album(svc: PyiCloudService) -> Any:
    return svc.photos.all


def list_body(album: Any, offset: int, page_size: int, direction: str) -> Dict[str, Any]:
    """A listing query with an overridable sort direction.

    `_list_query_gen` hardcodes ASCENDING. Against a 4.5k-asset library that
    puts the newest photo on the *last* page, so a first-page window would be
    blind to the very mutation this spike introduces. DESCENDING puts the
    mutation in page one, which is the only way the delta comparison means
    anything.
    """
    body = album._list_query_gen(offset, album.list_type, album.query_filter)
    body["resultsLimit"] = page_size
    for clause in body["query"]["filterBy"]:
        if clause.get("fieldName") == "direction":
            clause["fieldValue"]["value"] = direction
    return body


def variant_params(
    base: Dict[str, Any], sync_token: str | None, swap_client_id: bool
) -> Dict[str, Any]:
    p = dict(base)
    if sync_token is not None:
        p["syncToken"] = sync_token
    if swap_client_id and "clientId" in p:
        p["clientInstanceId"] = p.pop("clientId")
    return p


def cmd_auth(args: argparse.Namespace) -> int:
    build_service()
    print("auth OK — session persisted")
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    artifacts = Path(args.artifacts)
    svc = build_service()
    album = get_album(svc)
    endpoint = album.service_endpoint
    base_params = dict(album.params)
    page_size = args.page_size

    body = list_body(album, 0, page_size, args.direction)

    results: Dict[str, Any] = {
        "page_size": page_size,
        "direction": args.direction,
        "base_params": redact_params(base_params),
    }

    # --- 1. baseline -------------------------------------------------------
    t0 = time.monotonic()
    status, baseline = post_query(svc, endpoint, base_params, body)
    baseline_ms = int((time.monotonic() - t0) * 1000)
    dump(artifacts, "01-baseline-response", baseline)
    results["baseline"] = {"status": status, "elapsed_ms": baseline_ms, **summarize(baseline)}

    sync_token = baseline.get("syncToken")
    if sync_token is None:
        print("!! baseline response carried NO syncToken — the premise is wrong")

    # --- 2. resend, three variants ----------------------------------------
    # Isolating the clientId->clientInstanceId swap matters: the dead code at
    # photos.py:415-419 does both at once, so a null result from the combined
    # form would not tell us which half Apple rejected.
    variants = [
        ("02-resend-token-only", variant_params(base_params, sync_token, False)),
        ("03-resend-token-and-clientinstanceid", variant_params(base_params, sync_token, True)),
        ("04-clientinstanceid-only", variant_params(base_params, None, True)),
    ]
    results["resend"] = {}
    for name, params in variants:
        if sync_token is None and "token" in name:
            results["resend"][name] = {"skipped": "no baseline syncToken"}
            continue
        t0 = time.monotonic()
        status, resp = post_query(svc, endpoint, params, body)
        ms = int((time.monotonic() - t0) * 1000)
        dump(artifacts, f"{name}-response", resp)
        entry: Dict[str, Any] = {
            "status": status,
            "elapsed_ms": ms,
            "params": redact_params(params),
            **summarize(resp),
        }
        entry["identical_to_baseline"] = (
            entry["record_names"] == results["baseline"]["record_names"]
        )
        entry["token_changed"] = resp.get("syncToken") != sync_token
        results["resend"][name] = entry

    # --- 3. continuationMarker paging -------------------------------------
    marker = baseline.get("continuationMarker")
    if marker is None:
        results["continuation"] = {"skipped": "baseline carried no continuationMarker"}
    else:
        cont_body = dict(body)
        cont_body["continuationMarker"] = marker
        status, resp = post_query(svc, endpoint, base_params, cont_body)
        dump(artifacts, "05-continuation-response", resp)
        cont = {"status": status, **summarize(resp)}
        # A working cursor returns the NEXT page: disjoint from page 1, and the
        # same set startRank=page_size would have returned.
        cont["overlaps_page_one"] = bool(
            set(cont["record_names"]) & set(results["baseline"]["record_names"])
        )
        rank_body = list_body(album, page_size, page_size, args.direction)
        _, rank_resp = post_query(svc, endpoint, base_params, rank_body)
        dump(artifacts, "06-startrank-page-two-response", rank_resp)
        cont["matches_startrank_page_two"] = (
            cont["record_names"] == summarize(rank_resp)["record_names"]
        )
        results["continuation"] = cont

    # --- 4. count probe ----------------------------------------------------
    count_body = album._count_query_gen(album.obj_type)
    timings = []
    item_count = None
    for _ in range(args.count_samples):
        t0 = time.monotonic()
        status, resp = post_batch(svc, endpoint, base_params, count_body)
        timings.append(int((time.monotonic() - t0) * 1000))
        try:
            item_count = int(resp["batch"][0]["records"][0]["fields"]["itemCount"]["value"])
        except (KeyError, IndexError, TypeError, ValueError):
            item_count = None
    dump(artifacts, "07-count-probe-response", resp)
    results["count_probe"] = {
        "status": status,
        "item_count": item_count,
        "elapsed_ms_samples": timings,
    }

    dump(artifacts, "00-probe-summary", results)

    state = load_state()
    state["sync_token"] = sync_token
    state["baseline_record_names"] = results["baseline"]["record_names"]
    state["baseline_item_count"] = item_count
    state["page_size"] = page_size
    state["direction"] = args.direction
    save_state(state)

    print(json.dumps(results, indent=2, sort_keys=True))
    print(f"\nartifacts -> {artifacts}")
    print("Now mutate the library (add or delete ONE photo), then run: delta")
    return 0


def cmd_delta(args: argparse.Namespace) -> int:
    artifacts = Path(args.artifacts)
    state = load_state()
    sync_token = state.get("sync_token")
    if not sync_token:
        raise SystemExit("no stored syncToken; run `probe` first")

    svc = build_service()
    album = get_album(svc)
    endpoint = album.service_endpoint
    base_params = dict(album.params)
    page_size = state.get("page_size", args.page_size)
    direction = state.get("direction", args.direction)

    body = list_body(album, 0, page_size, direction)

    results: Dict[str, Any] = {
        "stored_token_fp": fingerprint(sync_token),
        "direction": direction,
    }

    for name, params in [
        ("10-post-mutation-token-only", variant_params(base_params, sync_token, False)),
        ("11-post-mutation-token-and-clientinstanceid", variant_params(base_params, sync_token, True)),
        ("12-post-mutation-no-token", dict(base_params)),
    ]:
        status, resp = post_query(svc, endpoint, params, body)
        dump(artifacts, f"{name}-response", resp)
        entry = {"status": status, "params": redact_params(params), **summarize(resp)}
        entry["identical_to_baseline"] = entry["record_names"] == state["baseline_record_names"]
        entry["new_names_vs_baseline"] = sorted(
            set(entry["record_names"]) - set(state["baseline_record_names"])
        )
        entry["missing_names_vs_baseline"] = sorted(
            set(state["baseline_record_names"]) - set(entry["record_names"])
        )
        results[name] = entry

    # Did the cheap count probe notice the mutation? This is the fallback
    # change-detector the spec calls out if the delta is a bust.
    count_body = album._count_query_gen(album.obj_type)
    status, resp = post_batch(svc, endpoint, base_params, count_body)
    dump(artifacts, "13-post-mutation-count", resp)
    try:
        item_count = int(resp["batch"][0]["records"][0]["fields"]["itemCount"]["value"])
    except (KeyError, IndexError, TypeError, ValueError):
        item_count = None
    results["count_probe"] = {
        "before": state.get("baseline_item_count"),
        "after": item_count,
        "detected_change": item_count != state.get("baseline_item_count"),
    }

    # Deletions live in their own list_type; if the main delta is silent about
    # removals, this tells us whether removals are observable at all.
    deleted_album = svc.photos.recently_deleted
    del_body = list_body(deleted_album, 0, page_size, direction)
    status, resp = post_query(svc, endpoint, dict(deleted_album.params), del_body)
    dump(artifacts, "14-recently-deleted", resp)
    results["recently_deleted"] = {"status": status, **summarize(resp)}

    dump(artifacts, "09-delta-summary", results)
    print(json.dumps(results, indent=2, sort_keys=True))
    print(f"\nartifacts -> {artifacts}")
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", default=str(STATE_DIR / "artifacts"))
    parser.add_argument("--page-size", type=int, default=20)
    parser.add_argument("--count-samples", type=int, default=3)
    parser.add_argument("--direction", choices=["ASCENDING", "DESCENDING"], default="DESCENDING")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("auth")
    sub.add_parser("probe")
    sub.add_parser("delta")

    args = parser.parse_args()
    return {"auth": cmd_auth, "probe": cmd_probe, "delta": cmd_delta}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
