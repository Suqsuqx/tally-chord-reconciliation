#!/usr/bin/env python3
"""Redacted integration configuration preflight. No secrets printed."""
import os
import sys
from urllib.parse import urlparse

def main():
    env = os.environ
    checks = [("Sandbox environment", env.get("TALLY_ENV", "sandbox") == "sandbox")]
    if env.get("PAYSTACK_ENABLE_TEST_WEBHOOK", "false").lower() == "true":
        checks.extend([
            ("Paystack modern signing secret", env.get("PAYSTACK_WEBHOOK_SIGNING_SECRET", "").startswith("whsec_")),
            ("Paystack merchant ID mapping", bool(env.get("PAYSTACK_TEST_BUSINESS_ID", ""))),
        ])
    api_key = env.get("PAYSTACK_RESTRICTED_TEST_KEY", "")
    if api_key:
        checks.append(("Paystack test restricted key", api_key.startswith("rk_test_")))
    if env.get("PAYSTACK_ALLOW_LEGACY_SIGNATURE", "false").lower() == "true":
        checks.append(("Legacy test secret", env.get("PAYSTACK_LEGACY_SECRET_KEY", "").startswith("sk_test_")))
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
