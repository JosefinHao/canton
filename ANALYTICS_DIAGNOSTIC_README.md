# Splice Analytics Diagnostic Guide

## Issue Summary

When running `splice_analytics.py`, you may encounter missing data for:
- **Validator Network**: Shows 0 validators
- **Transaction Updates**: Shows 0 updates

While other endpoints like **Mining Rounds** work correctly.

## Root Cause

The issue stems from two main factors:

### 1. API Endpoint Access Restrictions

Some endpoints require elevated permissions or authentication:

- **`/v0/admin/validator/licenses`** - Requires admin privileges (403 Forbidden)
- **`/v2/updates`** - May return empty results or require authentication
- **`/v0/events`** - Alternative endpoint that may also have restrictions

### 2. Silent Error Handling

The original code caught exceptions and returned error dictionaries, but the calling code used `.get()` with default values, masking actual errors and showing `0` instead of error messages.

## Solutions Implemented

### 1. Improved Error Reporting (`splice_analytics.py`)

**Changes made:**
- Added verbose error messages that are displayed in the report
- Implemented fallback methods to try alternative API endpoints
- Better diagnostics when endpoints fail or return empty data

**Validator Data Fallback Chain:**
1. Try `/v0/admin/validator/licenses` (requires admin)
2. Try `/v0/top-validators-by-validator-faucets` (public endpoint)
3. Try `/v0/dso` for SV node states (alternative)

**Transaction Data Improvements:**
- Shows clear messages when ledger is empty vs. authentication failures
- Provides context about why data might be missing

### 2. Diagnostic Tool (`splice_analytics_debug.py`)

A comprehensive diagnostic script that tests all endpoints and shows exactly what's failing.

**Usage:**
```bash
python splice_analytics_debug.py
```

**What it tests:**
- Mining Rounds (control test - should work)
- Validators (3 different methods)
- Updates/Events (2 different methods)

**Output includes:**
- Success/failure status for each method
- Error types and messages
- Sample data structure when successful
- Recommendations for fixing issues

### 3. Simple Endpoint Test (`test_alternative_endpoints.py`)

Quick test script for specific endpoints.

## How to Use

### Step 1: Run Diagnostic

First, run the diagnostic to see what's failing:

```bash
python splice_analytics_debug.py
```

This will show you:
- ✓ Which endpoints are working
- ✗ Which endpoints are failing
- Error messages and types
- Recommendations for fixes

### Step 2: Run Improved Analytics

The improved `splice_analytics.py` now includes:
- Better error messages
- Multiple fallback methods
- Clear explanations when data is missing

```bash
python splice_analytics.py
```

### Step 3: Interpret Results

**If you see "0 validators":**
- Check the error message in the report
- The `/admin/validator/licenses` endpoint likely requires authentication
- Try obtaining API credentials or admin access
- Alternative: The network may genuinely have no validators yet

**If you see "0 updates":**
- Check if the ledger is empty (no transactions yet)
- The endpoint may require authentication
- Try using the `/v0/events` endpoint as alternative

**If mining rounds work but others don't:**
- This confirms API connectivity is fine
- The specific endpoints have access restrictions
- Check with your API provider for required credentials

## API Endpoint Reference

### Working Endpoints (No Auth Required)
- `POST /v0/open-and-issuing-mining-rounds` ✓
- `GET /v0/closed-rounds` ✓
- `GET /v0/ans-entries` ✓

### Restricted Endpoints (May Require Auth)
- `GET /v0/admin/validator/licenses` ⚠️ (admin only)
- `POST /v2/updates` ⚠️ (may be empty or restricted)
- `POST /v0/events` ⚠️ (may be empty or restricted)
- `GET /v0/dso` ⚠️ (may be restricted)

### Alternative Endpoints to Try
- `GET /v0/top-validators-by-validator-faucets` (public)
- Consider using ACS (Active Contract Set) queries if available

## Common Error Messages

### `403 Forbidden`
- **Cause**: Endpoint requires authentication or admin privileges
- **Fix**: Obtain API credentials from your network administrator

### `ProxyError: Tunnel connection failed`
- **Cause**: Network firewall or proxy blocking the request
- **Fix**: Check firewall rules or run from a different network

### `Empty list returned`
- **Cause**: Ledger has no data yet, or filters exclude all results
- **Fix**: Wait for network activity, or check filter parameters

## Next Steps

1. **For Authentication Issues**: Contact your Splice network administrator for API credentials
2. **For Empty Data**: Verify the network has activity (check block explorer)
3. **For Network Issues**: Check firewall/proxy settings

## Additional Notes

- The diagnostic script provides the most detailed information
- All three scripts use the same `canton_scan_client.py` client
- Check the API documentation for your specific Splice network deployment
- Some endpoints may behave differently in testnet vs. mainnet

## Files in This Package

- `splice_analytics.py` - Main analytics script (IMPROVED with better errors)
- `splice_analytics_debug.py` - Comprehensive diagnostic tool (NEW)
- `test_endpoints.py` - Basic endpoint tests
- `test_alternative_endpoints.py` - Alternative endpoint tests
- `canton_scan_client.py` - API client library
- `ANALYTICS_DIAGNOSTIC_README.md` - This file
