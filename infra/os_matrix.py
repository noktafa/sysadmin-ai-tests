import json
import os


class OSTarget:
    def __init__(self, name, image, user="root", pkg_manager="apt",
                 family="debian", python_install="", setup_commands=None,
                 pip_flags=""):
        self.name = name
        self.image = image
        self.user = user
        self.pkg_manager = pkg_manager
        self.family = family
        self.python_install = python_install
        self.setup_commands = setup_commands if setup_commands is not None else []
        self.pip_flags = pip_flags
        self.snapshot_image = None

    def __repr__(self):
        return f"OSTarget(name={self.name!r}, image={self.image!r}, family={self.family!r})"

    def __eq__(self, other):
        if not isinstance(other, OSTarget):
            return NotImplemented
        return self.name == other.name and self.image == other.image


# cloud-init status --wait blocks until cloud-init finishes, which
# releases all apt/dnf locks.  One command instead of polling loops.
_WAIT_CLOUD_INIT = "cloud-init status --wait >/dev/null 2>&1 || true"

OS_MATRIX = [
    # --- Debian family (apt) ---
    OSTarget(
        name="ubuntu-24.04",
        image="ubuntu-24-04-x64",
        pkg_manager="apt",
        family="debian",
        python_install="apt-get update && apt-get install -y python3",
        setup_commands=[
            _WAIT_CLOUD_INIT,
            "apt-get update && apt-get install -y python3 python3-pip",
        ],
        pip_flags="--break-system-packages --ignore-installed",
    ),
    OSTarget(
        name="ubuntu-22.04",
        image="ubuntu-22-04-x64",
        pkg_manager="apt",
        family="debian",
        python_install="apt-get update && apt-get install -y python3",
        setup_commands=[
            _WAIT_CLOUD_INIT,
            "apt-get update && apt-get install -y python3 python3-pip",
        ],
        pip_flags="",
    ),
    OSTarget(
        name="debian-12",
        image="debian-12-x64",
        pkg_manager="apt",
        family="debian",
        python_install="apt-get update && apt-get install -y python3",
        setup_commands=[
            _WAIT_CLOUD_INIT,
            "apt-get update && apt-get install -y python3 python3-pip",
        ],
        pip_flags="--break-system-packages --ignore-installed",
    ),
    # --- RHEL family (dnf) ---
    OSTarget(
        name="centos-stream-9",
        image="centos-stream-9-x64",
        pkg_manager="dnf",
        family="rhel",
        python_install="dnf install -y python3",
        setup_commands=[
            _WAIT_CLOUD_INIT,
            "dnf install -y python3 python3-pip",
        ],
        pip_flags="",
    ),
    OSTarget(
        name="fedora-42",
        image="fedora-42-x64",
        pkg_manager="dnf",
        family="rhel",
        python_install="dnf install -y python3",
        setup_commands=[
            _WAIT_CLOUD_INIT,
            "dnf install -y python3 python3-pip",
        ],
        pip_flags="",
    ),
    OSTarget(
        name="almalinux-9",
        image="almalinux-9-x64",
        pkg_manager="dnf",
        family="rhel",
        python_install="dnf install -y python3",
        setup_commands=[
            _WAIT_CLOUD_INIT,
            "dnf install -y python3 python3-pip",
        ],
        pip_flags="",
    ),
]


_SNAPSHOTS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "snapshots.json")


def load_snapshots(targets=None):
    """Load infra/snapshots.json and set snapshot_image on matching OS targets.

    Returns the snapshot dict (or empty dict if file doesn't exist).
    """
    if not os.path.exists(_SNAPSHOTS_PATH):
        return {}

    with open(_SNAPSHOTS_PATH) as f:
        snapshots = json.load(f)

    if targets is None:
        targets = OS_MATRIX

    for target in targets:
        if target.name in snapshots:
            target.snapshot_image = str(snapshots[target.name]["snapshot_id"])

    return snapshots


def get_all(use_snapshots=True):
    """Returns a copy of the full OS_MATRIX list.

    When use_snapshots=True (default), loads infra/snapshots.json and swaps
    target.image to the snapshot ID for any OS that has a pre-built snapshot.
    """
    targets = list(OS_MATRIX)
    if use_snapshots:
        load_snapshots(targets)
        for target in targets:
            if target.snapshot_image:
                target.image = target.snapshot_image
    return targets


def get_by_name(name):
    """Returns a single OSTarget by name. Raises KeyError if not found."""
    for target in OS_MATRIX:
        if target.name == name:
            return target
    raise KeyError(f"No OS target named {name!r}")


def get_by_family(family):
    """Filter OS targets by family ('debian' or 'rhel')."""
    return [t for t in OS_MATRIX if t.family == family]


def get_by_pkg_manager(pm):
    """Filter OS targets by package manager ('apt' or 'dnf')."""
    return [t for t in OS_MATRIX if t.pkg_manager == pm]
