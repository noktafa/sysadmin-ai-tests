# sysadmin-ai-tests

Automated cross-distro testing pipeline for [sysadmin-ai](https://github.com/noktafa/sysadmin-ai). Spins up real DigitalOcean VMs across 6 Linux distributions, deploys sysadmin-ai via SSH, and validates safety guardrails, command checking, security hardening, and core functionality.

Real VMs are used instead of Docker because sysadmin-ai needs to test systemd, package managers, and kernel-level commands that containers can't faithfully reproduce.

## Test Results

| Run | Tests | Passed | Skipped | Failed | Time | Notes |
|-----|-------|--------|---------|--------|------|-------|
| run6 | 612 | 594 | 18 | 0 | 12m01s | With pre-built snapshots |
| run5 | 90 | 90 | 0 | 0 | 9m06s | Before snapshots, before security hardening tests |

## OS Matrix

| Family | Target           | Image                | Pkg Manager |
|--------|------------------|----------------------|-------------|
| Debian | Ubuntu 24.04     | ubuntu-24-04-x64     | apt         |
| Debian | Ubuntu 22.04     | ubuntu-22-04-x64     | apt         |
| Debian | Debian 12        | debian-12-x64        | apt         |
| RHEL   | CentOS Stream 9  | centos-stream-9-x64  | dnf         |
| RHEL   | Fedora 42        | fedora-42-x64        | dnf         |
| RHEL   | AlmaLinux 9      | almalinux-9-x64      | dnf         |

## What Gets Tested

612 integration tests across 6 OS targets, organized into three test suites:

### TestConnectivity (4 tests x 6 OS = 24)

Basic VM health checks that run first to fail fast if infrastructure is broken.

- **SSH access** -- connects via ephemeral keypair, runs `uname -a`
- **OS family verification** -- `/etc/os-release` matches expected debian/rhel family
- **Package manager availability** -- `which apt` or `which dnf` succeeds
- **systemd presence** -- `systemctl --version` succeeds

### TestDeployment (5 tests x 6 OS = 30)

Validates that sysadmin-ai can be installed and imported on each target OS. When using pre-built snapshots, setup and pip tests are skipped (dependencies already baked in).

- **Setup commands** -- `apt-get update && apt-get install python3 python3-pip` or equivalent dnf commands (skipped with snapshots)
- **Python3 available** -- `python3 --version` returns successfully
- **pip install openai** -- installs the OpenAI SDK with OS-appropriate pip flags (skipped with snapshots)
- **Upload sysadmin-ai** -- SFTP uploads `sysadmin_ai.py` and `soul.md` to `/opt/sysadmin-ai/`
- **Import sysadmin-ai** -- `python3 -c "import sysadmin_ai"` succeeds on the remote VM

### TestSysadminAi (7 test groups x 6 OS = ~258)

Tests sysadmin-ai's safety functions by calling them remotely on real Linux VMs.

- **Blocked commands** -- dangerous commands (`rm -rf /`, `mkfs`, `dd if=/dev/zero`, `:(){:|:&};:`, `chmod 777 /etc/shadow`, etc.) return `("blocked", reason)`
- **Graylist commands** -- risky-but-legitimate commands (`systemctl restart`, `kill`, `reboot`, etc.) return `("confirm", reason)` requiring user approval
- **Safe commands** -- everyday commands (`ls -la`, `df -h`, `cat /var/log/syslog`, `whoami`) return `("safe", None)`
- **Read safety** -- blocks reading sensitive files (`/etc/shadow`, `/etc/gshadow`, `~/.ssh/id_rsa`, SSH host keys)
- **Write safety** -- blocks writing to critical paths (`/etc/passwd`, `/etc/shadow`, `/etc/fstab`, `/etc/sudoers`, `/bin/`, `/boot/`)
- **Secret redaction** -- redacts API keys, tokens, and credentials (OpenAI keys, AWS keys, GitHub PATs, GitLab tokens, Slack tokens, JWTs, env exports)
- **OpenAI API connectivity** -- validates real API calls work from each VM (skipped when `OPENAI_API_KEY` is empty)

### TestSecurityHardening (11 test groups x 6 OS = ~300)

Tests the v0.16.0 security hardening layer. Each test calls sysadmin-ai functions on remote VMs to verify behavior across different OS environments.

- **Interpreter evasion blocking** (17 patterns) -- blocks `bash -c`, `sh -c`, `python3 -c`, `perl -e`, `ruby -e`, `node -e`, `eval`, base64 pipe to shell, `Invoke-Expression`/`iex`, `crontab -r/-e`, `find -exec rm`/`xargs rm`/`find -delete`
- **Script execution graylist** (7 patterns) -- `bash deploy.sh`, `sh setup.sh`, `python3 migrate.py`, `perl transform.pl`, `ruby deploy.rb`, `node server.js`, `source ~/.bashrc` all require confirmation
- **Write content scanning -- dangerous** (9 patterns) -- blocks file content containing reverse shells, `curl | bash`, shadow/SSH key reads, mimikatz references, `rm -rf /`, SUID escalation, data exfiltration, PowerShell `Invoke-Expression`
- **Write content scanning -- safe** (3 patterns) -- allows benign content (`echo Hello World`, nginx config, connection settings)
- **Prompt injection delimiters** -- `_wrap_tool_output()` wraps output in `[BEGIN/END]` delimiters to prevent LLM prompt injection
- **Script path extraction** -- `_extract_script_path()` correctly parses script paths from commands
- **Write-then-execute detection** -- flags execution of recently-written scripts (e.g. write `/tmp/evil.sh` then `bash /tmp/evil.sh`)
- **Non-written script safety** -- allows execution of scripts the agent didn't write
- **Safe command regression** (9 commands) -- `ls -la`, `cat /etc/hostname`, `python3 --version`, `node --version`, `crontab -l`, `df -h`, `ps aux`, `whoami`, `uname -a` remain classified as safe after hardening
- **Full remote test suite** -- installs pytest on each VM and runs sysadmin-ai's own unit test suite remotely

## Pre-built Snapshots

To avoid spending ~5 minutes per test run on `apt/dnf update`, `pip install`, and `cloud-init` waiting, pre-built DigitalOcean snapshots are used. Each snapshot has python3, pip, and the openai package already installed.

**Cost:** ~$0.90/month for 6 snapshots (~$0.06/GB/month x ~2.5GB each).

### Building Snapshots

```bash
python scripts/build_snapshots.py              # Build all 6 snapshots (~5 min)
python scripts/build_snapshots.py --dry-run    # Show what would be built
python scripts/build_snapshots.py --force      # Rebuild even if snapshots.json exists
```

This creates one droplet per OS target in parallel, SSHs in, runs setup commands, installs openai, powers off, takes a snapshot, destroys the droplet, and writes the snapshot IDs to `infra/snapshots.json`.

### Deleting Snapshots

```bash
python scripts/delete_snapshots.py             # Delete all snapshots from DO
python scripts/delete_snapshots.py --dry-run   # List without deleting
```

### How It Works

When snapshots exist (`infra/snapshots.json`), `os_matrix.get_all()` transparently swaps each target's base image to the snapshot ID. The test fixtures (`droplet_pool`, `ssh_connect`) use `os_target.image` as before -- no changes needed. Tests that verify setup (package install, pip install) are automatically skipped since the work is already done.

Without snapshots, everything falls back to the original behavior: base images + setup commands.

## Project Structure

```
sysadmin-ai-tests/
├── infra/
│   ├── droplet_controller.py   # DigitalOcean VM lifecycle (create/destroy/wait)
│   ├── ssh_driver.py           # SSH connections, command execution, file transfer
│   ├── os_matrix.py            # 6 OS target definitions + snapshot loading
│   ├── snapshots.json          # Pre-built snapshot IDs (generated, checked in)
│   ├── guardrails.py           # Cost limits, session timeouts, safety checks
│   └── status_monitor.py       # Live droplet status printing during test runs
├── tests/
│   └── integration/
│       ├── conftest.py             # Session fixtures, xdist grouping, cleanup
│       ├── test_connectivity.py    # SSH, uname, pkg manager, systemctl
│       ├── test_deployment.py      # Setup commands, Python, pip, upload, import
│       └── test_sysadmin_ai.py     # Command safety, security hardening, redaction
├── scripts/
│   ├── cleanup.py              # Emergency cleanup for orphaned resources
│   ├── build_snapshots.py      # Build pre-baked OS snapshots for faster tests
│   └── delete_snapshots.py     # Delete snapshots from DigitalOcean
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
| `OPENAI_API_KEY`     | No       | Enables OpenAI API connectivity tests (must be empty or unset to skip) |
| `SYSADMIN_AI_PATH`   | No       | Path to sysadmin-ai repo (default: `../sysadmin-ai`) |
| `MAX_TEST_DROPLETS`  | No       | Max concurrent droplets (default: 6)             |
| `MAX_SESSION_MINUTES`| No       | Session timeout in minutes (default: 60)         |

## Running Tests

```bash
python run_tests.py unit            # Unit tests (fast, no cloud resources)
python run_tests.py integration     # 612 integration tests, 6 parallel workers
python run_tests.py all             # Unit first, then integration
python run_tests.py [pytest args]   # Pass-through to pytest
```

### Parallel Execution

Integration tests run in parallel using `pytest-xdist`. Tests are grouped by OS target (`--dist loadgroup`), so each of the 6 workers provisions exactly one droplet and runs all tests for that target sequentially. This keeps the total wall time around 12 minutes despite 612 tests.

### Test Execution Flow

```
1. Session startup
   ├── Validate DIGITALOCEAN_TOKEN
   ├── Check for stale droplets from previous runs
   ├── Validate OPENAI_API_KEY (if set)
   ├── Generate ephemeral SSH keypair
   └── Register SSH key with DigitalOcean

2. Per-worker (6 workers in parallel, one per OS target)
   ├── Create droplet from snapshot (or base image)
   ├── Wait for active status + IP assignment
   ├── SSH connect with retry loop
   ├── Run TestConnectivity (4 tests)
   ├── Run TestDeployment (5 tests, 2 skipped if snapshot)
   ├── Run TestSysadminAi (~43 tests)
   └── Run TestSecurityHardening (~50 tests)

3. Session teardown
   ├── Destroy each tracked droplet
   ├── Tag sweep: destroy_all() catches orphans
   ├── SessionGuard: final safety-net cleanup
   ├── Destroy ephemeral SSH key
   └── Print session summary (elapsed time, cost estimate)
```

## Safety and Cost Guardrails

All test infrastructure is ephemeral and tagged (`sysadmin-ai-test`). Cleanup is triple-layered:

1. **Per-droplet** -- each tracked VM is individually destroyed on teardown
2. **Tag sweep** -- `destroy_all()` catches any orphans by tag
3. **SessionGuard** -- final safety-net cleanup pass

Cost estimation runs at `$0.00893/hr` per droplet (s-1vcpu-1gb). A full 6-droplet session under 15 minutes costs approximately $0.01.

### Emergency Cleanup

If a test run is interrupted and droplets are left running:

```bash
python scripts/cleanup.py              # Interactive: lists resources, asks for confirmation
python scripts/cleanup.py --dry-run    # List orphaned resources without destroying
python scripts/cleanup.py --force      # Destroy immediately, no confirmation
```
