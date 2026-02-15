import os

import digitalocean
import pytest

from infra.droplet_controller import DropletController
from infra.guardrails import SessionGuard, check_stale_droplets
from infra.os_matrix import OSTarget, get_all
from infra.ssh_driver import SSHDriver, generate_keypair


def os_target_params():
    """Shorthand for parametrize over all OS targets.

    Each parameter carries an xdist_group marker so pytest-xdist keeps all
    tests for the same OS target on the same worker.  Embedding the marker
    in pytest.param() is more reliable than a collection hook because it
    guarantees the marker exists before xdist schedules distribution.
    """
    targets = get_all()
    return pytest.mark.parametrize(
        "os_target",
        [
            pytest.param(t, marks=pytest.mark.xdist_group(name=t.name))
            for t in targets
        ],
        ids=[t.name for t in targets],
    )


# ---------------------------------------------------------------------------
# Session-scoped fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def do_token():
    """Read DIGITALOCEAN_TOKEN from env; skip entire session if missing."""
    token = os.environ.get("DIGITALOCEAN_TOKEN")
    if not token:
        pytest.skip("DIGITALOCEAN_TOKEN not set — skipping integration tests")
    return token


@pytest.fixture(scope="session", autouse=True)
def preflight_check(do_token):
    """Warn if stale droplets exist from a previous run."""
    stale = check_stale_droplets(do_token)
    if stale:
        names = ", ".join(d["name"] for d in stale)
        print(
            f"\n⚠  WARNING: {len(stale)} stale droplet(s) found from a "
            f"previous run: {names}\n"
            f"   Run 'python scripts/cleanup.py' to remove them.\n"
        )


@pytest.fixture(scope="session")
def session_guard(do_token):
    """Session-wide cost/safety guard. Logs summary and cleans up on teardown."""
    guard = SessionGuard(token=do_token)
    yield guard


@pytest.fixture(scope="session")
def controller(do_token):
    """Session-wide DropletController instance."""
    return DropletController(token=do_token)


@pytest.fixture(scope="session")
def ssh_keypair():
    """Generate an ephemeral RSA keypair for the test session."""
    private_key, pub_string = generate_keypair()
    return private_key, pub_string


@pytest.fixture(scope="session")
def registered_ssh_key(do_token, ssh_keypair):
    """Register the ephemeral public key with DigitalOcean; destroy on teardown.

    Each xdist worker gets a unique key name to prevent collisions when
    multiple workers register keys in parallel.
    """
    _, pub_string = ssh_keypair
    worker_id = os.environ.get("PYTEST_XDIST_WORKER", "main")
    do_key = digitalocean.SSHKey(
        token=do_token,
        name=f"sysadmin-ai-test-ephemeral-{worker_id}",
        public_key=pub_string,
    )
    do_key.create()
    yield do_key
    try:
        do_key.destroy()
    except Exception:
        pass


@pytest.fixture(scope="session")
def droplet_pool(controller, registered_ssh_key, session_guard):
    """
    Factory fixture: get_or_create(os_target) → {"id": int, "ip": str}.

    Lazily creates one droplet per OS target. Destroys all on teardown.
    Triple-layered cleanup: individual destroy → destroy_all by tag → guard cleanup.
    """
    pool = {}  # os_target.name → {"id": int, "ip": str}

    def get_or_create(os_target):
        if os_target.name in pool:
            return pool[os_target.name]

        session_guard.check_before_create()

        info = controller.create(
            image=os_target.image,
            ssh_keys=[registered_ssh_key],
        )
        ip = controller.wait_until_ready(info["id"])
        entry = {"id": info["id"], "ip": ip}
        pool[os_target.name] = entry
        return entry

    yield get_or_create

    # Log session summary
    try:
        summary = session_guard.summary()
        print(
            f"\n--- Session Summary ---\n"
            f"  Elapsed: {summary['elapsed_minutes']} min\n"
            f"  Droplets: {summary['droplet_count']}\n"
            f"  Estimated cost: ${summary['estimated_cost']:.4f}\n"
        )
    except Exception:
        pass

    # Layer 1: destroy each tracked droplet individually
    for name, entry in pool.items():
        try:
            controller.destroy(entry["id"])
        except Exception:
            pass

    # Layer 2 & 3: skip when running as an xdist worker, because other
    # workers may still be using their droplets.  The global cleanup
    # sweep runs in run_tests.py after all workers have finished.
    if not os.environ.get("PYTEST_XDIST_WORKER"):
        # Layer 2: destroy_all by tag as safety net
        try:
            controller.destroy_all()
        except Exception:
            pass

        # Layer 3: guard cleanup as final safety net
        session_guard.cleanup(controller)


class _PooledDriver:
    """Thin wrapper around SSHDriver that suppresses close().

    Tests call driver.close() in finally blocks, but with connection
    pooling we want to keep the connection alive for reuse.  The real
    cleanup happens in the ssh_connect fixture teardown.
    """

    def __init__(self, driver):
        self._driver = driver

    def run(self, command, timeout=120):
        return self._driver.run(command, timeout=timeout)

    def upload_file(self, local_path, remote_path):
        return self._driver.upload_file(local_path, remote_path)

    def upload_dir(self, local_path, remote_path):
        return self._driver.upload_dir(local_path, remote_path)

    def close(self):
        pass  # no-op — connection stays alive for reuse


@pytest.fixture(scope="session")
def ssh_connect(droplet_pool, ssh_keypair):
    """
    Factory fixture: connect(os_target) → pooled SSHDriver wrapper.

    Connections are cached and reused across tests for the same OS target.
    This avoids SSH reconnection failures on VMs where cloud-init restarts
    sshd (e.g. Rocky 9).  Tests still call driver.close() in finally blocks
    but the wrapper makes it a no-op.

    Fail-fast: if droplet creation or the initial SSH connection fails for
    an OS target, the error is cached and all subsequent tests for that
    target skip immediately.
    """
    private_key, _ = ssh_keypair
    _failed = {}       # os_target.name → error message
    _connections = {}   # os_target.name → SSHDriver (real, not wrapped)

    def connect(os_target):
        if os_target.name in _failed:
            pytest.skip(
                f"Skipping — VM for {os_target.name} is unavailable: "
                f"{_failed[os_target.name]}"
            )

        # Return cached connection if available
        if os_target.name in _connections:
            return _PooledDriver(_connections[os_target.name])

        try:
            entry = droplet_pool(os_target)
            driver = SSHDriver(
                host=entry["ip"],
                username=os_target.user,
                key=private_key,
            )
            driver.connect()
            _connections[os_target.name] = driver
            return _PooledDriver(driver)
        except Exception as exc:
            _failed[os_target.name] = str(exc)
            raise

    yield connect

    # Teardown: close all cached connections
    for driver in _connections.values():
        try:
            driver.close()
        except Exception:
            pass


@pytest.fixture(scope="session")
def deployment_state():
    """Shared set tracking which OS targets have been successfully deployed."""
    return set()


@pytest.fixture(scope="session")
def sysadmin_ai_path():
    """Resolve the local sysadmin-ai project directory."""
    env_path = os.environ.get("SYSADMIN_AI_PATH")
    if env_path:
        path = os.path.abspath(env_path)
    else:
        # Default: sibling directory relative to the test project root
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        path = os.path.abspath(os.path.join(project_root, "..", "sysadmin-ai"))

    if not os.path.isdir(path):
        pytest.skip(f"sysadmin-ai directory not found at {path}")
    return path
