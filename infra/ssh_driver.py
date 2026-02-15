import io
import os
import time

import paramiko


def generate_keypair():
    """
    Generate an ephemeral RSA keypair for test SSH access.
    Returns (private_key: paramiko.RSAKey, public_key_str: str)
    The public_key_str is in OpenSSH format for DigitalOcean API registration.
    """
    key = paramiko.RSAKey.generate(4096)
    pub_parts = f"{key.get_name()} {key.get_base64()}"
    return key, pub_parts


class SSHDriver:
    def __init__(self, host, username="root", key=None, key_path=None):
        """
        host: IP address of the droplet
        username: default "root" (DigitalOcean default)
        key: paramiko.RSAKey object (ephemeral key)
        key_path: path to private key file (alternative to key)
        One of key or key_path must be provided.
        """
        if key is None and key_path is None:
            raise ValueError("One of key or key_path must be provided")
        self.host = host
        self.username = username
        self.key = key
        self.key_path = key_path
        self._client = None

    def connect(self, timeout=60, retry_interval=5):
        """
        Connect to the host via SSH. Retries until timeout because
        freshly-created droplets may not have SSH ready immediately
        even after status=active. Raises TimeoutError on failure.
        """
        pkey = self.key
        if pkey is None:
            pkey = paramiko.RSAKey.from_private_key_file(self.key_path)

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        deadline = time.monotonic() + timeout
        last_error = None

        while time.monotonic() < deadline:
            try:
                client.connect(
                    self.host,
                    username=self.username,
                    pkey=pkey,
                    timeout=10,
                )
                self._client = client
                return
            except Exception as exc:
                last_error = exc
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                time.sleep(min(retry_interval, remaining))

        raise TimeoutError(
            f"SSH connection to {self.host} failed after {timeout}s: {last_error}"
        )

    def run(self, command, timeout=120):
        """
        Execute a command on the remote host.
        Returns dict: {"stdout": str, "stderr": str, "exit_code": int}
        Raises RuntimeError if not connected.
        """
        if self._client is None:
            raise RuntimeError("Not connected. Call connect() first.")

        stdin, stdout, stderr = self._client.exec_command(command, timeout=timeout)
        exit_code = stdout.channel.recv_exit_status()
        return {
            "stdout": stdout.read().decode(),
            "stderr": stderr.read().decode(),
            "exit_code": exit_code,
        }

    def upload_file(self, local_path, remote_path):
        """
        Upload a single file via SFTP.
        """
        if self._client is None:
            raise RuntimeError("Not connected. Call connect() first.")

        sftp = self._client.open_sftp()
        try:
            sftp.put(local_path, remote_path)
        finally:
            sftp.close()

    def upload_dir(self, local_path, remote_path):
        """
        Recursively upload a local directory to the remote host via SFTP.
        Creates remote directories as needed.
        """
        if self._client is None:
            raise RuntimeError("Not connected. Call connect() first.")

        sftp = self._client.open_sftp()
        try:
            self._mkdir_p(sftp, remote_path)
            for root, dirs, files in os.walk(local_path):
                rel_root = os.path.relpath(root, local_path)
                if rel_root == ".":
                    remote_root = remote_path
                else:
                    remote_root = remote_path + "/" + rel_root.replace("\\", "/")

                for d in dirs:
                    remote_dir = remote_root + "/" + d
                    self._mkdir_p(sftp, remote_dir)

                for f in files:
                    local_file = os.path.join(root, f)
                    remote_file = remote_root + "/" + f
                    sftp.put(local_file, remote_file)
        finally:
            sftp.close()

    @staticmethod
    def _mkdir_p(sftp, remote_path):
        """Create remote directory, ignoring errors if it already exists."""
        try:
            sftp.mkdir(remote_path)
        except IOError:
            pass

    def close(self):
        """
        Close the SSH connection. Idempotent.
        """
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
