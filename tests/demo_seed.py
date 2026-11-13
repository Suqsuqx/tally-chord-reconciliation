"""Isolated legacy regression data. Production modules never import this fixture."""

from server.business import now
from server.db import tx


DEMO_BUSINESS_ID = "test-merchant-fixture"


def seed_demo():
    with tx() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO businesses VALUES(?,?,?)",
            (DEMO_BUSINESS_ID, "Test Merchant Fixture", "NGN"),
        )
        timestamp = now()
        conn.execute(
            """INSERT OR IGNORE INTO business_settings
               (business_id,shop_slug,onboarding_status,profile_json,policies_json,payment_method,
                bank_details_json,created_at,updated_at)
               VALUES(?,?,?,'{}','[]',NULL,NULL,?,?)""",
            (DEMO_BUSINESS_ID, "test-merchant-fixture", "active", timestamp, timestamp),
        )
        for actor in (
            ("cust-ada", "customer", "customer", "Ada (test customer)"),
            ("cust-bola", "customer", "customer", "Bola (test customer)"),
            ("staff-eni", "staff", "admin", "Eni (test Admin)"),
            ("staff-tola", "staff", "operator", "Tola (test Operator)"),
            ("staff-femi", "staff", "operator", "Femi (test Operator)"),
        ):
            conn.execute(
                "INSERT OR IGNORE INTO actors (id,business_id,kind,role,display_name) VALUES(?,?,?,?,?)",
                (actor[0], DEMO_BUSINESS_ID, actor[1], actor[2], actor[3]),
            )
        for item in (
            ("cup-choc", "Chocolate cupcake", 250000, 14, 3),
            ("cup-vanilla", "Vanilla cupcake", 200000, 0, 3),
            ("brownie", "Brownie box", 650000, 5, 2),
        ):
            conn.execute(
                """INSERT OR IGNORE INTO products
                   (id,business_id,name,price_minor,stock_on_hand,stock_reserved,
                    low_stock_threshold,active,updated_at)
                   VALUES(?,?,?,?,?,0,?,1,?)""",
                (item[0], DEMO_BUSINESS_ID, item[1], item[2], item[3], item[4], now()),
            )
