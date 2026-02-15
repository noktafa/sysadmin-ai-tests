import os
from unittest.mock import MagicMock, call, patch

import paramiko
import pytest

from infra.ssh_driver import SSHDriver, generate_keypair


class TestGenerateKeypair:
    def test_generate_keypair_returns_key_and_pubstring(self):
        key, pub = generate_keypair()
        assert isinstance(key, paramiko.RSAKey)
        assert isinstance(pub, str)
        assert pub.startswith("ssh-rsa ")

    def test_generate_keypair_unique(self):
        key1, pub1 = generate_keypair()
        key2, pub2 = generate_keypair()
        assert pub1 != pub2


class TestConnect:
    @patch("infra.ssh_driver.paramiko")
    @patch("infra.ssh_driver.time")
    def test_connect_success(self, mock_time, mock_paramiko):
        mock_time.monotonic.side_effect = [0, 1]
        mock_client = MagicMock()
        mock_paramiko.SSHClient.return_value = mock_client
        mock_paramiko.AutoAddPolicy.return_value = "auto-add"

        key = MagicMock()
        driver = SSHDriver("10.0.0.1", key=key)
        driver.connect(timeout=60)

        mock_client.set_missing_host_key_policy.assert_called_once_with("auto-add")
        mock_client.connect.assert_called_once_with(
            "10.0.0.1", username="root", pkey=key, timeout=10,
        )
        assert driver._client is mock_client

    @patch("infra.ssh_driver.paramiko")
    @patch("infra.ssh_driver.time")
    def test_connect_retries_on_failure(self, mock_time, mock_paramiko):
        # monotonic: start=0, fail check=1, sleep, retry check=2, success check=3
        mock_time.monotonic.side_effect = [0, 1, 2, 3]
        mock_client = MagicMock()
        mock_client.connect.side_effect = [
            ConnectionRefusedError("refused"),
            None,  # success on second attempt
        ]
        mock_paramiko.SSHClient.return_value = mock_client
        mock_paramiko.AutoAddPolicy.return_value = "auto-add"

        key = MagicMock()
        driver = SSHDriver("10.0.0.1", key=key)
        driver.connect(timeout=60, retry_interval=5)

        assert mock_client.connect.call_count == 2
        assert driver._client is mock_client

    @patch("infra.ssh_driver.paramiko")
    @patch("infra.ssh_driver.time")
    def test_connect_timeout(self, mock_time, mock_paramiko):
        # monotonic: start=0, attempt=1, past deadline=999
        mock_time.monotonic.side_effect = [0, 1, 999]
        mock_client = MagicMock()
        mock_client.connect.side_effect = ConnectionRefusedError("refused")
        mock_paramiko.SSHClient.return_value = mock_client
        mock_paramiko.AutoAddPolicy.return_value = "auto-add"

        key = MagicMock()
        driver = SSHDriver("10.0.0.1", key=key)

        with pytest.raises(TimeoutError, match="SSH connection to 10.0.0.1 failed"):
            driver.connect(timeout=60)


class TestRun:
    def _make_connected_driver(self):
        driver = SSHDriver("10.0.0.1", key=MagicMock())
        driver._client = MagicMock()
        return driver

    def test_run_returns_output(self):
        driver = self._make_connected_driver()
        mock_stdout = MagicMock()
        mock_stdout.read.return_value = b"hello world\n"
        mock_stdout.channel.recv_exit_status.return_value = 0
        mock_stderr = MagicMock()
        mock_stderr.read.return_value = b""
        driver._client.exec_command.return_value = (MagicMock(), mock_stdout, mock_stderr)

        result = driver.run("echo hello world")

        assert result["stdout"] == "hello world\n"
        assert result["stderr"] == ""
        assert result["exit_code"] == 0

    def test_run_captures_stderr(self):
        driver = self._make_connected_driver()
        mock_stdout = MagicMock()
        mock_stdout.read.return_value = b""
        mock_stdout.channel.recv_exit_status.return_value = 1
        mock_stderr = MagicMock()
        mock_stderr.read.return_value = b"error: not found\n"
        driver._client.exec_command.return_value = (MagicMock(), mock_stdout, mock_stderr)

        result = driver.run("bad-command")

        assert result["stderr"] == "error: not found\n"

    def test_run_returns_exit_code(self):
        driver = self._make_connected_driver()
        mock_stdout = MagicMock()
        mock_stdout.read.return_value = b""
        mock_stdout.channel.recv_exit_status.return_value = 42
        mock_stderr = MagicMock()
        mock_stderr.read.return_value = b""
        driver._client.exec_command.return_value = (MagicMock(), mock_stdout, mock_stderr)

        result = driver.run("exit 42")

        assert result["exit_code"] == 42

    def test_run_raises_if_not_connected(self):
        driver = SSHDriver("10.0.0.1", key=MagicMock())

        with pytest.raises(RuntimeError, match="Not connected"):
            driver.run("ls")


class TestUpload:
    def _make_connected_driver(self):
        driver = SSHDriver("10.0.0.1", key=MagicMock())
        driver._client = MagicMock()
        return driver

    def test_upload_file(self):
        driver = self._make_connected_driver()
        mock_sftp = MagicMock()
        driver._client.open_sftp.return_value = mock_sftp

        driver.upload_file("/local/file.txt", "/remote/file.txt")

        mock_sftp.put.assert_called_once_with("/local/file.txt", "/remote/file.txt")
        mock_sftp.close.assert_called_once()

    @patch("infra.ssh_driver.os.walk")
    def test_upload_dir_creates_dirs(self, mock_walk):
        driver = self._make_connected_driver()
        mock_sftp = MagicMock()
        driver._client.open_sftp.return_value = mock_sftp

        # Simulate: local_path/ has subdir/ with a file
        mock_walk.return_value = [
            ("/local/project", ["subdir"], ["root.txt"]),
            ("/local/project/subdir", [], ["nested.txt"]),
        ]

        driver.upload_dir("/local/project", "/remote/project")

        # Should mkdir the top-level and subdirectory
        mkdir_calls = mock_sftp.mkdir.call_args_list
        assert call("/remote/project") in mkdir_calls
        assert call("/remote/project/subdir") in mkdir_calls

        # Should put both files (local paths use os.path.join so may have backslashes on Windows)
        put_calls = mock_sftp.put.call_args_list
        assert call(
            os.path.join("/local/project", "root.txt"), "/remote/project/root.txt"
        ) in put_calls
        assert call(
            os.path.join("/local/project/subdir", "nested.txt"),
            "/remote/project/subdir/nested.txt",
        ) in put_calls

        mock_sftp.close.assert_called_once()


class TestClose:
    def test_close_idempotent(self):
        driver = SSHDriver("10.0.0.1", key=MagicMock())
        driver._client = MagicMock()

        driver.close()
        driver.close()  # second call should not raise

        assert driver._client is None

    def test_context_manager(self):
        driver = SSHDriver("10.0.0.1", key=MagicMock())
        mock_client = MagicMock()
        driver._client = mock_client

        with driver:
            pass

        mock_client.close.assert_called_once()
        assert driver._client is None
