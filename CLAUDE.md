# sysadmin-ai-tests

Integration test suite for [sysadmin-ai](https://github.com/noktafa/sysadmin-ai) — an LLM-powered sysadmin assistant with safety filters. Tests run on real Linux VMs across 6 OS targets via DigitalOcean.

## Ecosystem

```
sysadmin-ai/            # The product: LLM sysadmin agent with safety filters
sysadmin-ai-tests/      # THIS REPO: multi-OS integration tests
dreamloop/              # Self-improving pipeline: diagnose → fix → attack → validate
dreamloop-dash/         # Real-time dashboard (http://localhost:8500, launchd service)
dreamer/                # 7-server banking POC (target infrastructure for dreamloop)
sysfox-ai/              # Diagnostic tool (used by dreamloop diagnose step)
badintentions/          # Adversarial security auditor (dreamloop attack step)
dreamcatcher/           # Validation test suite (dreamloop validate step)
```

All repos live as siblings under `~/claude/`. sysadmin-ai is the core — everything else orbits it.

## Running Tests

**Always use `run_tests.py` — never call pytest directly.**

```bash
python3 run_tests.py unit          # Unit tests only (fast, no VMs)
python3 run_tests.py integration   # Integration tests (6 parallel workers, real VMs)
python3 run_tests.py all           # Unit first, then integration
```

### Required Environment

```bash
export DIGITALOCEAN_TOKEN=...      # Required for integration tests
unset OPENAI_API_KEY               # MUST be unset (causes preflight_check import failure)
unset OPENAI_BASE_URL              # Unset to avoid interference
unset OPENAI_MODEL                 # Unset to avoid interference
```

**Critical**: `OPENAI_API_KEY` must be empty or unset. If set, `preflight_check` in conftest.py tries to `import openai` which isn't installed in the test venv, causing all 612 tests to error.

### Dashboard Integration

The dashboard auto-starts on boot (launchd service at `com.noktafa.dreamloop-dash`). Tests stream live progress to it when running:

```bash
DASHBOARD_URL=http://localhost:8500 python3 run_tests.py integration -v --durations=0 --tb=short
```

The pytest plugin (`tests/dash_plugin.py`) maps test classes to dashboard panels:
- TestConnectivity → Connectivity phase
- TestDeployment → Deployment phase
- TestSysadminAi → SysadminAi phase
- TestSecurityHardening → Security phase

Each test result streams as a real-time event. Plugin auto-disables if dashboard is unreachable.

## Test Architecture

### OS Targets (6 VMs, parallel via pytest-xdist)

| OS | Family | Pkg Manager | Snapshot |
|----|--------|-------------|----------|
| Ubuntu 24.04 | debian | apt | yes |
| Ubuntu 22.04 | debian | apt | yes |
| Debian 12 | debian | apt | yes |
| CentOS Stream 9 | rhel | dnf | yes |
| Fedora 42 | rhel | dnf | yes |
| AlmaLinux 9 | rhel | dnf | yes |

Pre-built snapshots have Python3 + openai pip package baked in. Defined in `infra/os_matrix.py`, snapshot IDs in `infra/snapshots.json`.

### Test Execution Flow

1. **Session setup**: Create ephemeral SSH keypair, register with DigitalOcean
2. **Per-OS worker**: Each xdist worker (gw0-gw5) handles one OS target
3. **Droplet creation**: Lazy — first test for each OS triggers VM creation from snapshot (~60s)
4. **Connection pooling**: SSH connections cached and reused across tests (see `_PooledDriver`)
5. **Test phases** (sequential per OS, parallel across OS targets):
   - **Connectivity** (4 tests × 6 OS = 24): SSH, uname, os-release, pkg manager, systemctl
   - **Deployment** (5 tests × 6 OS = 30): setup commands, python3, pip, upload, import
   - **SysadminAi** (29 tests × 6 OS = 174): blocked/graylist/safe commands, read/write safety, redaction, API connectivity
   - **SecurityHardening** (40 tests × 6 OS = 240): interpreter evasion, script execution, content scanning, prompt injection, write-then-execute, full remote test suite
6. **Cleanup**: Destroy all droplets + SSH keys (triple-layered: individual → tag sweep → guard)

### What Gets Tested

sysadmin-ai has a two-tier safety filter:
- **Blocklist** (~100 regex patterns): `rm -rf /`, `mkfs`, reverse shells, `cat /etc/shadow`, etc. → hard reject
- **Graylist**: `systemctl stop`, `reboot`, `iptables -F`, etc. → requires confirmation
- **Safe**: `ls`, `df -h`, `ps aux`, `whoami`, etc. → allowed

Tests verify these classifications work identically across all 6 Linux distros by running `sysadmin_ai.check_command_safety()` remotely on each VM.

SecurityHardening (v0.16.0) additionally tests:
- Interpreter evasion blocking (`python3 -c`, `eval`, `base64 | bash`)
- Content scanning (`_check_write_content_safety`)
- Prompt injection delimiters (`_wrap_tool_output`)
- Write-then-execute detection (`_check_script_execution_safety`)
- Full pytest suite execution on remote VMs

## Project Structure

```
run_tests.py                    # Entry point — use this, not pytest directly
pytest.ini                      # Markers: integration, xdist_group
scripts/cleanup.py              # Emergency VM cleanup (--force to skip prompts)
infra/
  os_matrix.py                  # 6 OS targets with setup commands and snapshot IDs
  droplet_controller.py         # DigitalOcean droplet lifecycle (create/wait/destroy)
  ssh_driver.py                 # SSH/SFTP operations (upload_dir skips .venv/.git)
  guardrails.py                 # SessionGuard: cost limits, stale droplet detection
  status_monitor.py             # Background thread printing VM status every 30s
  snapshots.json                # Pre-built snapshot IDs per OS target
tests/
  conftest.py                   # Markers + dashboard plugin registration
  dash_plugin.py                # Streams test progress to dreamloop-dash
  test_droplet_controller.py    # Unit tests for infra
  test_guardrails.py
  test_os_matrix.py
  test_ssh_driver.py
  integration/
    conftest.py                 # Session fixtures: DO token, SSH keys, droplet pool, connection pool
    test_connectivity.py        # Basic SSH + OS verification
    test_deployment.py          # Package setup + sysadmin-ai upload
    test_sysadmin_ai.py         # Safety filter + security hardening tests
```

## Common Issues

| Issue | Cause | Fix |
|-------|-------|-----|
| All 612 tests ERROR | `OPENAI_API_KEY` is set | `unset OPENAI_API_KEY` |
| "Unable to authenticate you" | Wrong/expired DO token | Check `$DIGITALOCEAN_TOKEN` matches the one in `~/.zshrc` |
| Tests hang on `test_upload_sysadmin_ai` | `upload_dir` uploading `.venv` (41MB) | Fixed: `ssh_driver.py` now skips `.venv`, `.git`, `__pycache__` |
| Stale droplets from crashed run | Tests killed mid-run | `python3 scripts/cleanup.py --force` |
| Dashboard shows no data | Dashboard not running | `launchctl start com.noktafa.dreamloop-dash` |

## Performance

Typical run: **~594 passed, ~18 skipped, 0 failed in ~5-6 minutes**

- VM provisioning: ~60s (DigitalOcean snapshot boot)
- Individual safety tests: 1-3s each (SSH roundtrip)
- Full remote test suite: ~40s per OS
- Cost per run: ~$0.01 (6 × $0.006/hr droplets for ~6 min)

## LLM Configuration (Kimi/Moonshot)

The project uses Moonshot AI's Kimi API as the LLM backend (OpenAI-compatible):
```
OPENAI_API_KEY=<your-moonshot-api-key>
OPENAI_BASE_URL=https://api.moonshot.ai/v1
OPENAI_MODEL=moonshot-v1-128k
```
These are set in `~/.zshrc` but **must be unset** when running integration tests.
