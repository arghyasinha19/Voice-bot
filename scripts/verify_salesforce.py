"""
scripts/verify_salesforce.py
-----------------------------
Smoke-test: authenticate via OAuth 2.0 and create a test Lead record.
"""
import asyncio
import os
import sys

from dotenv import load_dotenv

# UTF-8 stdout on Windows
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# Make src importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.salesforce.client import SalesforceClient, SalesforceAPIError, SalesforceAuthError


async def verify():
    load_dotenv()

    print("=" * 55)
    print("  SALESFORCE OAUTH 2.0 INTEGRATION TEST")
    print("=" * 55)

    # Show which credentials are present (never print secrets)
    for key in ("SF_INSTANCE_URL", "SF_CLIENT_ID", "SF_USERNAME", "SF_API_VERSION"):
        val = os.getenv(key, "<NOT SET>")
        print(f"  {key}: {val}")
    print(f"  SF_CLIENT_SECRET: {'✅ set' if os.getenv('SF_CLIENT_SECRET') else '❌ missing'}")
    print(f"  SF_PASSWORD:      {'✅ set' if os.getenv('SF_PASSWORD') else '❌ missing'}")
    print()

    try:
        client = SalesforceClient()
    except SalesforceAuthError as e:
        print(f"❌ Config error: {e}")
        return

    import random
    suffix = random.randint(1000, 9999)
    test_lead = {
        "FirstName": "Maya",
        "LastName":  f"OAuth-Test-{suffix}",
        "Company":   "Maya Voice Bot Testing",
        "Email":     f"maya_oauth_{suffix}@example.com",
        "Phone":     "+91-98765-00000",
        "Description": "Automated OAuth 2.0 verification — Maya Voice Bot.",
        "LeadSource": "Web",
        "Status":    "Open - Not Contacted",
    }

    print(f"Attempting to create test Lead: {test_lead['FirstName']} {test_lead['LastName']}")
    print(f"Target instance: {os.getenv('SF_INSTANCE_URL')}")
    print()

    try:
        response = await client.create_record("Lead", test_lead)
        if response.success:
            print(f"✅ Success! Created Lead ID: {response.record_id}")
            print("   OAuth token minted and Lead creation verified.")
        else:
            print(f"❌ Unexpected failure: {response.errors}")

    except SalesforceAuthError as e:
        print(f"❌ Auth Error: {e}")
        print()
        print("Troubleshooting checklist:")
        print("  1. SF_USERNAME   — is it your exact Salesforce login email?")
        print("  2. SF_PASSWORD   — password + Security Token (no space), e.g. MyPass1AbcXyzToken")
        print("  3. SF_CLIENT_ID  — Connected App Consumer Key")
        print("  4. SF_CLIENT_SECRET — Connected App Consumer Secret")
        print("  5. Connected App → OAuth Policies → Permitted Users = 'All users may self-authorize'")
        print("  6. Connected App → OAuth Scopes includes 'api' and 'refresh_token'")

    except SalesforceAPIError as e:
        print(f"❌ API Error ({e.status_code}): {e.error_code} — {e.message}")

    except Exception as e:
        print(f"❌ Unexpected Error: {type(e).__name__}: {e}")


if __name__ == "__main__":
    asyncio.run(verify())
