#!/usr/bin/env python3
"""
Quick API Status Checker
Run this to see which endpoints are accessible and working.
"""

from src.canton_scan_client import SpliceScanClient

BASE_URL = "https://scan.sv-1.global.canton.network.sync.global/api/scan/"
FALLBACK_URL = "https://scan.sv-1.global.canton.network.cumberland.io/api/scan/"

def check_endpoint(name, func, description):
    """Test a single endpoint and report status."""
    try:
        result = func()
        if isinstance(result, dict):
            if 'error' in result:
                return f"✗ {name}: Error - {result['error']}"
            # Check for common result keys
            for key in ['open_mining_rounds', 'validators', 'updates', 'events', 'entries']:
                if key in result:
                    data = result[key]
                    count = len(data) if isinstance(data, (list, dict)) else 0
                    return f"✓ {name}: OK ({count} items) - {description}"
            return f"✓ {name}: OK (response received) - {description}"
        return f"? {name}: Unexpected response type"
    except Exception as e:
        error_type = type(e).__name__
        # Truncate long error messages
        error_msg = str(e)
        if len(error_msg) > 80:
            error_msg = error_msg[:77] + "..."
        return f"✗ {name}: {error_type} - {error_msg}"


def main():
    """Check API endpoint status."""
    print("=" * 80)
    print("SPLICE API STATUS CHECKER")
    print("=" * 80)

    # Try original MainNet URL first, fall back to fastest SV node
    import time
    url = BASE_URL
    print(f"Trying primary URL: {BASE_URL}...", end=" ", flush=True)
    try:
        test_client = SpliceScanClient(base_url=BASE_URL)
        start = time.time()
        test_client.get_dso()
        elapsed = time.time() - start
        test_client.close()
        print(f"✓ OK ({elapsed:.2f}s)")
    except Exception:
        print(f"✗ Unreachable, falling back to {FALLBACK_URL}")
        url = FALLBACK_URL

    print(f"Target: {url}")
    print()

    client = SpliceScanClient(base_url=url)

    # Test endpoints
    tests = [
        ("Mining Rounds",
         lambda: client.get_open_and_issuing_mining_rounds(),
         "Open and issuing mining rounds"),

        ("Closed Rounds",
         lambda: client.get_closed_rounds(),
         "Closed mining rounds"),

        ("Validators (Admin)",
         lambda: client.get_validator_licenses(limit=10),
         "Validator licenses (requires admin)"),

        ("Validators (Public)",
         lambda: client.get_top_validators_by_validator_faucets(limit=10),
         "Top validators by faucets (public)"),

        ("Updates",
         lambda: client.get_updates(page_size=10),
         "Transaction updates"),

        ("Events",
         lambda: client.get_events(page_size=10),
         "Transaction events"),

        ("ANS Entries",
         lambda: client.get_ans_entries(page_size=10),
         "ANS namespace entries"),

        ("DSO Info",
         lambda: client.get_dso(),
         "DSO information and SV states"),
    ]

    results = []
    for name, func, desc in tests:
        print(f"Testing: {name}...", end=" ", flush=True)
        result = check_endpoint(name, func, desc)
        print("\r" + " " * 80, end="\r")  # Clear line
        print(result)
        results.append((name, result.startswith("✓")))

    client.close()

    # Summary
    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)

    working = sum(1 for _, status in results if status)
    total = len(results)

    print(f"Working endpoints: {working}/{total}")
    print()

    if working == 0:
        print("⚠️  No endpoints accessible!")
        print("   - Check network connectivity")
        print("   - Verify API URL is correct")
        print("   - Check firewall/proxy settings")
    elif working < total:
        print("⚠️  Some endpoints not accessible:")
        for name, status in results:
            if not status:
                print(f"   - {name}")
        print()
        print("   This is normal for:")
        print("   - Admin endpoints (require authentication)")
        print("   - Empty ledgers (no data yet)")
    else:
        print("✓ All endpoints accessible!")

    print()
    print("For diagnostics, run:")
    print("  python splice_analytics_debug.py")
    print()

    # Test all 13 SV node URLs
    print()
    print("=" * 80)
    print("SV NODE CONNECTIVITY CHECK")
    print("=" * 80)
    print()

    from cloud_run.data_ingestion.canton_scan_client import MAINNET_SV_URLS

    sv_results = []
    for i, url in enumerate(MAINNET_SV_URLS, 1):
        # Extract short name from URL
        host = url.split("canton.network.")[1].split("/")[0]
        print(f"[{i:2d}/13] {host}...", end=" ", flush=True)
        start = time.time()
        try:
            sv_client = SpliceScanClient(base_url=url)
            result = sv_client.get_dso()
            elapsed = time.time() - start
            if isinstance(result, dict) and 'error' not in result:
                status = f"✓ OK ({elapsed:.2f}s)"
                sv_results.append((host, True, elapsed))
            else:
                status = f"✗ Error response ({elapsed:.2f}s)"
                sv_results.append((host, False, elapsed))
            sv_client.close()
        except Exception as e:
            elapsed = time.time() - start
            error_msg = str(e)
            if len(error_msg) > 60:
                error_msg = error_msg[:57] + "..."
            status = f"✗ {type(e).__name__} ({elapsed:.2f}s)"
            sv_results.append((host, False, elapsed))
        print("\r" + " " * 80, end="\r")
        print(f"[{i:2d}/13] {host:30s} {status}")

    print()
    print("=" * 80)
    print("SV NODE SUMMARY")
    print("=" * 80)
    reachable = sum(1 for _, ok, _ in sv_results if ok)
    print(f"Reachable: {reachable}/13")
    if reachable > 0:
        fastest = min((t, h) for h, ok, t in sv_results if ok)
        print(f"Fastest:   {fastest[1]} ({fastest[0]:.2f}s)")
    print()
    for host, ok, elapsed in sv_results:
        marker = "✓" if ok else "✗"
        print(f"  {marker} {host:30s} {elapsed:.2f}s")
    print()


if __name__ == "__main__":
    main()
