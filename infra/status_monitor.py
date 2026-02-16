"""Live DigitalOcean droplet status monitor for integration tests.

Runs a background thread that periodically queries the DO API and prints
a status table showing droplet health, IP, and image info alongside test
progress. Integrates as a pytest plugin via conftest.py.
"""

import json
import os
import threading
import time
import urllib.request


TAG = "sysadmin-ai-test"
DEFAULT_INTERVAL = 30  # seconds between status checks


def _fetch_droplets(token, tag=TAG):
    """Query DO API for tagged droplets. Returns list of dicts."""
    url = f"https://api.digitalocean.com/v2/droplets?tag_name={tag}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())
    except Exception as exc:
        return None, str(exc)
    return data.get("droplets", []), None


def _format_status_line(droplets, elapsed_minutes):
    """Format a compact status summary."""
    if not droplets:
        return f"  [Monitor] No droplets found (elapsed: {elapsed_minutes:.1f}m)"

    lines = [
        f"\n  [Monitor] {len(droplets)} droplet(s) | elapsed: {elapsed_minutes:.1f}m",
        f"  {'Name':<30s} {'Status':<10s} {'Image':<22s} {'IP':<16s} {'Region'}",
        f"  {'-'*30} {'-'*10} {'-'*22} {'-'*16} {'-'*6}",
    ]
    for d in droplets:
        name = d.get("name", "?")
        status = d.get("status", "?")
        image = d.get("image", {})
        image_name = image.get("slug") or image.get("name", "?")
        networks = d.get("networks", {}).get("v4", [])
        ip = networks[0].get("ip_address", "pending") if networks else "pending"
        region = d.get("region", {}).get("slug", "?")
        lines.append(f"  {name:<30s} {status:<10s} {image_name:<22s} {ip:<16s} {region}")

    return "\n".join(lines)


class StatusMonitor:
    """Background monitor that prints DO droplet status periodically."""

    def __init__(self, token, interval=None):
        self.token = token
        self.interval = interval or int(os.environ.get("STATUS_MONITOR_INTERVAL", DEFAULT_INTERVAL))
        self._stop_event = threading.Event()
        self._thread = None
        self._start_time = time.monotonic()

    def start(self):
        """Start the background monitoring thread."""
        self._thread = threading.Thread(target=self._run, daemon=True, name="do-status-monitor")
        self._thread.start()

    def stop(self):
        """Signal the monitor to stop and wait for it."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    def _run(self):
        """Main loop: fetch and print status at regular intervals."""
        # Initial status after a short delay (let droplets start creating)
        self._stop_event.wait(10)

        while not self._stop_event.is_set():
            elapsed = (time.monotonic() - self._start_time) / 60
            droplets, error = _fetch_droplets(self.token)
            if error:
                print(f"\n  [Monitor] API error: {error}")
            else:
                print(_format_status_line(droplets, elapsed), flush=True)

            self._stop_event.wait(self.interval)

    def print_now(self):
        """Print status immediately (for on-demand checks)."""
        elapsed = (time.monotonic() - self._start_time) / 60
        droplets, error = _fetch_droplets(self.token)
        if error:
            print(f"\n  [Monitor] API error: {error}")
        else:
            print(_format_status_line(droplets, elapsed), flush=True)
