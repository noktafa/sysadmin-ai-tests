#!/usr/bin/env python3
"""Delete all DigitalOcean snapshots listed in infra/snapshots.json.

Usage:
    python scripts/delete_snapshots.py              # delete + remove JSON
    python scripts/delete_snapshots.py --dry-run    # list only, no delete
"""

import argparse
import json
import os
import sys

import digitalocean

SNAPSHOTS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "infra", "snapshots.json",
)


def main():
    parser = argparse.ArgumentParser(
        description="Delete sysadmin-ai test snapshots from DigitalOcean."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="List snapshots only; do not delete.",
    )
    args = parser.parse_args()

    token = os.environ.get("DIGITALOCEAN_TOKEN")
    if not token:
        print("Error: DIGITALOCEAN_TOKEN environment variable not set.", file=sys.stderr)
        sys.exit(1)

    if not os.path.exists(SNAPSHOTS_PATH):
        print(f"No snapshots.json found at {SNAPSHOTS_PATH}")
        print("Nothing to delete.")
        return

    with open(SNAPSHOTS_PATH) as f:
        snapshots = json.load(f)

    if not snapshots:
        print("snapshots.json is empty. Nothing to delete.")
        return

    print(f"Snapshots to delete ({len(snapshots)}):")
    for name, info in sorted(snapshots.items()):
        print(f"  - {name}: snapshot_id={info['snapshot_id']} (base: {info['base_image']}, built: {info['built_at']})")

    if args.dry_run:
        print("\n--dry-run: no snapshots deleted.")
        return

    deleted = 0
    failed = 0
    for name, info in snapshots.items():
        sid = info["snapshot_id"]
        try:
            snap = digitalocean.Snapshot.get_object(api_token=token, snapshot_id=str(sid))
            snap.destroy()
            print(f"  Deleted {name} (snapshot_id={sid})")
            deleted += 1
        except digitalocean.NotFoundError:
            print(f"  {name} (snapshot_id={sid}) — already deleted or not found")
            deleted += 1  # count as success since it's gone
        except Exception as exc:
            print(f"  Failed to delete {name} (snapshot_id={sid}): {exc}")
            failed += 1

    # Remove the JSON file
    try:
        os.remove(SNAPSHOTS_PATH)
        print(f"\nRemoved {SNAPSHOTS_PATH}")
    except Exception as exc:
        print(f"\nWarning: could not remove {SNAPSHOTS_PATH}: {exc}")

    print(f"\nDone: {deleted} deleted, {failed} failed.")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
