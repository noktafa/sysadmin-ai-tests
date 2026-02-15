# sysadmin-ai-tests

Automated cross-distro testing pipeline for [sysadmin-ai](../sysadmin-ai). Spins up real DigitalOcean VMs across 7 Linux distributions, deploys sysadmin-ai via SSH, and validates safety guardrails, command checking, and core functionality.

Real VMs are used instead of Docker because sysadmin-ai needs to test systemd, package managers, and kernel-level commands.

## OS Matrix

| Family | Target           | Image                | Pkg Manager |
|--------|------------------|----------------------|-------------|
| Debian | Ubuntu 24.04     | ubuntu-24-04-x64     | apt         |
| Debian | Ubuntu 22.04     | ubuntu-22-04-x64     | apt         |
| Debian | Debian 12        | debian-12-x64        | apt         |
| RHEL   | CentOS Stream 9  | centos-stream-9-x64  | dnf         |
| RHEL   | Fedora 42        | fedora-42-x64        | dnf         |
| RHEL   | Rocky 9          | rockylinux-9-x64     | dnf         |
| RHEL   | AlmaLinux 9      | almalinux-9-x64      | dnf         |

## Project Structure

```
sysadmin-ai-tests/
├── infra/
│   ├── droplet_controller.py   # DigitalOcean VM lifecycle (create/destroy/wait)
│   ├── ssh_driver.py           # SSH connections, command execution, file transfer
│   ├── os_matrix.py            # 7 OS target definitions
│   └── guardrails.py           # Cost limits, session timeouts, safety checks
├── tests/
│   ├── test_droplet_controller.py
│   ├── test_guardrails.py
│   ├── test_os_matrix.py
│   ├── test_ssh_driver.py
│   └── integration/
│       ├── conftest.py             # Session fixtures, xdist grouping, cleanup
│       ├── test_connectivity.py    # SSH, uname, pkg manager, systemctl
│       ├── test_deployment.py      # Setup commands, Python, pip, upload, import
│       └── test_sysadmin_ai.py     # Command safety, read/write safety, redaction
├── scripts/
│   └── cleanup.py              # Emergency cleanup for orphaned resources
├── run_tests.py                # Cross-platform test runner
├── pytest.ini
└── requirements.txt
```

## Setup

**Requirements:** Python 3.10+

```bash
pip install -r requirements.txt
```

**Environment variables:**

| Variable             | Required | Description                                      |
|----------------------|----------|--------------------------------------------------|
| `DIGITALOCEAN_TOKEN` | For integration tests | DigitalOcean API token               |
| `SYSADMIN_AI_PATH`   | No       | Path to sysadmin-ai repo (default: `../sysadmin-ai`) |
| `MAX_TEST_DROPLETS`  | No       | Max concurrent droplets (default: 7)             |
| `MAX_SESSION_MINUTES`| No       | Session timeout in minutes (default: 60)         |

## Running Tests

```bash
python run_tests.py unit            # 80 unit tests (fast, no cloud resources)
python run_tests.py integration     # 105 integration tests, 7 parallel workers
python run_tests.py all             # Unit first, then integration
python run_tests.py [pytest args]   # Pass-through to pytest
```

### Parallel Execution

Integration tests run in parallel using `pytest-xdist`. Tests are grouped by OS target (`--dist loadgroup`), so each of the 7 workers provisions exactly one droplet and runs all 15 tests for that target. This brings the integration suite from ~97 minutes (sequential) down to ~15-20 minutes.

### What the Integration Tests Cover

- **Connectivity** (4 tests per OS) -- SSH access, OS family verification, package manager availability, systemd presence
- **Deployment** (5 tests per OS) -- setup commands, Python3 installation, pip install, file upload, module import
- **sysadmin-ai behavior** (6 tests per OS) -- safe/blocked/graylist command classification, read/write safety checks, API key redaction

## Safety & Cost Guardrails

All test infrastructure is ephemeral and tagged (`sysadmin-ai-test`). Cleanup is triple-layered:

1. **Per-droplet** -- each tracked VM is individually destroyed on teardown
2. **Tag sweep** -- `destroy_all()` catches any orphans by tag
3. **SessionGuard** -- final safety-net cleanup pass

Cost estimation runs at `$0.00893/hr` per droplet (s-1vcpu-1gb). A full 7-droplet session under 20 minutes costs approximately $0.02.

### Emergency Cleanup

If a test run is interrupted and droplets are left running:

```bash
python scripts/cleanup.py              # Interactive: lists resources, asks for confirmation
python scripts/cleanup.py --dry-run    # List orphaned resources without destroying
python scripts/cleanup.py --force      # Destroy immediately, no confirmation
```
