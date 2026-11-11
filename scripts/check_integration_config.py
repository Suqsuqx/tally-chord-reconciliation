#!/usr/bin/env python3
"""Redacted integration configuration preflight. No secrets printed."""
import base64
import os
import sys
from urllib.parse import urlparse

def main():
    env = os.environ
    checks = [("Sandbox environment", env.get("TALLY_ENV", "sandbox") == "sandbox")]
    provider_connections_enabled = any(
        env.get(name, "false").lower() == "true"
        for name in ("TALLY_PAYSTACK_CONNECTIONS_ENABLED", "TALLY_NOTION_CONNECTIONS_ENABLED")
    )
    if provider_connections_enabled:
        encoded = env.get("TALLY_CREDENTIAL_ENCRYPTION_KEY", "")
        try:
            valid_encryption_key = len(base64.urlsafe_b64decode(encoded.encode())) == 32
        except (ValueError,TypeError):
            valid_encryption_key = False
        checks.extend([
            ("Merchant credential encryption key", valid_encryption_key),
            ("Credential encryption key version", bool(env.get("TALLY_CREDENTIAL_ENCRYPTION_KEY_VERSION", ""))),
        ])
    if env.get("TALLY_NOTION_CONNECTIONS_ENABLED", "false").lower() == "true":
        checks.append(("Notion client pair", bool(env.get("NOTION_CLIENT_ID") and env.get("NOTION_CLIENT_SECRET"))))
        redirect = env.get("NOTION_OAUTH_REDIRECT_URI", "")
        parsed = urlparse(redirect)
        checks.append(("Notion redirect HTTPS", parsed.scheme == "https" and bool(parsed.netloc)))
        checks.append(("Notion API version", bool(env.get("NOTION_API_VERSION", ""))))
    for name, passed in checks:
        print(("PASS" if passed else "FAIL") + ": " + name)
    return 0 if all(passed for _, passed in checks) else 1

if __name__ == "__main__":
    sys.exit(main())
