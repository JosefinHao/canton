"""
JWT Helper Utilities for Canton Network Scan API

This module provides utilities for working with JWT tokens for authentication.
"""

import json
import base64
from datetime import datetime, timedelta
from typing import Dict, Any, Optional


def decode_jwt_payload(token: str) -> Dict[str, Any]:
    """
    Decode the payload of a JWT token (without verification).

    Args:
        token: JWT token string

    Returns:
        Decoded payload as dictionary

    Note:
        This function does NOT verify the token signature.
        Use only for inspection purposes.
    """
    try:
        # Split token into parts
        parts = token.split('.')

        if len(parts) != 3:
            raise ValueError("Invalid JWT format")

        # Decode payload (second part)
        payload_encoded = parts[1]

        # Add padding if needed
        padding = 4 - (len(payload_encoded) % 4)
        if padding != 4:
            payload_encoded += '=' * padding

        # Decode base64
        payload_bytes = base64.urlsafe_b64decode(payload_encoded)
        payload = json.loads(payload_bytes)

        return payload

    except Exception as e:
        raise ValueError(f"Failed to decode JWT: {e}")


def inspect_jwt_token(token: str) -> Dict[str, Any]:
    """
    Inspect a JWT token and return its details.

    Args:
        token: JWT token string

    Returns:
        Dictionary with token details including claims and expiry info
    """
    payload = decode_jwt_payload(token)

    # Extract common claims
    subject = payload.get('sub')
    audience = payload.get('aud')
    issued_at = payload.get('iat')
    expires_at = payload.get('exp')
    issuer = payload.get('iss')

    # Calculate expiry information
    expiry_info = {}
    if expires_at:
        expiry_datetime = datetime.fromtimestamp(expires_at)
        now = datetime.utcnow()
        time_to_expiry = expiry_datetime - now

        expiry_info = {
            'expires_at': expiry_datetime.isoformat(),
            'is_expired': now > expiry_datetime,
            'time_to_expiry_seconds': time_to_expiry.total_seconds(),
            'time_to_expiry_hours': time_to_expiry.total_seconds() / 3600
        }

    # Build inspection result
    inspection = {
        'subject': subject,
        'audience': audience,
        'issuer': issuer,
        'issued_at': datetime.fromtimestamp(issued_at).isoformat() if issued_at else None,
        'expiry': expiry_info,
        'all_claims': payload
    }

    return inspection


def validate_token_claims(
    token: str,
    expected_audience: Optional[str] = None,
    expected_subject: Optional[str] = None
) -> Dict[str, Any]:
    """
    Validate JWT token claims.

    Args:
        token: JWT token string
        expected_audience: Expected audience value (optional)
        expected_subject: Expected subject value (optional)

    Returns:
        Dictionary with validation results

    Note:
        This function does NOT verify the token signature.
        Use only for basic claim validation.
    """
    try:
        payload = decode_jwt_payload(token)
        errors = []
        warnings = []

        # Check required claims
        if 'sub' not in payload:
            errors.append("Missing required claim: 'sub' (subject)")
        elif expected_subject and payload['sub'] != expected_subject:
            errors.append(f"Subject mismatch: expected '{expected_subject}', got '{payload['sub']}'")

        if 'aud' not in payload:
            errors.append("Missing required claim: 'aud' (audience)")
        elif expected_audience and payload['aud'] != expected_audience:
            errors.append(f"Audience mismatch: expected '{expected_audience}', got '{payload['aud']}'")

        # Check expiry
        if 'exp' in payload:
            expires_at = datetime.fromtimestamp(payload['exp'])
            now = datetime.utcnow()

            if now > expires_at:
                errors.append(f"Token expired at {expires_at.isoformat()}")
            else:
                time_to_expiry = expires_at - now
                if time_to_expiry.total_seconds() < 3600:  # Less than 1 hour
                    warnings.append(f"Token expires soon: {expires_at.isoformat()}")
        else:
            warnings.append("No expiry claim found (token may not expire)")

        # Build validation result
        validation = {
            'valid': len(errors) == 0,
            'errors': errors,
            'warnings': warnings,
            'claims': payload
        }

        return validation

    except Exception as e:
        return {
            'valid': False,
            'errors': [f"Failed to validate token: {e}"],
            'warnings': [],
            'claims': {}
        }


def format_token_info(inspection: Dict[str, Any]) -> str:
    """
    Format token inspection results as a human-readable string.

    Args:
        inspection: Token inspection dictionary from inspect_jwt_token

    Returns:
        Formatted string
    """
    lines = []
    lines.append("=" * 70)
    lines.append("JWT TOKEN INSPECTION")
    lines.append("=" * 70)

    lines.append(f"\nSubject (ledgerApiUserId): {inspection.get('subject', 'N/A')}")
    lines.append(f"Audience: {inspection.get('audience', 'N/A')}")
    lines.append(f"Issuer: {inspection.get('issuer', 'N/A')}")
    lines.append(f"Issued At: {inspection.get('issued_at', 'N/A')}")

    expiry = inspection.get('expiry', {})
    if expiry:
        lines.append(f"\nExpiry Information:")
        lines.append(f"  Expires At: {expiry.get('expires_at', 'N/A')}")
        lines.append(f"  Is Expired: {expiry.get('is_expired', 'N/A')}")

        if not expiry.get('is_expired'):
            hours = expiry.get('time_to_expiry_hours', 0)
            lines.append(f"  Time to Expiry: {hours:.2f} hours")

    lines.append(f"\nAll Claims:")
    for key, value in inspection.get('all_claims', {}).items():
        lines.append(f"  {key}: {value}")

    lines.append("\n" + "=" * 70)

    return "\n".join(lines)


def main():
    """Example usage of JWT helper utilities."""
    import sys

    if len(sys.argv) < 2:
        print("Usage: python jwt_helper.py <jwt-token>")
        print("\nThis tool helps you inspect JWT tokens for Canton Network Scan API.")
        print("\nExample:")
        print("  python jwt_helper.py eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...")
        sys.exit(1)

    token = sys.argv[1]

    # Inspect token
    print("Inspecting JWT token...\n")
    try:
        inspection = inspect_jwt_token(token)
        print(format_token_info(inspection))

        # Validate token
        print("\nValidating token claims...")
        validation = validate_token_claims(token)

        if validation['valid']:
            print(" Token claims are valid")
        else:
            print(" Token validation failed")

        if validation['errors']:
            print("\nErrors:")
            for error in validation['errors']:
                print(f"  • {error}")

        if validation['warnings']:
            print("\nWarnings:")
            for warning in validation['warnings']:
                print(f"  • {warning}")

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
