import pytest

from infra.os_matrix import get_all
from tests.integration.conftest import os_target_params


@os_target_params()
@pytest.mark.integration
class TestConnectivity:

    def test_ssh_and_uname(self, ssh_connect, os_target):
        """SSH connects and 'uname -a' exits 0 with non-empty output."""
        driver = ssh_connect(os_target)
        try:
            result = driver.run("uname -a")
            assert result["exit_code"] == 0
            assert result["stdout"].strip(), "uname output should not be empty"
        finally:
            driver.close()

    def test_os_family_matches(self, ssh_connect, os_target):
        """
        /etc/os-release contains expected family identifiers.
        Debian-family: 'debian' or 'ubuntu'
        RHEL-family: 'rhel' or 'centos' or 'fedora' or 'rocky' or 'almalinux'
        """
        driver = ssh_connect(os_target)
        try:
            result = driver.run("cat /etc/os-release")
            assert result["exit_code"] == 0
            content = result["stdout"].lower()

            if os_target.family == "debian":
                assert "debian" in content or "ubuntu" in content, (
                    f"Expected debian/ubuntu in os-release for {os_target.name}"
                )
            elif os_target.family == "rhel":
                rhel_ids = ("rhel", "centos", "fedora", "rocky", "almalinux")
                assert any(rid in content for rid in rhel_ids), (
                    f"Expected RHEL-family identifier in os-release for {os_target.name}"
                )
        finally:
            driver.close()

    def test_pkg_manager_available(self, ssh_connect, os_target):
        """'which apt' or 'which dnf' exits 0."""
        driver = ssh_connect(os_target)
        try:
            result = driver.run(f"which {os_target.pkg_manager}")
            assert result["exit_code"] == 0, (
                f"{os_target.pkg_manager} not found on {os_target.name}: "
                f"{result['stderr']}"
            )
        finally:
            driver.close()

    def test_systemctl_available(self, ssh_connect, os_target):
        """'systemctl --version' exits 0."""
        driver = ssh_connect(os_target)
        try:
            result = driver.run("systemctl --version")
            assert result["exit_code"] == 0, (
                f"systemctl not available on {os_target.name}: {result['stderr']}"
            )
        finally:
            driver.close()
