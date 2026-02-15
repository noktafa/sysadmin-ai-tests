import json
import os
import threading

import pytest

from tests.integration.conftest import os_target_params

REMOTE_DEPLOY_DIR = "/opt/sysadmin-ai"

# Thread-safe results log — survives xdist worker isolation
_results_lock = threading.Lock()
_RESULTS_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "logs", "sysadmin_ai_results.jsonl",
)


def _run_sysadmin_ai_function(driver, python_expression, os_name=""):
    """
    Execute a sysadmin_ai function on the remote host and return parsed result.

    Builds a python3 -c one-liner that:
    1. Inserts /opt/sysadmin-ai into sys.path
    2. Imports sysadmin_ai
    3. Evaluates the expression
    4. json.dumps the result to stdout

    Returns the parsed JSON (tuples become lists).
    Writes each call+result to logs/sysadmin_ai_results.jsonl.
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
    parsed = json.loads(result["stdout"].strip())

    # Write to results file (thread-safe, works across xdist workers)
    entry = {"os": os_name, "call": python_expression, "result": parsed}
    try:
        os.makedirs(os.path.dirname(_RESULTS_FILE), exist_ok=True)
        with _results_lock:
            with open(_RESULTS_FILE, "a") as f:
                f.write(json.dumps(entry) + "\n")
    except Exception:
        pass

    return parsed


def _run_remote_python(driver, code, env=None, os_name=""):
    """
    Execute a multi-line Python snippet on the remote host and return parsed JSON.

    Unlike _run_sysadmin_ai_function (which wraps a single expression in
    double-quoted python3 -c "..."), this helper uses single-quoted shell
    strings so the Python code can contain double quotes, dict literals, etc.

    The last line of *code* must print(json.dumps(...)) to produce output.
    *env* is an optional dict of environment variables injected as an inline
    prefix (never written to disk).
    """
    # Escape single quotes in the Python code for the shell
    escaped_code = code.replace("'", "'\\''")

    env_prefix = ""
    if env:
        env_prefix = " ".join(f"{k}={v}" for k, v in env.items()) + " "

    cmd = f"{env_prefix}python3 -c '{escaped_code}'"
    result = driver.run(cmd)
    assert result["exit_code"] == 0, (
        f"Remote Python execution failed:\n"
        f"stdout: {result['stdout']}\nstderr: {result['stderr']}"
    )
    parsed = json.loads(result["stdout"].strip())

    # Write to results file (thread-safe, works across xdist workers)
    entry = {"os": os_name, "call": "run_remote_python", "result": parsed}
    try:
        os.makedirs(os.path.dirname(_RESULTS_FILE), exist_ok=True)
        with _results_lock:
            with open(_RESULTS_FILE, "a") as f:
                f.write(json.dumps(entry) + "\n")
    except Exception:
        pass

    return parsed


_deployed_targets = set()


def _ensure_deployed(driver, os_target, sysadmin_ai_path):
    """
    Deploy once per OS target, then skip entirely on subsequent calls.

    First call: cloud-init wait + package install + pip + SFTP upload.
    Subsequent calls: instant return (zero SSH roundtrips).
    """
    if os_target.name in _deployed_targets:
        return

    # Setup: wait for cloud-init + install python3/pip in one command
    for cmd in os_target.setup_commands:
        driver.run(cmd, timeout=300)

    # Install openai
    pip_cmd = f"pip3 install {os_target.pip_flags} openai".strip()
    driver.run(pip_cmd, timeout=300)

    # Upload sysadmin-ai
    driver.upload_dir(sysadmin_ai_path, REMOTE_DEPLOY_DIR)

    _deployed_targets.add(os_target.name)


@os_target_params()
@pytest.mark.integration
class TestSysadminAi:

    def test_safe_command_allowed(self, ssh_connect, os_target, sysadmin_ai_path):
        """check_command_safety('ls -la') returns ["safe", None]."""
        driver = ssh_connect(os_target)
        try:
            _ensure_deployed(driver, os_target, sysadmin_ai_path)
            result = _run_sysadmin_ai_function(
                driver, "sysadmin_ai.check_command_safety('ls -la')",
                os_name=os_target.name,
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
                driver, "sysadmin_ai.check_command_safety('rm -rf /')",
                os_name=os_target.name,
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
                os_name=os_target.name,
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
                driver, "sysadmin_ai._check_read_safety('/etc/shadow')",
                os_name=os_target.name,
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
                driver, "sysadmin_ai._check_write_safety('/etc/passwd')",
                os_name=os_target.name,
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
                os_name=os_target.name,
            )
            assert "[REDACTED]" in result
            assert "sk-abc123def456ghi789jkl012mno345" not in result
        finally:
            driver.close()

    def test_openai_api_connectivity(
        self, ssh_connect, os_target, sysadmin_ai_path, openai_api_key
    ):
        """Live OpenAI API call via build_client returns a non-empty response."""
        driver = ssh_connect(os_target)
        try:
            _ensure_deployed(driver, os_target, sysadmin_ai_path)
            code = (
                "import sys, json, os, types\n"
                f"sys.path.insert(0, '{REMOTE_DEPLOY_DIR}')\n"
                "import sysadmin_ai\n"
                "args = types.SimpleNamespace(\n"
                "    provider=\"openai\",\n"
                "    api_key=os.environ[\"OPENAI_API_KEY\"],\n"
                "    api_base=None,\n"
                "    model=\"gpt-4o-mini\",\n"
                ")\n"
                "client, model, base_url = sysadmin_ai.build_client(args)\n"
                "resp = client.chat.completions.create(\n"
                "    model=model,\n"
                "    messages=[{\"role\": \"user\", \"content\": \"Say hi\"}],\n"
                "    max_tokens=5,\n"
                ")\n"
                "print(json.dumps(resp.choices[0].message.content))\n"
            )
            result = _run_remote_python(
                driver,
                code,
                env={"OPENAI_API_KEY": openai_api_key},
                os_name=os_target.name,
            )
            assert isinstance(result, str) and len(result) > 0, (
                f"Expected non-empty string from OpenAI, got: {result!r}"
            )
        finally:
            driver.close()
