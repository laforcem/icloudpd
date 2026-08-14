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
import hashlib
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


def token_hash(value: Any) -> str:
    """Full-value equality check for an opaque token, safe to print.

    `fingerprint` only exposes the first 6 and last 4 characters, which is
    useless for deciding whether a 44-char base64 syncToken advanced — the
    change would sit in the middle. A truncated SHA-256 compares the whole
    value while revealing none of it.
    """
    if value is None:
        return "<absent>"
    return hashlib.sha256(str(value).encode()).hexdigest()[:12]


def redact_params(params: Dict[str, Any]) -> Dict[str, Any]:
    return {
        k: (fingerprint(v) if k in _SENSITIVE_PARAM_KEYS else v) for k, v in params.items()
    }


# --------------------------------------------------------------------------
# auth
# --------------------------------------------------------------------------


ENV_FILE = STATE_DIR / "env"


def resolve_username() -> str:
    """Apple ID from the environment, falling back to a gitignored env file.

    The persisted session cannot supply this: it stores no Apple ID, and the
    session filename is produced by sanitize_apple_id(), which strips '@' and
    '.' and so cannot be reversed. The env file exists so an already-authed
    run needs no interactive step and no credential in shell history.
    """
    username = os.environ.get("ICLOUD_USERNAME")
    if username:
        return username

    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip().removeprefix("export ").strip()
            if line.startswith("ICLOUD_USERNAME="):
                return line.partition("=")[2].strip().strip("'\"")

    raise SystemExit(
        f"ICLOUD_USERNAME is not set. Either export it, or write it to {ENV_FILE} as:\n"
        "  ICLOUD_USERNAME=you@example.com"
    )


def build_service() -> PyiCloudService:
    username = resolve_username()

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
        "syncToken_sha12": token_hash(response.get("syncToken")),
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

    # --- 5. full-sweep control --------------------------------------------
    # The paged window above CANNOT prove a mutation is visible. The list type
    # sorts by asset date (capture time), not added date, so an uploaded photo
    # with old EXIF lands mid-list and never enters page one. Without this
    # control, "no new record after mutation" is ambiguous between "the token
    # filtered it out" and "the window never covered it in the first place".
    full_body = list_body(album, 0, args.full_limit, args.direction)
    status, full_resp = post_query(svc, endpoint, base_params, full_body)
    dump(artifacts, "08-full-sweep", full_resp)
    results["full_sweep"] = {"status": status, **summarize(full_resp)}

    dump(artifacts, "00-probe-summary", results)

    state = load_state()
    state["sync_token"] = sync_token
    state["baseline_token_sha12"] = token_hash(sync_token)
    state["baseline_record_names"] = results["baseline"]["record_names"]
    state["baseline_full_names"] = results["full_sweep"]["record_names"]
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

    # THE CONTROL. Everything above is uninterpretable without this: it proves
    # whether the mutation is visible to an unfiltered query at all. If this
    # shows no change either, the experiment says nothing about syncToken.
    full_body = list_body(album, 0, args.full_limit, direction)
    status, full_resp = post_query(svc, endpoint, base_params, full_body)
    dump(artifacts, "15-post-mutation-full-sweep", full_resp)
    full = {"status": status, **summarize(full_resp)}
    baseline_full = state.get("baseline_full_names", [])
    full["new_names_vs_baseline"] = sorted(set(full["record_names"]) - set(baseline_full))
    full["missing_names_vs_baseline"] = sorted(set(baseline_full) - set(full["record_names"]))
    full["mutation_is_visible"] = bool(
        full["new_names_vs_baseline"] or full["missing_names_vs_baseline"]
    )
    results["full_sweep_control"] = full

    # Does the token advance when the zone changes? If it does, it is usable
    # as a cheap change detector even though it is not a change log.
    results["token_advance"] = {
        "baseline_sha12": state.get("baseline_token_sha12"),
        "after_mutation_sha12": token_hash(full_resp.get("syncToken")),
        "token_advanced": token_hash(full_resp.get("syncToken"))
        != state.get("baseline_token_sha12"),
    }

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


DEFAULTS: Dict[str, Any] = {
    "artifacts": str(STATE_DIR / "artifacts"),
    "page_size": 20,
    "count_samples": 3,
    "direction": "DESCENDING",
    "full_limit": 1000,
}


def add_common_args(parser: argparse.ArgumentParser) -> None:
    """Options accepted on either side of the subcommand.

    default=SUPPRESS is load-bearing: the same options are registered on the
    top-level parser and on every subparser, and a subparser with a real
    default would overwrite a value already parsed from before the
    subcommand. Suppressed options simply stay unset, so the real defaults
    get filled in once, after parsing.
    """
    parser.add_argument("--artifacts", default=argparse.SUPPRESS)
    parser.add_argument("--page-size", type=int, default=argparse.SUPPRESS)
    parser.add_argument("--count-samples", type=int, default=argparse.SUPPRESS)
    parser.add_argument("--full-limit", type=int, default=argparse.SUPPRESS)
    parser.add_argument(
        "--direction", choices=["ASCENDING", "DESCENDING"], default=argparse.SUPPRESS
    )


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    add_common_args(parser)
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("auth", "probe", "delta"):
        add_common_args(sub.add_parser(name))

    args = parser.parse_args()
    for key, value in DEFAULTS.items():
        if not hasattr(args, key):
            setattr(args, key, value)

    return {"auth": cmd_auth, "probe": cmd_probe, "delta": cmd_delta}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
