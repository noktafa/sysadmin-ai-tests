import pytest

from tests.integration.conftest import os_target_params

REMOTE_DEPLOY_DIR = "/opt/sysadmin-ai"

_setup_done = set()


def _run_setup_once(driver, os_target):
    """Run setup_commands once per OS target, skip on subsequent calls."""
    if os_target.name in _setup_done:
        return
    for cmd in os_target.setup_commands:
        result = driver.run(cmd, timeout=300)
        assert result["exit_code"] == 0, (
            f"Setup command failed on {os_target.name}: {cmd!r}\n"
            f"stdout: {result['stdout']}\nstderr: {result['stderr']}"
        )
    _setup_done.add(os_target.name)


@os_target_params()
@pytest.mark.integration
class TestDeployment:

    def test_setup_commands_succeed(self, ssh_connect, os_target):
        """Each os_target.setup_commands exits 0."""
        driver = ssh_connect(os_target)
        try:
            _run_setup_once(driver, os_target)
        finally:
            driver.close()

    def test_python3_available(self, ssh_connect, os_target):
        """python3 --version works after setup."""
        driver = ssh_connect(os_target)
        try:
            _run_setup_once(driver, os_target)
            result = driver.run("python3 --version")
            assert result["exit_code"] == 0, (
                f"python3 not available on {os_target.name}: {result['stderr']}"
            )
            assert "python" in result["stdout"].lower()
        finally:
            driver.close()

    def test_pip_install_openai(self, ssh_connect, os_target):
        """pip3 install openai succeeds (using os_target.pip_flags)."""
        driver = ssh_connect(os_target)
        try:
            _run_setup_once(driver, os_target)
            pip_cmd = f"pip3 install {os_target.pip_flags} openai".strip()
            result = driver.run(pip_cmd, timeout=300)
            assert result["exit_code"] == 0, (
                f"pip install openai failed on {os_target.name}:\n"
                f"stdout: {result['stdout']}\nstderr: {result['stderr']}"
            )
        finally:
            driver.close()

    def test_upload_sysadmin_ai(self, ssh_connect, os_target, sysadmin_ai_path):
        """upload_dir puts sysadmin_ai.py and soul.md at /opt/sysadmin-ai."""
        driver = ssh_connect(os_target)
        try:
            driver.upload_dir(sysadmin_ai_path, REMOTE_DEPLOY_DIR)

            result = driver.run(
                f"test -f {REMOTE_DEPLOY_DIR}/sysadmin_ai.py && echo OK"
            )
            assert result["exit_code"] == 0, (
                f"sysadmin_ai.py not found at {REMOTE_DEPLOY_DIR} on {os_target.name}"
            )
            assert "OK" in result["stdout"]

            result = driver.run(
                f"test -f {REMOTE_DEPLOY_DIR}/soul.md && echo OK"
            )
            assert result["exit_code"] == 0, (
                f"soul.md not found at {REMOTE_DEPLOY_DIR} on {os_target.name}"
            )
            assert "OK" in result["stdout"]
        finally:
            driver.close()

    def test_import_sysadmin_ai(
        self, ssh_connect, os_target, sysadmin_ai_path, deployment_state
    ):
        """python3 -c 'import sysadmin_ai' works; marks deployment_state."""
        driver = ssh_connect(os_target)
        try:
            _run_setup_once(driver, os_target)
            pip_cmd = f"pip3 install {os_target.pip_flags} openai".strip()
            driver.run(pip_cmd, timeout=300)
            driver.upload_dir(sysadmin_ai_path, REMOTE_DEPLOY_DIR)

            import_cmd = (
                f'python3 -c "import sys; sys.path.insert(0, \'{REMOTE_DEPLOY_DIR}\'); '
                f'import sysadmin_ai; print(\'import OK\')"'
            )
            result = driver.run(import_cmd)
            assert result["exit_code"] == 0, (
                f"sysadmin_ai import failed on {os_target.name}:\n"
                f"stdout: {result['stdout']}\nstderr: {result['stderr']}"
            )
            assert "import OK" in result["stdout"]
            deployment_state.add(os_target.name)
        finally:
            driver.close()
