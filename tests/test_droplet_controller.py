import re
from unittest.mock import MagicMock, patch

import pytest

from infra.droplet_controller import DropletController


TOKEN = "test-token-abc123"


@pytest.fixture
def controller():
    with patch("infra.droplet_controller.digitalocean") as mock_do:
        mock_do.Manager.return_value.get_all_sshkeys.return_value = []
        ctrl = DropletController(token=TOKEN)
        ctrl._mock_do = mock_do
        yield ctrl


class TestCreate:
    def test_create_returns_droplet_info(self, controller):
        mock_droplet = MagicMock()
        mock_droplet.id = 12345
        mock_droplet.name = "test-ubuntu-a3f8"
        mock_droplet.status = "new"
        controller._mock_do.Droplet.return_value = mock_droplet

        result = controller.create("ubuntu-22-04-x64")

        assert result["id"] == 12345
        assert result["name"] == "test-ubuntu-a3f8"
        assert result["status"] == "new"
        assert result["ip"] is None
        mock_droplet.create.assert_called_once()

    def test_create_auto_generates_name(self, controller):
        mock_droplet = MagicMock()
        mock_droplet.id = 1
        mock_droplet.status = "new"
        controller._mock_do.Droplet.return_value = mock_droplet

        controller.create("ubuntu-22-04-x64")

        call_kwargs = controller._mock_do.Droplet.call_args
        name = call_kwargs.kwargs.get("name") or call_kwargs[1].get("name")
        assert re.match(r"^test-ubuntu-[0-9a-f]{4}$", name)

    def test_create_tags_droplet(self, controller):
        mock_droplet = MagicMock()
        mock_droplet.id = 1
        mock_droplet.status = "new"
        controller._mock_do.Droplet.return_value = mock_droplet

        controller.create("ubuntu-22-04-x64")

        call_kwargs = controller._mock_do.Droplet.call_args
        tags = call_kwargs.kwargs.get("tags") or call_kwargs[1].get("tags")
        assert "sysadmin-ai-test" in tags

    def test_create_with_custom_name(self, controller):
        mock_droplet = MagicMock()
        mock_droplet.id = 1
        mock_droplet.name = "my-custom-name"
        mock_droplet.status = "new"
        controller._mock_do.Droplet.return_value = mock_droplet

        result = controller.create("ubuntu-22-04-x64", name="my-custom-name")

        call_kwargs = controller._mock_do.Droplet.call_args
        name = call_kwargs.kwargs.get("name") or call_kwargs[1].get("name")
        assert name == "my-custom-name"
        assert result["name"] == "my-custom-name"


class TestWaitUntilReady:
    def test_wait_until_ready_returns_ip(self, controller):
        mock_droplet = MagicMock()
        mock_droplet.status = "active"
        mock_droplet.ip_address = "10.0.0.1"
        controller._mock_do.Droplet.return_value = mock_droplet

        with patch("infra.droplet_controller.time") as mock_time:
            mock_time.monotonic.side_effect = [0, 1]
            ip = controller.wait_until_ready(12345)

        assert ip == "10.0.0.1"
        mock_droplet.load.assert_called_once()

    def test_wait_until_ready_polls_until_active(self, controller):
        mock_droplet = MagicMock()
        # First load: still new, no IP. Second load: active with IP.
        mock_droplet.status = "new"
        mock_droplet.ip_address = None

        def become_active():
            mock_droplet.status = "active"
            mock_droplet.ip_address = "10.0.0.2"

        mock_droplet.load.side_effect = [None, become_active()]
        controller._mock_do.Droplet.return_value = mock_droplet

        with patch("infra.droplet_controller.time") as mock_time:
            # monotonic: start, check1 (still new), sleep, check2 (active)
            mock_time.monotonic.side_effect = [0, 1, 2, 3]
            ip = controller.wait_until_ready(12345, timeout=300)

        assert ip == "10.0.0.2"

    def test_wait_until_ready_timeout(self, controller):
        mock_droplet = MagicMock()
        mock_droplet.status = "new"
        mock_droplet.ip_address = None
        controller._mock_do.Droplet.return_value = mock_droplet

        with patch("infra.droplet_controller.time") as mock_time:
            # First call sets deadline, second call exceeds it
            mock_time.monotonic.side_effect = [0, 999]
            with pytest.raises(TimeoutError):
                controller.wait_until_ready(12345, timeout=300)


class TestDestroy:
    def test_destroy_calls_destroy(self, controller):
        mock_droplet = MagicMock()
        controller._mock_do.Droplet.return_value = mock_droplet

        controller.destroy(12345)

        controller._mock_do.Droplet.assert_called_with(id=12345, token=TOKEN)
        mock_droplet.destroy.assert_called_once()

    def test_destroy_idempotent_on_not_found(self, controller):
        mock_droplet = MagicMock()
        mock_droplet.destroy.side_effect = controller._mock_do.NotFoundError
        controller._mock_do.Droplet.return_value = mock_droplet

        # Should not raise
        controller.destroy(12345)

    def test_destroy_idempotent_on_data_read_error(self, controller):
        mock_droplet = MagicMock()
        mock_droplet.destroy.side_effect = controller._mock_do.DataReadError
        controller._mock_do.Droplet.return_value = mock_droplet

        # Should not raise
        controller.destroy(12345)


class TestDestroyAll:
    def test_destroy_all_by_tag(self, controller):
        d1 = MagicMock()
        d2 = MagicMock()
        controller.manager.get_all_droplets.return_value = [d1, d2]

        controller.destroy_all()

        controller.manager.get_all_droplets.assert_called_with(
            tag_name="sysadmin-ai-test"
        )
        d1.destroy.assert_called_once()
        d2.destroy.assert_called_once()

    def test_destroy_all_custom_tag(self, controller):
        controller.manager.get_all_droplets.return_value = []

        controller.destroy_all(tag="custom-tag")

        controller.manager.get_all_droplets.assert_called_with(tag_name="custom-tag")


class TestAuth:
    def test_missing_token_raises(self):
        with patch("infra.droplet_controller.digitalocean"):
            with patch.dict("os.environ", {}, clear=True):
                with pytest.raises(ValueError, match="No DigitalOcean token"):
                    DropletController(token=None)

    def test_token_from_env(self):
        with patch("infra.droplet_controller.digitalocean") as mock_do:
            with patch.dict("os.environ", {"DIGITALOCEAN_TOKEN": "env-token"}):
                ctrl = DropletController()
                assert ctrl.token == "env-token"

    def test_explicit_token_overrides_env(self):
        with patch("infra.droplet_controller.digitalocean") as mock_do:
            with patch.dict(
                "os.environ", {"DIGITALOCEAN_TOKEN": "env-token"}
            ):
                ctrl = DropletController(token="explicit-token")
                assert ctrl.token == "explicit-token"
