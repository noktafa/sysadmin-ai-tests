"""Cost & safety guardrails for DigitalOcean test infrastructure.

Prevents orphaned droplets, runaway creation, and session timeouts.
All thresholds are overridable via environment variables.
"""

import os
import time

import digitalocean


MAX_DROPLETS = int(os.environ.get("MAX_TEST_DROPLETS", "7"))
MAX_SESSION_MINUTES = int(os.environ.get("MAX_SESSION_MINUTES", "60"))
COST_PER_HOUR = 0.00893  # DigitalOcean s-1vcpu-1gb rate


def count_tagged_droplets(token, tag="sysadmin-ai-test"):
    """Return the number of existing droplets with the given tag."""
    manager = digitalocean.Manager(token=token)
    droplets = manager.get_all_droplets(tag_name=tag)
    return len(droplets)


def check_droplet_limit(token, tag="sysadmin-ai-test", limit=MAX_DROPLETS):
    """Raise RuntimeError if the number of tagged droplets meets or exceeds limit."""
    count = count_tagged_droplets(token, tag=tag)
    if count >= limit:
        raise RuntimeError(
            f"Droplet limit reached: {count} droplets exist with tag '{tag}' "
            f"(limit={limit}). Destroy existing droplets before creating more."
        )


def check_stale_droplets(token, tag="sysadmin-ai-test"):
    """Return a list of dicts describing existing tagged droplets.

    Each dict has keys: id, name, created_at.
    Returns an empty list if no tagged droplets exist.
    """
    manager = digitalocean.Manager(token=token)
    droplets = manager.get_all_droplets(tag_name=tag)
    return [
        {"id": d.id, "name": d.name, "created_at": d.created_at}
        for d in droplets
    ]


def estimate_cost(num_droplets, duration_minutes):
    """Estimate the cost for running num_droplets for duration_minutes."""
    return num_droplets * (duration_minutes / 60) * COST_PER_HOUR


class SessionGuard:
    """Tracks a test session and enforces cost/safety limits.

    Create once per session. Call check_before_create() before every
    droplet creation, and cleanup() during teardown as a safety net.
    """

    def __init__(self, token, tag="sysadmin-ai-test",
                 max_droplets=MAX_DROPLETS, max_minutes=MAX_SESSION_MINUTES):
        self.token = token
        self.tag = tag
        self.max_droplets = max_droplets
        self.max_minutes = max_minutes
        self._start = time.monotonic()

    def check_before_create(self):
        """Raise RuntimeError if droplet limit or session timeout is exceeded."""
        self.check_timeout()
        check_droplet_limit(self.token, tag=self.tag, limit=self.max_droplets)

    def check_timeout(self):
        """Raise RuntimeError if the session has exceeded max_minutes."""
        elapsed = self.elapsed_minutes()
        if elapsed > self.max_minutes:
            raise RuntimeError(
                f"Session timeout: {elapsed:.1f} minutes elapsed "
                f"(limit={self.max_minutes}). Aborting to prevent cost overrun."
            )

    def elapsed_minutes(self):
        """Return minutes since this guard was created."""
        return (time.monotonic() - self._start) / 60

    def summary(self):
        """Return a dict summarizing the session state."""
        elapsed = self.elapsed_minutes()
        count = count_tagged_droplets(self.token, tag=self.tag)
        return {
            "elapsed_minutes": round(elapsed, 2),
            "estimated_cost": round(estimate_cost(count, elapsed), 4),
            "droplet_count": count,
        }

    def cleanup(self, controller):
        """Emergency cleanup: destroy all tagged droplets. Always safe to call."""
        try:
            controller.destroy_all(tag=self.tag)
        except Exception:
            pass
