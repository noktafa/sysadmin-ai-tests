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


def get_all():
    """Returns a copy of the full OS_MATRIX list."""
    return list(OS_MATRIX)


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
