"""Back up Tally's sandbox ledger, trash Tally-owned Notion pages, and empty it.

Run only while tally.service is stopped. Notion pages moved to Trash are
recoverable in Notion. Merchant-authored source pages and selected parents are
never targeted.
"""
import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from server.db import SCHEMA, db_path
from server.notion_connections import trash_managed_notion_pages_for_business


CONFIRMATION = "RESET TALLY RECORDING"


def _database_summary(path):
    with sqlite3.connect(path) as conn:
        tables = [row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )]
        if "businesses" not in tables:
            raise RuntimeError("The selected file is not a Tally database")
        counts = {table: conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                  for table in tables}
        workspace_businesses = {row[0] for row in conn.execute(
            "SELECT business_id FROM notion_workspaces")}
        record_businesses = {row[0] for row in conn.execute(
            "SELECT DISTINCT business_id FROM notion_records")}
        managed_businesses = set()
        for business_id, metadata_json in conn.execute(
                "SELECT business_id,metadata_json FROM provider_resources WHERE provider='notion'"):
            try:
                metadata = json.loads(metadata_json or "{}")
            except ValueError:
                metadata = {}
            if metadata.get("managed_by") == "tally":
                managed_businesses.add(business_id)
        notion_businesses = workspace_businesses | record_businesses | managed_businesses
    # Workspace sections may also be in provider_resources; count unique IDs
    # below for the user-facing preview rather than double-counting them.
    with sqlite3.connect(path) as conn:
        owned_ids = set(row[0] for row in conn.execute(
            "SELECT notion_page_id FROM notion_records WHERE notion_page_id IS NOT NULL"))
        for row in conn.execute("""SELECT profile_page_id,catalogue_page_id,policies_page_id,
                                  orders_page_id,activity_page_id FROM notion_workspaces"""):
            owned_ids.update(value for value in row if value)
        for resource_id, metadata_json in conn.execute(
                "SELECT resource_id,metadata_json FROM provider_resources WHERE provider='notion'"):
            try:
                metadata = json.loads(metadata_json or "{}")
            except ValueError:
                metadata = {}
            if metadata.get("managed_by") == "tally":
                owned_ids.add(resource_id)
    return {
        "tables": tables,
        "counts": counts,
        "notion_business_ids": sorted(notion_businesses),
        "managed_page_count": len(owned_ids),
    }


def _require_service_stopped(service_name):
    systemctl = shutil.which("systemctl")
    if systemctl is None:
        raise RuntimeError("systemctl is required to confirm the service is stopped")
    result = subprocess.run([systemctl, "is-active", service_name],
                            check=False, capture_output=True, text=True, timeout=10)
    if result.returncode == 0 and result.stdout.strip() == "active":
        raise RuntimeError(f"Stop {service_name} before resetting the database")


def _backup_database(source_path, backup_dir):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination_dir = backup_dir / f"{stamp}-pre-recording-reset"
    destination_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    os.chmod(destination_dir, 0o700)
    backup = destination_dir / "tally.db"
    with sqlite3.connect(source_path) as source, sqlite3.connect(backup) as target:
        source.backup(target)
    with sqlite3.connect(backup) as conn:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        raise RuntimeError("The database backup failed its integrity check")
    os.chmod(backup, 0o600)
    return backup


def _replace_with_empty_schema(live_path):
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{live_path.name}.fresh-",
                                              suffix=".db", dir=live_path.parent)
    os.close(descriptor)
    temp_path = Path(temp_name)
    try:
        with sqlite3.connect(temp_path) as conn:
            conn.execute("PRAGMA journal_mode=DELETE")
            conn.executescript(SCHEMA)
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            empty_tables = [row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            nonempty = {table: conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                        for table in empty_tables}
        if integrity != "ok" or any(nonempty.values()):
            raise RuntimeError("The empty database schema failed validation")
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, live_path)
        for suffix in ("-wal", "-shm"):
            sidecar = Path(str(live_path) + suffix)
            if sidecar.exists():
                sidecar.unlink()
        with sqlite3.connect(live_path) as conn:
            live_integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            live_tables = [row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            live_counts = {table: conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                           for table in live_tables}
        if live_integrity != "ok" or any(live_counts.values()):
            raise RuntimeError("The reset database failed its post-replacement validation")
        return len(live_tables), live_integrity
    finally:
        if temp_path.exists():
            temp_path.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true",
                        help="perform the reset; without this option, show a dry run")
    parser.add_argument("--confirm", default="",
                        help=f"required exact confirmation: {CONFIRMATION}")
    parser.add_argument("--service-name", default="tally.service")
    parser.add_argument("--backup-dir", type=Path, default=None)
    args = parser.parse_args()

    if os.getenv("TALLY_ENV", "").lower() != "sandbox":
        raise RuntimeError("Recording reset is allowed only when TALLY_ENV=sandbox")
    live_path = db_path().resolve()
    if not live_path.is_file():
        raise RuntimeError(f"Tally database does not exist: {live_path}")
    summary = _database_summary(live_path)
    report = {
        "mode": "execute" if args.execute else "dry_run",
        "database": str(live_path),
        "merchant_count": summary["counts"].get("businesses", 0),
        "notion_business_count": len(summary["notion_business_ids"]),
        "tally_owned_notion_pages": summary["managed_page_count"],
        "table_count": len(summary["tables"]),
    }
    if not args.execute:
        print(json.dumps(report, sort_keys=True))
        return
    if args.confirm != CONFIRMATION:
        raise RuntimeError(f"Pass --confirm '{CONFIRMATION}' to execute")
    _require_service_stopped(args.service_name)
    if live_path.stat().st_size == 0:
        raise RuntimeError("Refusing to reset an empty or invalid database file")

    backup_dir = args.backup_dir or (live_path.parent.parent / "backups")
    backup = _backup_database(live_path, backup_dir)
    report["backup"] = str(backup)
    report["backup_integrity"] = "ok"

    pages_trashed = 0
    # Archive remote pages first. If Notion rejects any page, keep the local
    # database and connection intact so the cleanup can be retried safely.
    for business_id in summary["notion_business_ids"]:
        cleanup = trash_managed_notion_pages_for_business(business_id)
        pages_trashed += cleanup["trashed_pages"]
    report["tally_owned_notion_pages_trashed"] = pages_trashed

    table_count, integrity = _replace_with_empty_schema(live_path)
    report.update({"reset": True, "table_count": table_count, "live_integrity": integrity})
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"reset": False, "error": str(exc)}, sort_keys=True))
        raise SystemExit(1)
