"""
Cognito Pre sign-up trigger: allowlist for federated (Google) sign-ins.

Without this, anyone with a Google account could sign in and run triage
(every triage spends Bedrock tokens). Fires the first time a federated user
signs in; raising an exception blocks that sign-in with an error on the
Hosted UI. Users created by an admin (PreSignUp_AdminCreateUser) and native
sign-ups are passed through untouched - the pool already blocks self sign-up.

ALLOWED_EMAILS / ALLOWED_DOMAINS are comma-separated, set from Terraform.
An empty allowlist (both empty) denies everyone, i.e. fails closed.
"""

import os


def _split(name):
    return {v.strip().lower() for v in os.environ.get(name, "").split(",") if v.strip()}


def handler(event, context):
    if event.get("triggerSource") != "PreSignUp_ExternalProvider":
        return event

    attrs = event["request"].get("userAttributes", {})
    email = (attrs.get("email") or "").strip().lower()
    verified = str(attrs.get("email_verified", "")).lower() == "true"

    allowed_emails = _split("ALLOWED_EMAILS")
    allowed_domains = _split("ALLOWED_DOMAINS")
    domain = email.rsplit("@", 1)[-1] if "@" in email else ""

    if email and verified and (email in allowed_emails or domain in allowed_domains):
        return event

    # Logged so a denial is diagnosable from CloudWatch (which check failed).
    print(f"DENIED federated sign-up: email={email!r} verified={verified} "
          f"in_allowed_emails={email in allowed_emails} in_allowed_domains={domain in allowed_domains}")

    raise Exception("This account is not authorised to use ClaimPilot.")
