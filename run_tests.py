#!/usr/bin/env python3
"""Cross-platform test runner for sysadmin-ai-tests.

Usage:
    python run_tests.py unit                # Unit tests only
    python run_tests.py integration         # Integration tests, parallel (7 workers)
    python run_tests.py all                 # Both unit and integration
    python run_tests.py [pytest args]       # Pass-through to pytest
"""

import os
import sys

import pytest


def _integration_cleanup():
    """Post-run safety sweep: destroy any leftover test droplets."""
    token = os.environ.get("DIGITALOCEAN_TOKEN")
    if not token:
        return

    try:
        from infra.droplet_controller import DropletController

        controller = DropletController(token=token)
        controller.destroy_all()
        print("\n[run_tests] Global cleanup complete — all tagged droplets destroyed.")
    except Exception as exc:
        print(f"\n[run_tests] Global cleanup error: {exc}", file=sys.stderr)


def _worker_count():
    """Return the number of parallel workers (one per OS target)."""
    from infra.os_matrix import get_all

    return len(get_all())


def main():
    args = sys.argv[1:]

    if not args:
        print(__doc__.strip())
        sys.exit(0)

    mode = args[0] if args else ""

    if mode == "unit":
        exit_code = pytest.main(["tests/", "-m", "not integration"] + args[1:])
        sys.exit(exit_code)

    elif mode == "integration":
        workers = _worker_count()
        exit_code = pytest.main([
            "tests/integration/",
            "-m", "integration",
            "-n", str(workers),
            "--dist", "loadgroup",
        ] + args[1:])
        _integration_cleanup()
        sys.exit(exit_code)

    elif mode == "all":
        # Run unit tests first (fast), then integration in parallel
        unit_code = pytest.main(["tests/", "-m", "not integration"] + args[1:])
        if unit_code != 0:
            print("\n[run_tests] Unit tests failed — skipping integration.")
            sys.exit(unit_code)

        workers = _worker_count()
        int_code = pytest.main([
            "tests/integration/",
            "-m", "integration",
            "-n", str(workers),
            "--dist", "loadgroup",
        ] + args[1:])
        _integration_cleanup()
        sys.exit(int_code)

    else:
        # Pass-through: forward everything to pytest as-is
        exit_code = pytest.main(args)
        sys.exit(exit_code)


if __name__ == "__main__":
    main()
