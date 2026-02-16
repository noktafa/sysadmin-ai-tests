#!/usr/bin/env python3
"""Build DigitalOcean snapshots with pre-installed dependencies for faster tests.

Creates one snapshot per OS in the test matrix with python3, pip, and openai
pre-installed. Writes snapshot IDs to infra/snapshots.json.

Usage:
    python scripts/build_snapshots.py              # build all snapshots
    python scripts/build_snapshots.py --force       # rebuild even if snapshots.json exists
    python scripts/build_snapshots.py --dry-run     # show what would be built
"""

import argparse
import json
import os
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import digitalocean

# Allow imports from the project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from infra.droplet_controller import DropletController
from infra.os_matrix import OS_MATRIX
from infra.ssh_driver import SSHDriver, generate_keypair

TAG = "sysadmin-ai-snapshot-build"
SNAPSHOTS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "infra", "snapshots.json",
)
COST_PER_GB_MONTH = 0.06  # DO snapshot pricing: $0.06/GB/month
ESTIMATED_SNAPSHOT_GB = 2.5  # rough estimate per snapshot


def register_ssh_key(token, pub_string):
    """Register an ephemeral SSH key with DigitalOcean. Returns the DO key object."""
    do_key = digitalocean.SSHKey(
        token=token,
        name=f"sysadmin-ai-snapshot-build-{uuid.uuid4().hex[:6]}",
        public_key=pub_string,
    )
    do_key.create()
    return do_key


def build_one_snapshot(os_target, token, private_key, do_key):
    """Build a snapshot for a single OS target. Returns (name, snapshot_info) or raises."""
    controller = DropletController(token=token)
    droplet_id = None
    log_prefix = f"[{os_target.name}]"

    try:
        # 1. Create droplet
        print(f"{log_prefix} Creating droplet from {os_target.image}...")
        info = controller.create(
            image=os_target.image,
            name=f"snap-{os_target.name}-{uuid.uuid4().hex[:4]}",
            ssh_keys=[do_key],
        )
        droplet_id = info["id"]

        # Tag it for identification
        droplet_obj = digitalocean.Droplet(id=droplet_id, token=token)
        try:
            tag = digitalocean.Tag(token=token, name=TAG)
            tag.create()
            tag.add_droplets([str(droplet_id)])
        except Exception:
            pass  # tagging is best-effort

        # 2. Wait for active
        print(f"{log_prefix} Waiting for droplet {droplet_id} to become active...")
        ip = controller.wait_until_ready(droplet_id, timeout=300)
        print(f"{log_prefix} Droplet active at {ip}")

        # 3. Connect via SSH
        print(f"{log_prefix} Connecting via SSH...")
        driver = SSHDriver(host=ip, username=os_target.user, key=private_key)
        driver.connect(timeout=180)

        try:
            # 4. Wait for cloud-init
            print(f"{log_prefix} Waiting for cloud-init...")
            result = driver.run("cloud-init status --wait >/dev/null 2>&1 || true", timeout=300)

            # 5. Run setup commands (apt/dnf install python3 python3-pip)
            for cmd in os_target.setup_commands:
                print(f"{log_prefix} Running: {cmd[:60]}...")
                result = driver.run(cmd, timeout=300)
                if result["exit_code"] != 0:
                    raise RuntimeError(
                        f"Setup command failed on {os_target.name}: {cmd!r}\n"
                        f"stdout: {result['stdout']}\nstderr: {result['stderr']}"
                    )

            # 6. Install openai via pip
            pip_cmd = f"pip3 install {os_target.pip_flags} openai".strip()
            print(f"{log_prefix} Running: {pip_cmd}")
            result = driver.run(pip_cmd, timeout=300)
            if result["exit_code"] != 0:
                raise RuntimeError(
                    f"pip install failed on {os_target.name}:\n"
                    f"stdout: {result['stdout']}\nstderr: {result['stderr']}"
                )

            # 7. Create /opt/sysadmin-ai/ directory
            print(f"{log_prefix} Creating /opt/sysadmin-ai/...")
            result = driver.run("mkdir -p /opt/sysadmin-ai")
            if result["exit_code"] != 0:
                raise RuntimeError(
                    f"mkdir failed on {os_target.name}: {result['stderr']}"
                )

            # 8. Verify python3 and openai are importable
            print(f"{log_prefix} Verifying installation...")
            result = driver.run("python3 -c 'import openai; print(openai.__version__)'")
            if result["exit_code"] != 0:
                raise RuntimeError(
                    f"openai import verification failed on {os_target.name}:\n"
                    f"stderr: {result['stderr']}"
                )
            openai_version = result["stdout"].strip()
            print(f"{log_prefix} openai {openai_version} installed successfully")

        finally:
            driver.close()

        # 9. Power off the droplet
        print(f"{log_prefix} Powering off droplet...")
        droplet_obj.load()
        off_action = droplet_obj.power_off(return_dict=False)
        success = off_action.wait(update_every_seconds=5, repeat=60)
        if not success:
            raise RuntimeError(
                f"Power off failed for {os_target.name}: status={off_action.status}"
            )
        print(f"{log_prefix} Droplet powered off")

        # 10. Take snapshot
        snapshot_name = f"sysadmin-ai-{os_target.name}-{datetime.now(timezone.utc).strftime('%Y%m%d')}"
        print(f"{log_prefix} Taking snapshot '{snapshot_name}'...")
        snap_action = droplet_obj.take_snapshot(snapshot_name, return_dict=False)
        success = snap_action.wait(update_every_seconds=10, repeat=180)  # up to 30 min
        if not success:
            raise RuntimeError(
                f"Snapshot failed for {os_target.name}: status={snap_action.status}"
            )

        # 11. Get snapshot ID
        droplet_obj.load()
        if not droplet_obj.snapshot_ids:
            raise RuntimeError(f"No snapshot IDs found on droplet for {os_target.name}")
        snapshot_id = droplet_obj.snapshot_ids[-1]  # most recent
        print(f"{log_prefix} Snapshot created: id={snapshot_id}")

        # 12. Destroy the droplet
        print(f"{log_prefix} Destroying droplet...")
        controller.destroy(droplet_id)
        droplet_id = None  # mark as cleaned up
        print(f"{log_prefix} Done!")

        return os_target.name, {
            "snapshot_id": snapshot_id,
            "base_image": os_target.image,
            "built_at": datetime.now(timezone.utc).isoformat(),
        }

    except Exception:
        # Cleanup on failure
        if droplet_id is not None:
            try:
                controller.destroy(droplet_id)
                print(f"{log_prefix} Cleaned up droplet after failure")
            except Exception:
                print(f"{log_prefix} WARNING: Failed to clean up droplet {droplet_id}")
        raise


def main():
    parser = argparse.ArgumentParser(
        description="Build DigitalOcean snapshots for sysadmin-ai integration tests."
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Rebuild even if snapshots.json already exists.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be built without creating anything.",
    )
    args = parser.parse_args()

    token = os.environ.get("DIGITALOCEAN_TOKEN")
    if not token:
        print("Error: DIGITALOCEAN_TOKEN environment variable not set.", file=sys.stderr)
        sys.exit(1)

    if os.path.exists(SNAPSHOTS_PATH) and not args.force:
        print(f"snapshots.json already exists at {SNAPSHOTS_PATH}")
        print("Use --force to rebuild, or delete the file first.")
        sys.exit(1)

    targets = list(OS_MATRIX)
    print(f"Building snapshots for {len(targets)} OS targets:")
    for t in targets:
        print(f"  - {t.name} (image: {t.image})")

    if args.dry_run:
        est_cost = len(targets) * ESTIMATED_SNAPSHOT_GB * COST_PER_GB_MONTH
        print(f"\n--dry-run: Would build {len(targets)} snapshots.")
        print(f"Estimated monthly storage cost: ${est_cost:.2f}")
        return

    # Generate ephemeral SSH keypair
    print("\nGenerating ephemeral SSH keypair...")
    private_key, pub_string = generate_keypair()

    # Register with DigitalOcean
    print("Registering SSH key with DigitalOcean...")
    do_key = register_ssh_key(token, pub_string)

    snapshots = {}
    errors = {}
    start_time = time.monotonic()

    try:
        # Build all snapshots in parallel
        print(f"\nStarting parallel build with {len(targets)} workers...\n")
        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = {
                executor.submit(build_one_snapshot, t, token, private_key, do_key): t
                for t in targets
            }

            for future in as_completed(futures):
                target = futures[future]
                try:
                    name, snap_info = future.result()
                    snapshots[name] = snap_info
                except Exception as exc:
                    errors[target.name] = str(exc)
                    print(f"\n[{target.name}] FAILED: {exc}\n")

    finally:
        # Always clean up SSH key
        print("\nCleaning up SSH key...")
        try:
            do_key.destroy()
        except Exception:
            pass

    elapsed = time.monotonic() - start_time

    # Write results
    if snapshots:
        with open(SNAPSHOTS_PATH, "w") as f:
            json.dump(snapshots, f, indent=2)
        print(f"\nWrote {len(snapshots)} snapshot(s) to {SNAPSHOTS_PATH}")

    # Summary
    est_cost = len(snapshots) * ESTIMATED_SNAPSHOT_GB * COST_PER_GB_MONTH
    print(f"\n{'='*60}")
    print(f"Build Summary")
    print(f"{'='*60}")
    print(f"  Elapsed: {elapsed/60:.1f} minutes")
    print(f"  Succeeded: {len(snapshots)}/{len(targets)}")
    if errors:
        print(f"  Failed: {len(errors)}/{len(targets)}")
        for name, err in errors.items():
            print(f"    - {name}: {err[:100]}")
    print(f"  Estimated monthly cost: ${est_cost:.2f}")
    print()
    for name, info in sorted(snapshots.items()):
        print(f"  {name}: snapshot_id={info['snapshot_id']}")

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
