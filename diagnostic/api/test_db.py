"""Quick test — verify Supabase connection via REST API.

Usage:  python3 test_db.py
Delete this file after verifying.
"""

import asyncio
import os

os.environ.setdefault("SUPABASE_URL", "https://jfpeamjbhaqnbupkrcgb.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImpmcGVhbWpiaGFxbmJ1cGtyY2diIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3MzA0NTk1NCwiZXhwIjoyMDg4NjIxOTU0fQ.PVvw0VhODLsJRifycdnlHEce6kFRvlLsCTeDqsc6LlU")

import db


async def main():
    print("Connecting to Supabase REST API...")
    await db.init_pool()

    print("\n1. Testing messages table...")
    msg_id = await db.insert_message("Test Bot", "test@whiterabbit.com.py", "Mensaje de prueba")
    print(f"   Inserted message ID: {msg_id}")

    messages = await db.list_messages()
    print(f"   Total messages: {len(messages)}")

    print("\n2. Testing diagnostics table...")
    diag_id = await db.insert_diagnostic(
        url="https://www.whiterabbit.com.py",
        health_score=85,
        report={"health_score": 85, "summary": "Test report"},
        crawl_summary="Test crawl",
    )
    print(f"   Inserted diagnostic ID: {diag_id}")

    print("\n3. Testing leads table...")
    lead_id = await db.upsert_lead(email="test@whiterabbit.com.py", name="Test Lead", source="diagnostic")
    print(f"   Upserted lead ID: {lead_id}")

    await db.add_lead_event(lead_id, "diagnostic_run", {"url": "https://test.com"})
    print("   Added lead event")

    print("\n4. Testing email_captures table...")
    cap_id = await db.capture_email(email="test@whiterabbit.com.py", url_diagnosed="https://test.com")
    print(f"   Captured email ID: {cap_id}")

    print("\n5. Testing stats...")
    stats = await db.get_stats()
    print(f"   Stats: {stats}")

    print("\n6. Cleanup — deleting test data...")
    c = db._get_client()
    await c.delete(f"/lead_events?lead_id=eq.{lead_id}")
    await c.delete(f"/email_captures?id=eq.{cap_id}")
    await c.delete(f"/leads?id=eq.{lead_id}")
    await c.delete(f"/diagnostics?id=eq.{diag_id}")
    await c.delete(f"/messages?id=eq.{msg_id}")
    print("   Test data cleaned up")

    await db.close_pool()
    print("\n ALL TESTS PASSED!")


if __name__ == "__main__":
    asyncio.run(main())
