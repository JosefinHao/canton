"""
Deep Investigation: /v2/updates vs /v0/events

Goes far beyond the first-page comparison to thoroughly investigate:

  Phase 1: FULL-SCALE COUNTS
    Paginate exhaustively through every page of both endpoints for all migrations
    to get true total counts and verify set equality at full scale.

  Phase 2: REASSIGNMENT DETECTION
    Check whether /v2/updates returns reassignment-type records (contract key
    reassignments) that /v0/events doesn't include.

  Phase 3: VERDICT-ONLY RECORD DEEP-DIVE
    For events with null update bodies, fetch the individual event record and
    examine exactly what data the verdict contains and whether it's analytically
    useful.

  Phase 4: INDIVIDUAL ID CROSS-COMPARISON
    For a random sample of shared update_ids, fetch via both get_update_by_id
    and get_event_by_id, then compare the full JSON response structure
    field-by-field.

  Phase 5: TIME-DISTRIBUTED SAMPLING
    Sample from early, middle, and late time windows within each migration to
    verify the pattern holds across the full timeline.

  Phase 6: MULTI-NODE VERIFICATION
    Check a sample of IDs against different SV scan nodes to see if data
    availability varies between nodes.

Usage:
    python scripts/deep_investigation.py
    python scripts/deep_investigation.py --phases 1,3,4
    python scripts/deep_investigation.py --migration-id 4
    python scripts/deep_investigation.py --phase1-max-pages 5000
"""

import argparse
import hashlib
import json
import os
import random
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.canton_scan_client import SpliceScanClient

BASE_URL = "https://scan.sv-1.global.canton.network.sync.global/api/scan/"
REQUEST_DELAY = 0.12
MIGRATION_IDS = [0, 1, 2, 3, 4]

# Additional SV node URLs for multi-node verification
SV_NODES = {
    "sv-1": "https://scan.sv-1.global.canton.network.sync.global/api/scan/",
    "sv-2": "https://scan.sv-2.global.canton.network.sync.global/api/scan/",
    "sv-3": "https://scan.sv-3.global.canton.network.sync.global/api/scan/",
}


def banner(text: str, char: str = "=", width: int = 78):
    print(f"\n{char * width}")
    print(f"  {text}")
    print(f"{char * width}", flush=True)


def sub_banner(text: str):
    banner(text, char="-", width=78)


# ═══════════════════════════════════════════════════════════════════════════════
#  Phase 1: Full-Scale Counts
# ═══════════════════════════════════════════════════════════════════════════════

def phase1_full_counts(client, migrations, max_pages=5000, page_size=500):
    """Paginate exhaustively to get true total counts per migration."""
    banner("PHASE 1: FULL-SCALE COUNTS", char="█")
    print("  Paginates through ALL pages to get true total update & event counts.")
    print(f"  Max pages per endpoint per migration: {max_pages}")
    print(f"  Page size: {page_size}")

    results = []

    for mig_id in migrations:
        sub_banner(f"Migration {mig_id}")

        # ── /v2/updates full count ──
        print(f"  /v2/updates: counting...", flush=True)
        u_count, u_event_count, u_pages, u_time_range, u_reassignment_count = \
            _count_all(client, mig_id, page_size, max_pages, source="updates")
        print(f"    → {u_count} updates, {u_event_count} events, "
              f"{u_reassignment_count} reassignments in {u_pages} pages")
        if u_time_range[0]:
            print(f"    → Time: {u_time_range[0]} .. {u_time_range[1]}")

        # ── /v0/events full count ──
        print(f"  /v0/events: counting...", flush=True)
        e_count, e_event_count, e_pages, e_time_range, e_null_body_count = \
            _count_all(client, mig_id, page_size, max_pages, source="events")
        print(f"    → {e_count} updates ({e_null_body_count} null-body), "
              f"{e_event_count} events in {e_pages} pages")
        if e_time_range[0]:
            print(f"    → Time: {e_time_range[0]} .. {e_time_range[1]}")

        # Compare
        delta = u_count - (e_count - e_null_body_count)
        print(f"\n  Comparison:")
        print(f"    /v2/updates:                 {u_count} updates")
        print(f"    /v0/events (with body):      {e_count - e_null_body_count}")
        print(f"    /v0/events (null body):      {e_null_body_count}")
        print(f"    Delta (updates - events):    {delta}")
        if u_reassignment_count > 0:
            print(f"    ★ Reassignments in updates:  {u_reassignment_count}")

        reached_limit_u = u_pages >= max_pages
        reached_limit_e = e_pages >= max_pages

        if reached_limit_u or reached_limit_e:
            print(f"    ⚠ Hit page limit ({max_pages})! Results may be incomplete.")
            print(f"       Updates: {'LIMIT' if reached_limit_u else 'complete'}, "
                  f"Events: {'LIMIT' if reached_limit_e else 'complete'}")

        results.append({
            "migration_id": mig_id,
            "updates_total": u_count,
            "updates_events_total": u_event_count,
            "updates_pages": u_pages,
            "updates_reassignments": u_reassignment_count,
            "updates_time_range": u_time_range,
            "events_total": e_count,
            "events_events_total": e_event_count,
            "events_null_body": e_null_body_count,
            "events_pages": e_pages,
            "events_time_range": e_time_range,
            "reached_page_limit": reached_limit_u or reached_limit_e,
        })

    # Summary table
    print(f"\n  {'Mig':>4} {'Upd Total':>10} {'Upd Evts':>10} {'Evt Total':>10} "
          f"{'Evt NullB':>10} {'Evt Evts':>10} {'Reassign':>9} {'Status':>10}")
    print(f"  {'─'*4} {'─'*10} {'─'*10} {'─'*10} {'─'*10} {'─'*10} {'─'*9} {'─'*10}")
    for r in results:
        status = "LIMIT" if r["reached_page_limit"] else "complete"
        print(f"  {r['migration_id']:>4} {r['updates_total']:>10} "
              f"{r['updates_events_total']:>10} {r['events_total']:>10} "
              f"{r['events_null_body']:>10} {r['events_events_total']:>10} "
              f"{r['updates_reassignments']:>9} {status:>10}")

    total_u = sum(r["updates_total"] for r in results)
    total_e = sum(r["events_total"] for r in results)
    total_null = sum(r["events_null_body"] for r in results)
    total_reassign = sum(r["updates_reassignments"] for r in results)
    print(f"\n  Grand totals: {total_u} updates, {total_e} events "
          f"({total_null} null-body), {total_reassign} reassignments")

    return results


def _count_all(client, migration_id, page_size, max_pages, source):
    """Count all updates and events for one migration from one endpoint."""
    total_updates = 0
    total_events = 0
    extra_count = 0  # reassignments for updates, null-body for events
    cursor_rt = "2000-01-01T00:00:00Z"
    first_rt = None
    last_rt = None

    for page_num in range(max_pages):
        try:
            if source == "updates":
                resp = client.get_updates(
                    after_migration_id=migration_id,
                    after_record_time=cursor_rt,
                    page_size=page_size,
                )
                items = resp.get("updates", resp.get("transactions", []))
            else:
                resp = client.get_events(
                    after_migration_id=migration_id,
                    after_record_time=cursor_rt,
                    page_size=page_size,
                )
                items = resp.get("events", [])
            time.sleep(REQUEST_DELAY)
        except Exception as e:
            print(f"    ERROR page {page_num + 1}: {e}")
            time.sleep(2)
            continue

        if not items:
            break

        for item in items:
            if source == "events":
                wrapper = item
                update = wrapper.get("update")
                if not update:
                    extra_count += 1
                    total_updates += 1
                    continue
                item = update

            item_mig = item.get("migration_id")
            if item_mig is not None and item_mig != migration_id:
                return total_updates, total_events, page_num + 1, (first_rt, last_rt), extra_count

            rt = item.get("record_time")
            if rt:
                if first_rt is None:
                    first_rt = rt
                last_rt = rt

            # Count events inside events_by_id
            ebi = item.get("events_by_id", {})
            total_events += len(ebi)

            # Check for reassignments (updates endpoint only)
            if source == "updates":
                if "reassignment" in item or item.get("update_type") == "reassignment":
                    extra_count += 1

            total_updates += 1

        after = resp.get("after")
        if not after:
            break

        next_mig = after.get("after_migration_id")
        if next_mig != migration_id:
            break

        cursor_rt = after.get("after_record_time")

        if (page_num + 1) % 50 == 0:
            print(f"    ... page {page_num + 1}: {total_updates} updates, "
                  f"{total_events} events at {cursor_rt}", flush=True)

        if page_num == 0:
            print(f"    [debug] page 1 returned {len(items)} items, "
                  f"after cursor: mig={after.get('after_migration_id')}, "
                  f"rt={after.get('after_record_time')}")

        if len(items) < page_size:
            break

    pages_done = page_num + 1 if 'page_num' in dir() else 0
    return total_updates, total_events, pages_done, (first_rt, last_rt), extra_count


# ═══════════════════════════════════════════════════════════════════════════════
#  Phase 2: Reassignment Detection
# ═══════════════════════════════════════════════════════════════════════════════

def phase2_reassignments(client, migrations, max_pages=200, page_size=500):
    """Check for reassignment-type records in /v2/updates that may not be in /v0/events."""
    banner("PHASE 2: REASSIGNMENT DETECTION", char="█")
    print("  Scanning /v2/updates for reassignment-type records.")
    print("  Reassignments are contract key reassignments that may not appear in /v0/events.\n")

    all_reassignments = []

    for mig_id in migrations:
        sub_banner(f"Migration {mig_id}")
        cursor_rt = "2000-01-01T00:00:00Z"
        mig_reassignments = []

        for page_num in range(max_pages):
            try:
                resp = client.get_updates(
                    after_migration_id=mig_id,
                    after_record_time=cursor_rt,
                    page_size=page_size,
                )
                items = resp.get("updates", resp.get("transactions", []))
                time.sleep(REQUEST_DELAY)
            except Exception as e:
                print(f"    ERROR page {page_num + 1}: {e}")
                time.sleep(2)
                continue

            if not items:
                break

            for item in items:
                item_mig = item.get("migration_id")
                if item_mig is not None and item_mig != mig_id:
                    break

                # Check multiple indicators of reassignment
                is_reassignment = False
                reassignment_data = {}

                # Check for explicit reassignment field
                if "reassignment" in item:
                    is_reassignment = True
                    reassignment_data = item["reassignment"]
                # Check for reassignment in update_type or similar fields
                elif item.get("update_type") == "reassignment":
                    is_reassignment = True
                # Check if events_by_id is empty but update exists (potential reassignment)
                elif not item.get("events_by_id") and item.get("update_id"):
                    # Might be a reassignment — no events but has an ID
                    is_reassignment = True
                    reassignment_data = {"note": "no events_by_id"}

                if is_reassignment:
                    uid = item.get("update_id", "unknown")
                    rt = item.get("record_time", "unknown")
                    mig_reassignments.append({
                        "update_id": uid,
                        "record_time": rt,
                        "keys": sorted(item.keys()),
                        "reassignment_data_keys": sorted(reassignment_data.keys())
                            if isinstance(reassignment_data, dict) else str(reassignment_data),
                    })

            after = resp.get("after")
            if not after or after.get("after_migration_id") != mig_id:
                break
            cursor_rt = after.get("after_record_time")

            if (page_num + 1) % 50 == 0:
                print(f"    ... page {page_num + 1}, "
                      f"{len(mig_reassignments)} reassignments found", flush=True)

            if len(items) < page_size:
                break

        print(f"  Migration {mig_id}: {len(mig_reassignments)} reassignments found")
        if mig_reassignments:
            for r in mig_reassignments[:5]:
                print(f"    {r['update_id'][:50]}...")
                print(f"      Keys: {r['keys']}")
                if r.get('reassignment_data_keys'):
                    print(f"      Reassignment keys: {r['reassignment_data_keys']}")

            # Cross-check: do these exist in /v0/events?
            print(f"\n  Cross-checking {min(10, len(mig_reassignments))} reassignments "
                  f"against /v0/events...")
            for r in mig_reassignments[:10]:
                uid = r["update_id"]
                try:
                    e_resp = client.get_event_by_id(uid)
                    time.sleep(REQUEST_DELAY)
                    has_update = bool(e_resp.get("update"))
                    has_verdict = bool(e_resp.get("verdict"))
                    print(f"    {uid[:40]}... → events: ✓ "
                          f"(update={has_update}, verdict={has_verdict})")
                except Exception as e:
                    print(f"    {uid[:40]}... → events: ✗ ({e})")

        all_reassignments.extend(mig_reassignments)

    print(f"\n  TOTAL REASSIGNMENTS: {len(all_reassignments)}")
    return all_reassignments


# ═══════════════════════════════════════════════════════════════════════════════
#  Phase 3: Verdict-Only Record Deep-Dive
# ═══════════════════════════════════════════════════════════════════════════════

def phase3_verdict_deep_dive(client, migrations, page_size=500, max_null_to_fetch=50):
    """Fetch and examine verdict-only records from /v0/events."""
    banner("PHASE 3: VERDICT-ONLY RECORD DEEP-DIVE", char="█")
    print("  Fetches events with null update body and examines verdict content.")
    print(f"  Will examine up to {max_null_to_fetch} null-body records in detail.\n")

    null_records = []

    for mig_id in migrations:
        sub_banner(f"Migration {mig_id} — collecting null-body records")
        cursor_rt = "2000-01-01T00:00:00Z"

        for page_num in range(200):  # Enough to find null-body records
            try:
                resp = client.get_events(
                    after_migration_id=mig_id,
                    after_record_time=cursor_rt,
                    page_size=page_size,
                )
                raw_events = resp.get("events", [])
                time.sleep(REQUEST_DELAY)
            except Exception as e:
                print(f"    ERROR: {e}")
                time.sleep(2)
                continue

            if not raw_events:
                break

            for wrapper in raw_events:
                update = wrapper.get("update")
                if update:
                    mig = update.get("migration_id")
                    if mig is not None and mig != mig_id:
                        break
                    continue

                # This is a null-body record
                verdict = wrapper.get("verdict", {})
                null_records.append({
                    "migration_id": mig_id,
                    "wrapper_keys": sorted(wrapper.keys()),
                    "verdict": verdict,
                    "update_id": verdict.get("update_id") if verdict else None,
                })

            after = resp.get("after")
            if not after or after.get("after_migration_id") != mig_id:
                break
            cursor_rt = after.get("after_record_time")

            if len(null_records) >= max_null_to_fetch * 2:
                break

            if len(raw_events) < page_size:
                break

        print(f"  Migration {mig_id}: {len([r for r in null_records if r['migration_id'] == mig_id])} "
              f"null-body records collected")

    if not null_records:
        print("\n  No null-body records found. All events have update bodies.")
        return []

    print(f"\n  Total null-body records: {len(null_records)}")

    # Analyze verdict content
    sub_banner("Verdict Content Analysis")

    verdict_results = Counter()
    has_finalization = 0
    has_submitting_parties = 0
    has_transaction_views = 0
    has_mediator = 0
    verdict_keys_counter = Counter()
    submitting_parties_set = set()

    for rec in null_records:
        v = rec.get("verdict", {})
        if not v:
            verdict_results["NO_VERDICT"] += 1
            continue

        vr = v.get("verdict_result", "MISSING")
        verdict_results[vr] += 1

        if v.get("finalization_time"):
            has_finalization += 1
        if v.get("submitting_parties"):
            has_submitting_parties += 1
            for sp in v.get("submitting_parties", []):
                submitting_parties_set.add(sp)
        if v.get("transaction_views"):
            has_transaction_views += 1
        if v.get("mediator_group"):
            has_mediator += 1

        for k in v.keys():
            verdict_keys_counter[k] += 1

    print(f"  Verdict results:      {dict(verdict_results)}")
    print(f"  Has finalization_time: {has_finalization}/{len(null_records)}")
    print(f"  Has submitting_parties:{has_submitting_parties}/{len(null_records)}")
    print(f"  Has transaction_views: {has_transaction_views}/{len(null_records)}")
    print(f"  Has mediator_group:    {has_mediator}/{len(null_records)}")
    print(f"  Unique submitting parties: {len(submitting_parties_set)}")

    print(f"\n  Verdict field presence:")
    for k, count in verdict_keys_counter.most_common():
        print(f"    {k:30s} {count}/{len(null_records)}")

    # Fetch individual records for deeper inspection
    sub_banner("Individual null-body record inspection")
    to_fetch = null_records[:max_null_to_fetch]
    print(f"  Fetching {len(to_fetch)} records by ID from /v0/events endpoint...")

    fetched_details = []
    for i, rec in enumerate(to_fetch):
        uid = rec.get("update_id")
        if not uid:
            print(f"  [{i+1}] No update_id in verdict, skipping")
            continue

        try:
            full = client.get_event_by_id(uid)
            time.sleep(REQUEST_DELAY)

            # Handle non-dict responses (API may return string for some IDs)
            if not isinstance(full, dict):
                print(f"  [{i+1}] {uid[:40]}... → non-dict response: {type(full).__name__} = {str(full)[:100]}")
                fetched_details.append({
                    "update_id": uid, "response_type": type(full).__name__,
                    "has_update": False, "has_verdict": False, "event_count": 0,
                })
                continue

            upd_raw = full.get("update")
            vrd_raw = full.get("verdict")

            detail = {
                "update_id": uid,
                "response_keys": sorted(full.keys()),
                "has_update": isinstance(upd_raw, dict) and bool(upd_raw),
                "has_verdict": isinstance(vrd_raw, dict) and bool(vrd_raw),
                "update_type": type(upd_raw).__name__,
                "verdict_type": type(vrd_raw).__name__,
            }

            if isinstance(upd_raw, dict) and upd_raw:
                detail["update_keys"] = sorted(upd_raw.keys())
                ebi = upd_raw.get("events_by_id", {})
                detail["event_count"] = len(ebi) if isinstance(ebi, dict) else 0
                templates = set()
                if isinstance(ebi, dict):
                    for evt in ebi.values():
                        if isinstance(evt, dict):
                            tid = evt.get("template_id", "")
                            templates.add(tid)
                detail["templates"] = sorted(templates)
            else:
                detail["update_keys"] = None
                detail["event_count"] = 0
                if upd_raw is not None:
                    detail["update_raw_preview"] = str(upd_raw)[:200]

            if isinstance(vrd_raw, dict) and vrd_raw:
                detail["verdict_keys"] = sorted(vrd_raw.keys())
                detail["verdict_result"] = vrd_raw.get("verdict_result")
                tv = vrd_raw.get("transaction_views", [])
                detail["transaction_view_count"] = len(tv) if isinstance(tv, list) else 0
                if isinstance(tv, list) and tv:
                    total_informees = set()
                    for view in tv:
                        if isinstance(view, dict):
                            for inf in view.get("informees", []):
                                total_informees.add(inf)
                    detail["unique_informees"] = len(total_informees)
                else:
                    detail["unique_informees"] = 0
            else:
                if vrd_raw is not None and not isinstance(vrd_raw, dict):
                    detail["verdict_raw_preview"] = str(vrd_raw)[:200]

            fetched_details.append(detail)

            status = "has body" if detail["has_update"] else "NO BODY"
            upd_type_note = f" (update={detail['update_type']})" if not detail["has_update"] and upd_raw is not None else ""
            print(f"  [{i+1}] {uid[:40]}... → {status}{upd_type_note}, "
                  f"verdict={detail.get('verdict_result', 'none')}, "
                  f"events={detail['event_count']}, "
                  f"views={detail.get('transaction_view_count', 0)}")

        except Exception as e:
            print(f"  [{i+1}] {uid[:40] if uid else '?'}... → ERROR: {e}")

    # Summary
    with_body = sum(1 for d in fetched_details if d["has_update"])
    without_body = sum(1 for d in fetched_details if not d["has_update"])
    print(f"\n  Of {len(fetched_details)} fetched individually:")
    print(f"    With update body:    {with_body}")
    print(f"    Without update body: {without_body}")
    print(f"    ★ If all have bodies when fetched individually, the null bodies in")
    print(f"      pagination are a pagination artifact, not missing data.")

    return null_records


# ═══════════════════════════════════════════════════════════════════════════════
#  Phase 4: Individual ID Cross-Comparison
# ═══════════════════════════════════════════════════════════════════════════════

def phase4_cross_comparison(client, migrations, sample_size=30):
    """Fetch same IDs from both endpoints and compare response structure."""
    banner("PHASE 4: INDIVIDUAL ID CROSS-COMPARISON", char="█")
    print(f"  Fetches {sample_size} random IDs from both endpoints and compares")
    print(f"  the full JSON response structure field-by-field.\n")

    # First, collect some IDs from /v2/updates
    all_ids = []
    for mig_id in migrations:
        resp = client.get_updates(
            after_migration_id=mig_id,
            after_record_time="2000-01-01T00:00:00Z",
            page_size=100,
        )
        items = resp.get("updates", resp.get("transactions", []))
        time.sleep(REQUEST_DELAY)
        for item in items:
            if item.get("migration_id") == mig_id:
                uid = item.get("update_id")
                if uid:
                    all_ids.append((mig_id, uid))

    if len(all_ids) < sample_size:
        sample_size = len(all_ids)

    sample = random.sample(all_ids, sample_size)
    print(f"  Selected {sample_size} IDs across migrations: "
          f"{Counter(mig for mig, _ in sample)}\n")

    results = {
        "identical_bodies": 0,
        "different_bodies": 0,
        "events_has_verdict": 0,
        "events_missing_verdict": 0,
        "events_extra_fields": Counter(),
        "updates_extra_fields": Counter(),
        "body_hash_matches": 0,
        "body_hash_mismatches": 0,
        "errors": 0,
        "details": [],
    }

    for i, (mig_id, uid) in enumerate(sample):
        try:
            # Fetch from /v2/updates/{id}
            u_resp = client.get_update_by_id(uid)
            time.sleep(REQUEST_DELAY)

            # Fetch from /v0/events/{id}
            e_resp = client.get_event_by_id(uid)
            time.sleep(REQUEST_DELAY)

            # Compare top-level keys
            u_keys = set(u_resp.keys())
            e_keys = set(e_resp.keys())

            # The event response wraps in {"update": {...}, "verdict": {...}}
            # The update response returns the update directly
            # Extract comparable bodies
            e_update = e_resp.get("update", {})
            e_verdict = e_resp.get("verdict")

            # Determine update body from /v2/updates response
            # It might be under "transaction" or directly in the response
            u_body = u_resp.get("transaction", u_resp.get("update", u_resp))

            # Hash compare the update bodies
            u_hash = hashlib.sha256(
                json.dumps(u_body, sort_keys=True).encode()
            ).hexdigest()[:16]
            e_hash = hashlib.sha256(
                json.dumps(e_update, sort_keys=True).encode()
            ).hexdigest()[:16]

            bodies_match = u_hash == e_hash

            if bodies_match:
                results["body_hash_matches"] += 1
            else:
                results["body_hash_mismatches"] += 1

            if e_verdict:
                results["events_has_verdict"] += 1
            else:
                results["events_missing_verdict"] += 1

            # Field-level comparison of update bodies
            u_body_keys = set(u_body.keys()) if isinstance(u_body, dict) else set()
            e_body_keys = set(e_update.keys()) if isinstance(e_update, dict) else set()

            only_in_u = u_body_keys - e_body_keys
            only_in_e = e_body_keys - u_body_keys

            for f in only_in_u:
                results["updates_extra_fields"][f] += 1
            for f in only_in_e:
                results["events_extra_fields"][f] += 1

            detail = {
                "update_id": uid[:40],
                "migration_id": mig_id,
                "bodies_match": bodies_match,
                "has_verdict": bool(e_verdict),
                "u_resp_keys": sorted(u_keys),
                "e_resp_keys": sorted(e_keys),
                "u_body_keys": sorted(u_body_keys),
                "e_body_keys": sorted(e_body_keys),
                "only_in_updates": sorted(only_in_u),
                "only_in_events": sorted(only_in_e),
            }

            if e_verdict:
                detail["verdict_result"] = e_verdict.get("verdict_result")
                detail["verdict_keys"] = sorted(e_verdict.keys())

            results["details"].append(detail)

            match_str = "✓ MATCH" if bodies_match else "✗ DIFFER"
            verdict_str = f"verdict={e_verdict.get('verdict_result')}" if e_verdict else "no verdict"
            print(f"  [{i+1:2d}] mig{mig_id} {uid[:30]}... body:{match_str} {verdict_str}",
                  end="")
            if only_in_u:
                print(f" +upd:{sorted(only_in_u)}", end="")
            if only_in_e:
                print(f" +evt:{sorted(only_in_e)}", end="")
            print()

        except Exception as e:
            results["errors"] += 1
            print(f"  [{i+1:2d}] mig{mig_id} {uid[:30]}... ERROR: {e}")

    # Summary
    sub_banner("Cross-Comparison Summary")
    print(f"  Body hash matches:     {results['body_hash_matches']}/{sample_size}")
    print(f"  Body hash mismatches:  {results['body_hash_mismatches']}/{sample_size}")
    print(f"  Events with verdict:   {results['events_has_verdict']}/{sample_size}")
    print(f"  Events sans verdict:   {results['events_missing_verdict']}/{sample_size}")
    print(f"  Errors:                {results['errors']}/{sample_size}")

    if results["updates_extra_fields"]:
        print(f"\n  Fields ONLY in /v2/updates response body:")
        for f, c in results["updates_extra_fields"].most_common():
            print(f"    {f:30s} ({c}/{sample_size})")

    if results["events_extra_fields"]:
        print(f"\n  Fields ONLY in /v0/events update body:")
        for f, c in results["events_extra_fields"].most_common():
            print(f"    {f:30s} ({c}/{sample_size})")

    if not results["updates_extra_fields"] and not results["events_extra_fields"]:
        print(f"\n  ✓ Update body fields are IDENTICAL between both endpoints")

    return results


# ═══════════════════════════════════════════════════════════════════════════════
#  Phase 5: Time-Distributed Sampling
# ═══════════════════════════════════════════════════════════════════════════════

def phase5_time_sampling(client, migrations, page_size=500):
    """Sample from early, middle, and late windows within each migration."""
    banner("PHASE 5: TIME-DISTRIBUTED SAMPLING", char="█")
    print("  Samples from beginning, middle, and end of each migration")
    print("  to verify consistency across the full timeline.\n")

    results = []

    for mig_id in migrations:
        sub_banner(f"Migration {mig_id}")

        # First, find the time range by getting the first and last pages
        print(f"  Finding time range...")

        # Get first page
        resp = client.get_updates(
            after_migration_id=mig_id,
            after_record_time="2000-01-01T00:00:00Z",
            page_size=5,
        )
        first_items = resp.get("updates", resp.get("transactions", []))
        time.sleep(REQUEST_DELAY)

        if not first_items:
            print(f"  No data for migration {mig_id}")
            continue

        first_rt = first_items[0].get("record_time")

        # Find the end by paginating forward (use large pages)
        cursor_rt = first_rt
        last_rt = first_rt
        pages_counted = 0

        for _ in range(2000):
            resp = client.get_updates(
                after_migration_id=mig_id,
                after_record_time=cursor_rt,
                page_size=500,
            )
            items = resp.get("updates", resp.get("transactions", []))
            time.sleep(REQUEST_DELAY)
            pages_counted += 1

            if not items:
                break

            # Filter to this migration
            mig_items = [t for t in items if t.get("migration_id") == mig_id]
            if mig_items:
                last_rt = mig_items[-1].get("record_time", last_rt)

            after = resp.get("after")
            if not after or after.get("after_migration_id") != mig_id:
                break
            cursor_rt = after.get("after_record_time")

            if (pages_counted) % 100 == 0:
                print(f"    ... finding end: page {pages_counted} at {cursor_rt}", flush=True)

            if len(items) < 500:
                break

        print(f"  Time range: {first_rt} → {last_rt} ({pages_counted} pages)")

        # Now sample from 3 time windows: early, middle, late
        from datetime import datetime as dt

        try:
            t_start = dt.fromisoformat(first_rt.replace("Z", "+00:00"))
            t_end = dt.fromisoformat(last_rt.replace("Z", "+00:00"))
        except Exception:
            print(f"  Cannot parse time range, skipping")
            continue

        total_seconds = (t_end - t_start).total_seconds()
        if total_seconds < 60:
            print(f"  Time range too short ({total_seconds}s), skipping")
            continue

        sample_points = {
            "early": first_rt,
            "middle": (t_start + (t_end - t_start) / 2).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "late": (t_end - (t_end - t_start) * 0.05).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        }

        mig_result = {"migration_id": mig_id, "samples": {}}

        for label, sample_rt in sample_points.items():
            print(f"\n  [{label.upper()}] Sampling at {sample_rt}...")

            # Get one page from /v2/updates
            try:
                u_resp = client.get_updates(
                    after_migration_id=mig_id,
                    after_record_time=sample_rt,
                    page_size=page_size,
                )
                u_items = u_resp.get("updates", u_resp.get("transactions", []))
                u_items = [t for t in u_items if t.get("migration_id") == mig_id]
                time.sleep(REQUEST_DELAY)
            except Exception as e:
                print(f"    /v2/updates ERROR: {e}")
                u_items = []

            # Get one page from /v0/events
            try:
                e_resp = client.get_events(
                    after_migration_id=mig_id,
                    after_record_time=sample_rt,
                    page_size=page_size,
                )
                e_raw = e_resp.get("events", [])
                time.sleep(REQUEST_DELAY)

                e_items = []
                e_null = 0
                for wrapper in e_raw:
                    upd = wrapper.get("update")
                    if upd:
                        if upd.get("migration_id") == mig_id:
                            e_items.append(upd)
                    else:
                        e_null += 1
            except Exception as e:
                print(f"    /v0/events ERROR: {e}")
                e_items = []
                e_null = 0

            # Compare IDs
            u_ids = {t["update_id"] for t in u_items if t.get("update_id")}
            e_ids = {t["update_id"] for t in e_items if t.get("update_id")}

            u_event_ids = set()
            e_event_ids = set()
            for t in u_items:
                u_event_ids.update(t.get("events_by_id", {}).keys())
            for t in e_items:
                e_event_ids.update(t.get("events_by_id", {}).keys())

            overlap = u_ids & e_ids
            only_u = u_ids - e_ids
            only_e = e_ids - u_ids

            print(f"    /v2/updates: {len(u_items)} updates, {len(u_event_ids)} events")
            print(f"    /v0/events:  {len(e_items)} updates (+{e_null} null-body), "
                  f"{len(e_event_ids)} events")
            print(f"    Overlap: {len(overlap)} | Only updates: {len(only_u)} | "
                  f"Only events: {len(only_e)}")

            # For overlapping IDs, verify content identity
            if overlap:
                sample_check = list(overlap)[:10]
                mismatches = 0
                for uid in sample_check:
                    u_item = next(t for t in u_items if t["update_id"] == uid)
                    e_item = next(t for t in e_items if t["update_id"] == uid)
                    u_h = hashlib.sha256(json.dumps(u_item, sort_keys=True).encode()).hexdigest()
                    e_h = hashlib.sha256(json.dumps(e_item, sort_keys=True).encode()).hexdigest()
                    if u_h != e_h:
                        mismatches += 1
                print(f"    Content check ({len(sample_check)} samples): "
                      f"{'✓ ALL IDENTICAL' if mismatches == 0 else f'✗ {mismatches} DIFFER'}")

            mig_result["samples"][label] = {
                "sample_time": sample_rt,
                "updates_count": len(u_items),
                "events_count": len(e_items),
                "null_body": e_null,
                "overlap": len(overlap),
                "only_updates": len(only_u),
                "only_events": len(only_e),
            }

        results.append(mig_result)

    return results


# ═══════════════════════════════════════════════════════════════════════════════
#  Phase 6: Multi-Node Verification
# ═══════════════════════════════════════════════════════════════════════════════

def phase6_multi_node(client, migrations, sample_size=10):
    """Check IDs against different SV scan nodes."""
    banner("PHASE 6: MULTI-NODE VERIFICATION", char="█")
    print("  Checks if different SV nodes return the same data for the same IDs.\n")

    # Collect sample IDs from primary node
    sample_ids = []
    for mig_id in migrations:
        resp = client.get_updates(
            after_migration_id=mig_id,
            after_record_time="2000-01-01T00:00:00Z",
            page_size=20,
        )
        items = resp.get("updates", resp.get("transactions", []))
        time.sleep(REQUEST_DELAY)
        for item in items[:5]:
            if item.get("update_id") and item.get("migration_id") == mig_id:
                sample_ids.append((mig_id, item["update_id"]))

    if len(sample_ids) > sample_size:
        sample_ids = random.sample(sample_ids, sample_size)

    print(f"  Testing {len(sample_ids)} IDs across {len(SV_NODES)} SV nodes\n")

    # Create clients for each node
    node_clients = {}
    for name, url in SV_NODES.items():
        try:
            c = SpliceScanClient(base_url=url, timeout=30)
            if c.health_check():
                node_clients[name] = c
                print(f"  {name}: ✓ reachable")
            else:
                print(f"  {name}: ✗ (health check failed)")
                c.close()
        except Exception as e:
            print(f"  {name}: ✗ ({e})")

    if len(node_clients) < 2:
        print("\n  Not enough reachable nodes for multi-node comparison.")
        for c in node_clients.values():
            c.close()
        return {}

    print()

    results = {"matches": 0, "mismatches": 0, "errors": 0, "details": []}

    for mig_id, uid in sample_ids:
        hashes = {}
        for name, nc in node_clients.items():
            try:
                resp = nc.get_update_by_id(uid)
                time.sleep(REQUEST_DELAY)
                body = resp.get("transaction", resp.get("update", resp))
                h = hashlib.sha256(
                    json.dumps(body, sort_keys=True).encode()
                ).hexdigest()[:16]
                hashes[name] = h
            except Exception as e:
                hashes[name] = f"ERROR:{e}"

        unique_hashes = set(v for v in hashes.values() if not v.startswith("ERROR"))
        all_match = len(unique_hashes) <= 1

        if all_match:
            results["matches"] += 1
            status = "✓"
        else:
            results["mismatches"] += 1
            status = "✗ MISMATCH"

        hash_str = " | ".join(f"{n}={h[:8]}" for n, h in sorted(hashes.items()))
        print(f"  mig{mig_id} {uid[:30]}... {status} [{hash_str}]")

        results["details"].append({
            "update_id": uid,
            "migration_id": mig_id,
            "hashes": hashes,
            "all_match": all_match,
        })

    # Cleanup
    for c in node_clients.values():
        c.close()

    sub_banner("Multi-Node Summary")
    print(f"  Matches:    {results['matches']}/{len(sample_ids)}")
    print(f"  Mismatches: {results['mismatches']}/{len(sample_ids)}")
    if results["matches"] == len(sample_ids):
        print(f"  ✓ All SV nodes return identical data")

    return results


# ═══════════════════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Deep investigation: /v2/updates vs /v0/events"
    )
    parser.add_argument("--phases", type=str, default="1,2,3,4,5,6",
                        help="Comma-separated phase numbers to run (default: all)")
    parser.add_argument("--migration-id", type=int,
                        help="Check only this migration (default: all)")
    parser.add_argument("--phase1-max-pages", type=int, default=5000,
                        help="Max pages per endpoint for Phase 1 (default: 5000)")
    parser.add_argument("--page-size", type=int, default=500,
                        help="Page size for API requests (default: 500)")
    parser.add_argument("--output-json", type=str,
                        help="Save results to JSON file")
    parser.add_argument("--base-url", type=str, default=BASE_URL)
    args = parser.parse_args()

    phases = [int(p.strip()) for p in args.phases.split(",")]

    banner("DEEP INVESTIGATION: /v2/updates vs /v0/events", char="█", width=78)
    print(f"  Time:        {datetime.utcnow().isoformat()}Z")
    print(f"  Phases:      {phases}")
    print(f"  API:         {args.base_url}")

    if args.migration_id is not None:
        migrations = [args.migration_id]
    else:
        migrations = MIGRATION_IDS

    print(f"  Migrations:  {migrations}")

    client = SpliceScanClient(base_url=args.base_url, timeout=60)
    all_results = {}

    try:
        if 1 in phases:
            all_results["phase1"] = phase1_full_counts(
                client, migrations,
                max_pages=args.phase1_max_pages,
                page_size=args.page_size)

        if 2 in phases:
            all_results["phase2"] = phase2_reassignments(
                client, migrations,
                page_size=args.page_size)

        if 3 in phases:
            all_results["phase3"] = phase3_verdict_deep_dive(
                client, migrations,
                page_size=args.page_size)

        if 4 in phases:
            all_results["phase4"] = phase4_cross_comparison(
                client, migrations, sample_size=30)

        if 5 in phases:
            all_results["phase5"] = phase5_time_sampling(
                client, migrations, page_size=args.page_size)

        if 6 in phases:
            all_results["phase6"] = phase6_multi_node(
                client, migrations, sample_size=10)

        # ── Final Verdict ──
        banner("FINAL ASSESSMENT", char="█", width=78)
        print("  Based on all phases of investigation:\n")

        if "phase1" in all_results:
            p1 = all_results["phase1"]
            total_u = sum(r["updates_total"] for r in p1)
            total_e = sum(r["events_total"] for r in p1)
            total_null = sum(r["events_null_body"] for r in p1)
            total_reassign = sum(r["updates_reassignments"] for r in p1)
            any_limit = any(r["reached_page_limit"] for r in p1)
            print(f"  1. SCALE: {total_u} updates vs {total_e} events "
                  f"({total_null} null-body, {total_reassign} reassignments)")
            if any_limit:
                print(f"     ⚠ Some migrations hit page limits — counts may be incomplete")

        if "phase4" in all_results:
            p4 = all_results["phase4"]
            print(f"  4. CONTENT: {p4['body_hash_matches']}/{p4['body_hash_matches'] + p4['body_hash_mismatches']} "
                  f"update bodies are byte-identical between endpoints")

        print()

    finally:
        client.close()

    if args.output_json:
        os.makedirs(os.path.dirname(args.output_json) or ".", exist_ok=True)
        def sanitize(obj):
            if isinstance(obj, set):
                return sorted(obj)
            if isinstance(obj, tuple):
                return list(obj)
            if isinstance(obj, dict):
                return {k: sanitize(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [sanitize(v) for v in obj]
            return obj
        with open(args.output_json, "w") as f:
            json.dump(sanitize(all_results), f, indent=2, default=str)
        print(f"  Results saved to: {args.output_json}")

    banner("Investigation complete", char="█", width=78)


if __name__ == "__main__":
    main()
