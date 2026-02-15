import json

import pytest

from tests.integration.conftest import os_target_params

REMOTE_DEPLOY_DIR = "/opt/sysadmin-ai"


def _run_sysadmin_ai_function(driver, python_expression):
    """
    Execute a sysadmin_ai function on the remote host and return parsed result.

    Builds a python3 -c one-liner that:
    1. Inserts /opt/sysadmin-ai into sys.path
    2. Imports sysadmin_ai
    3. Evaluates the expression
    4. json.dumps the result to stdout

    Returns the parsed JSON (tuples become lists).
    """
    remote_code = (
        "import sys, json; "
        f"sys.path.insert(0, '{REMOTE_DEPLOY_DIR}'); "
        "import sysadmin_ai; "
        f"result = {python_expression}; "
        "print(json.dumps(result))"
    )
    cmd = f'python3 -c "{remote_code}"'
    result = driver.run(cmd)
    assert result["exit_code"] == 0, (
        f"Remote function execution failed:\n"
        f"expression: {python_expression}\n"
        f"stdout: {result['stdout']}\nstderr: {result['stderr']}"
    )
    return json.loads(result["stdout"].strip())


def _ensure_deployed(driver, os_target, sysadmin_ai_path):
    """
    Idempotent deployment: run setup commands, install pip/openai, upload code.

    All operations are no-ops when already done. First call pays ~60-120s,
    subsequent calls ~3-5s.
    """
    # Setup commands (idempotent: apt-get update, install python3)
    for cmd in os_target.setup_commands:
        driver.run(cmd, timeout=300)

    # Install pip (idempotent)
    if os_target.pkg_manager == "apt":
        driver.run(
            "apt-get -o DPkg::Lock::Timeout=120 install -y python3-pip",
            timeout=300,
        )
    else:
        driver.run("dnf install -y python3-pip", timeout=300)

    # Install openai using OS-specific pip flags (idempotent)
    pip_cmd = f"pip3 install {os_target.pip_flags} openai".strip()
    driver.run(pip_cmd, timeout=300)

    # Upload sysadmin-ai (idempotent: overwrites)
    driver.upload_dir(sysadmin_ai_path, REMOTE_DEPLOY_DIR)


@os_target_params()
@pytest.mark.integration
class TestSysadminAi:

    def test_safe_command_allowed(self, ssh_connect, os_target, sysadmin_ai_path):
        """check_command_safety('ls -la') returns ["safe", None]."""
        driver = ssh_connect(os_target)
        try:
            _ensure_deployed(driver, os_target, sysadmin_ai_path)
            result = _run_sysadmin_ai_function(
                driver, "sysadmin_ai.check_command_safety('ls -la')"
            )
            assert result == ["safe", None]
        finally:
            driver.close()

    def test_blocked_command_rejected(self, ssh_connect, os_target, sysadmin_ai_path):
        """check_command_safety('rm -rf /') returns ["blocked", <non-empty>]."""
        driver = ssh_connect(os_target)
        try:
            _ensure_deployed(driver, os_target, sysadmin_ai_path)
            result = _run_sysadmin_ai_function(
                driver, "sysadmin_ai.check_command_safety('rm -rf /')"
            )
            assert result[0] == "blocked"
            assert result[1], "Blocked reason should be non-empty"
        finally:
            driver.close()

    def test_graylist_command_flagged(self, ssh_connect, os_target, sysadmin_ai_path):
        """check_command_safety('systemctl stop nginx') returns ["confirm", <non-empty>]."""
        driver = ssh_connect(os_target)
        try:
            _ensure_deployed(driver, os_target, sysadmin_ai_path)
            result = _run_sysadmin_ai_function(
                driver,
                "sysadmin_ai.check_command_safety('systemctl stop nginx')",
            )
            assert result[0] == "confirm"
            assert result[1], "Confirm reason should be non-empty"
        finally:
            driver.close()

    def test_read_safety_blocks_shadow(
        self, ssh_connect, os_target, sysadmin_ai_path
    ):
        """_check_read_safety('/etc/shadow') returns ["blocked", <non-empty>]."""
        driver = ssh_connect(os_target)
        try:
            _ensure_deployed(driver, os_target, sysadmin_ai_path)
            result = _run_sysadmin_ai_function(
                driver, "sysadmin_ai._check_read_safety('/etc/shadow')"
            )
            assert result[0] == "blocked"
            assert result[1], "Blocked reason should be non-empty"
        finally:
            driver.close()

    def test_write_safety_blocks_passwd(
        self, ssh_connect, os_target, sysadmin_ai_path
    ):
        """_check_write_safety('/etc/passwd') returns ["blocked", <non-empty>]."""
        driver = ssh_connect(os_target)
        try:
            _ensure_deployed(driver, os_target, sysadmin_ai_path)
            result = _run_sysadmin_ai_function(
                driver, "sysadmin_ai._check_write_safety('/etc/passwd')"
            )
            assert result[0] == "blocked"
            assert result[1], "Blocked reason should be non-empty"
        finally:
            driver.close()

    def test_redact_text_redacts_api_key(
        self, ssh_connect, os_target, sysadmin_ai_path
    ):
        """redact_text with an API key returns [REDACTED], no original key."""
        driver = ssh_connect(os_target)
        try:
            _ensure_deployed(driver, os_target, sysadmin_ai_path)
            result = _run_sysadmin_ai_function(
                driver,
                "sysadmin_ai.redact_text('my key is sk-abc123def456ghi789jkl012mno345')",
            )
            assert "[REDACTED]" in result
            assert "sk-abc123def456ghi789jkl012mno345" not in result
        finally:
            driver.close()
