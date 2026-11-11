#!/usr/bin/env python3
"""Redacted integration configuration preflight. No secrets printed."""
import base64
import os
import sys
from urllib.parse import urlparse

def main():
    env = os.environ
    checks = [("Sandbox environment", env.get("TALLY_ENV", "sandbox") == "sandbox")]
    if env.get("TALLY_PAYSTACK_CONNECTIONS_ENABLED", "false").lower() == "true":
        encoded = env.get("TALLY_CREDENTIAL_ENCRYPTION_KEY", "")
        try:
            valid_encryption_key = len(base64.urlsafe_b64decode(encoded.encode())) == 32
        except (ValueError,TypeError):
            valid_encryption_key = False
        checks.extend([
            ("Merchant credential encryption key", valid_encryption_key),
            ("Credential encryption key version", bool(env.get("TALLY_CREDENTIAL_ENCRYPTION_KEY_VERSION", ""))),
        ])
    if env.get("NOTION_CLIENT_ID") or env.get("NOTION_CLIENT_SECRET"):
        checks.append(("Notion client pair", bool(env.get("NOTION_CLIENT_ID") and env.get("NOTION_CLIENT_SECRET"))))
    redirect = env.get("NOTION_OAUTH_REDIRECT_URI", "")
    if redirect:
        parsed = urlparse(redirect)
        checks.append(("Notion redirect HTTPS", parsed.scheme == "https" and bool(parsed.netloc)))
    for name, passed in checks:
        print(("PASS" if passed else "FAIL") + ": " + name)
    return 0 if all(passed for _, passed in checks) else 1

if __name__ == "__main__":
    sys.exit(main())
