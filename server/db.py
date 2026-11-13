"""Tally's sandbox SQLite storage. Connections are short-lived and transactional."""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS businesses (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, currency TEXT NOT NULL DEFAULT 'NGN'
);
CREATE TABLE IF NOT EXISTS business_settings (
 business_id TEXT PRIMARY KEY, shop_slug TEXT NOT NULL UNIQUE,
 onboarding_status TEXT NOT NULL DEFAULT 'onboarding',
 profile_json TEXT NOT NULL DEFAULT '{}', policies_json TEXT NOT NULL DEFAULT '[]',
 payment_method TEXT, bank_details_json TEXT,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS channel_identities (
 channel TEXT NOT NULL, identity_hash TEXT NOT NULL, business_id TEXT NOT NULL,
 actor_id TEXT NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(channel,identity_hash,business_id), UNIQUE(actor_id)
);
CREATE TABLE IF NOT EXISTS actors (
 id TEXT PRIMARY KEY, business_id TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('customer','staff')),
 role TEXT NOT NULL CHECK(role IN ('customer','admin','operator')), display_name TEXT NOT NULL,
 email TEXT,
 active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS access_codes (
 code_hash TEXT PRIMARY KEY, actor_id TEXT NOT NULL, expires_at TEXT NOT NULL, used_at TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
 token_hash TEXT PRIMARY KEY, actor_id TEXT NOT NULL, expires_at TEXT NOT NULL,
 issued_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS products (
 id TEXT PRIMARY KEY, business_id TEXT NOT NULL, name TEXT NOT NULL,
 price_minor INTEGER NOT NULL CHECK(price_minor>=0), currency TEXT NOT NULL DEFAULT 'NGN',
 stock_on_hand INTEGER NOT NULL CHECK(stock_on_hand>=0), stock_reserved INTEGER NOT NULL DEFAULT 0 CHECK(stock_reserved>=0),
 low_stock_threshold INTEGER NOT NULL DEFAULT 3 CHECK(low_stock_threshold>=0), active INTEGER NOT NULL DEFAULT 1,
 updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS products_name_by_business ON products(business_id, name COLLATE NOCASE);
CREATE TABLE IF NOT EXISTS orders (
 id TEXT PRIMARY KEY, business_id TEXT NOT NULL, customer_id TEXT NOT NULL,
 total_minor INTEGER NOT NULL, currency TEXT NOT NULL, status TEXT NOT NULL,
 idempotency_key TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS order_idempotency ON orders(business_id,customer_id,idempotency_key);
CREATE TABLE IF NOT EXISTS order_items (
 order_id TEXT NOT NULL, product_id TEXT NOT NULL, name TEXT NOT NULL,
 qty INTEGER NOT NULL CHECK(qty>0), price_minor INTEGER NOT NULL, PRIMARY KEY(order_id,product_id)
);
CREATE TABLE IF NOT EXISTS payment_claims (
 id TEXT PRIMARY KEY, order_id TEXT NOT NULL, actor_id TEXT NOT NULL,
 note TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS payment_events (
 event_id TEXT PRIMARY KEY, business_id TEXT NOT NULL, reference TEXT NOT NULL,
 amount_minor INTEGER NOT NULL, currency TEXT NOT NULL,
 event_status TEXT NOT NULL, match_status TEXT NOT NULL, order_id TEXT,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS inventory_adjustments (
 id TEXT PRIMARY KEY, business_id TEXT NOT NULL, product_id TEXT NOT NULL,
 before_qty INTEGER NOT NULL, after_qty INTEGER NOT NULL, reason TEXT NOT NULL,
 actor_id TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS support_cases (
 id TEXT PRIMARY KEY, business_id TEXT NOT NULL, customer_id TEXT NOT NULL,
 order_id TEXT, category TEXT NOT NULL CHECK(category IN ('complaint','inquiry')),
 status TEXT NOT NULL DEFAULT 'open', opened_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 last_staff_response_at TEXT
);
CREATE TABLE IF NOT EXISTS support_messages (
 id TEXT PRIMARY KEY, case_id TEXT NOT NULL, sender_actor_id TEXT NOT NULL,
 sender_kind TEXT NOT NULL, body TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS customer_notifications (
 id TEXT PRIMARY KEY, business_id TEXT NOT NULL, customer_id TEXT NOT NULL,
 order_id TEXT NOT NULL, kind TEXT NOT NULL, message TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL, resolved_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS customer_notification_per_order
 ON customer_notifications(customer_id,order_id,kind);
CREATE TABLE IF NOT EXISTS audit (
 id TEXT PRIMARY KEY, business_id TEXT NOT NULL, actor_id TEXT NOT NULL,
 action TEXT NOT NULL, target_id TEXT, detail TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS provider_setup_sessions (
 token_hash TEXT PRIMARY KEY, business_id TEXT NOT NULL, actor_id TEXT NOT NULL,
 provider TEXT NOT NULL, expires_at TEXT NOT NULL, used_at TEXT
);
CREATE TABLE IF NOT EXISTS provider_oauth_states (
 state_hash TEXT PRIMARY KEY, business_id TEXT NOT NULL, actor_id TEXT NOT NULL,
 provider TEXT NOT NULL, expires_at TEXT NOT NULL, used_at TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS provider_connections (
 id TEXT PRIMARY KEY, business_id TEXT NOT NULL, provider TEXT NOT NULL,
 environment TEXT NOT NULL, credentials_ciphertext TEXT NOT NULL,
 key_version TEXT NOT NULL, permissions_json TEXT NOT NULL,
 provider_account_ref TEXT, status TEXT NOT NULL,
 verified_at TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 revoked_at TEXT,
 UNIQUE(business_id,provider,environment)
);
CREATE TABLE IF NOT EXISTS payment_provider_references (
 provider TEXT NOT NULL, environment TEXT NOT NULL, business_id TEXT NOT NULL,
 connection_id TEXT NOT NULL, order_id TEXT NOT NULL, provider_reference TEXT NOT NULL,
 created_at TEXT NOT NULL, checkout_url TEXT, access_code TEXT,
 status TEXT NOT NULL DEFAULT 'initialized',
 PRIMARY KEY(provider,environment,connection_id,provider_reference),
 UNIQUE(provider,environment,connection_id,order_id)
);
CREATE TABLE IF NOT EXISTS provider_resources (
 connection_id TEXT NOT NULL, business_id TEXT NOT NULL, provider TEXT NOT NULL,
 resource_id TEXT NOT NULL, resource_type TEXT NOT NULL, title TEXT NOT NULL,
 metadata_json TEXT NOT NULL DEFAULT '{}', discovered_at TEXT NOT NULL,
 PRIMARY KEY(connection_id,resource_id)
);
CREATE TABLE IF NOT EXISTS notion_workspaces (
 business_id TEXT PRIMARY KEY, connection_id TEXT NOT NULL, parent_page_id TEXT NOT NULL,
 profile_page_id TEXT NOT NULL, catalogue_page_id TEXT NOT NULL, policies_page_id TEXT NOT NULL,
 orders_page_id TEXT NOT NULL, activity_page_id TEXT NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS notion_records (
 business_id TEXT NOT NULL, record_type TEXT NOT NULL, record_id TEXT NOT NULL,
 notion_page_id TEXT NOT NULL, updated_at TEXT NOT NULL,
 PRIMARY KEY(business_id,record_type,record_id)
);
"""

def db_path():
    return Path(os.getenv('TALLY_DB_PATH', './data/tally.db'))

def init_db():
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.executescript(SCHEMA)
        # Additive compatibility for databases created before provider checkout
        # metadata was introduced. Never rebuild or discard an existing table.
        existing = {row[1] for row in conn.execute('PRAGMA table_info(payment_provider_references)')}
        for name, declaration in (
            ('checkout_url', 'TEXT'),
            ('access_code', 'TEXT'),
            ('status', "TEXT NOT NULL DEFAULT 'initialized'"),
        ):
            if name not in existing:
                conn.execute(f'ALTER TABLE payment_provider_references ADD COLUMN {name} {declaration}')
        actor_columns = {row[1] for row in conn.execute('PRAGMA table_info(actors)')}
        if 'email' not in actor_columns:
            conn.execute('ALTER TABLE actors ADD COLUMN email TEXT')

@contextmanager
def tx():
    init_db()
    conn = sqlite3.connect(db_path(), isolation_level=None, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('BEGIN IMMEDIATE')
    try:
        yield conn
        conn.execute('COMMIT')
    except Exception:
        conn.execute('ROLLBACK')
        raise
    finally:
        conn.close()

def rowdict(row):
    return dict(row) if row is not None else None
