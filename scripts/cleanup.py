#!/usr/bin/env python3
"""Emergency cleanup: destroy all test droplets and ephemeral SSH keys.

Usage:
    python scripts/cleanup.py                # list + confirm + destroy
    python scripts/cleanup.py --force        # no confirmation prompt
    python scripts/cleanup.py --dry-run      # list only, no destroy
"""

import argparse
import os
import sys

import digitalocean


TAG = "sysadmin-ai-test"
SSH_KEY_NAME = "sysadmin-ai-test-ephemeral"


def get_tagged_droplets(manager):
    return manager.get_all_droplets(tag_name=TAG)


def get_ephemeral_ssh_keys(manager):
    return [k for k in manager.get_all_sshkeys() if k.name == SSH_KEY_NAME]


def print_resources(droplets, ssh_keys):
    if droplets:
        print(f"\nDroplets tagged '{TAG}' ({len(droplets)}):")
        for d in droplets:
            print(f"  - {d.name}  id={d.id}  ip={d.ip_address}  created={d.created_at}")
    else:
        print(f"\nNo droplets found with tag '{TAG}'.")

    if ssh_keys:
        print(f"\nSSH keys named '{SSH_KEY_NAME}' ({len(ssh_keys)}):")
        for k in ssh_keys:
            print(f"  - id={k.id}  fingerprint={k.fingerprint}")
    else:
        print(f"\nNo SSH keys found named '{SSH_KEY_NAME}'.")


def destroy_resources(droplets, ssh_keys):
    destroyed_droplets = 0
    for d in droplets:
        try:
            d.destroy()
            destroyed_droplets += 1
        except Exception as exc:
            print(f"  Warning: failed to destroy droplet {d.id}: {exc}")

    removed_keys = 0
    for k in ssh_keys:
        try:
            k.destroy()
            removed_keys += 1
        except Exception as exc:
            print(f"  Warning: failed to remove SSH key {k.id}: {exc}")

    return destroyed_droplets, removed_keys


def main():
    parser = argparse.ArgumentParser(
        description="Destroy all sysadmin-ai-test droplets and ephemeral SSH keys."
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Skip confirmation prompt.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="List resources only; do not destroy.",
    )
    args = parser.parse_args()

    token = os.environ.get("DIGITALOCEAN_TOKEN")
    if not token:
        print("Error: DIGITALOCEAN_TOKEN environment variable not set.", file=sys.stderr)
        sys.exit(1)

    manager = digitalocean.Manager(token=token)
    droplets = get_tagged_droplets(manager)
    ssh_keys = get_ephemeral_ssh_keys(manager)

    print_resources(droplets, ssh_keys)

    if not droplets and not ssh_keys:
        print("\nNothing to clean up.")
        return

    if args.dry_run:
        print("\n--dry-run: no resources destroyed.")
        return

    if not args.force:
        answer = input("\nDestroy all listed resources? [y/N] ").strip().lower()
        if answer != "y":
            print("Aborted.")
            return

    print("\nDestroying resources...")
    destroyed_droplets, removed_keys = destroy_resources(droplets, ssh_keys)
    print(f"\nDone: {destroyed_droplets} droplet(s) destroyed, {removed_keys} SSH key(s) removed.")


if __name__ == "__main__":
    main()
