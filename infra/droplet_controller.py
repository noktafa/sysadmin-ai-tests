import os
import time
import uuid

import digitalocean


class DropletController:
    TAG = "sysadmin-ai-test"

    def __init__(self, token=None, region="nyc3", size="s-1vcpu-1gb"):
        self.token = token or os.environ.get("DIGITALOCEAN_TOKEN")
        if not self.token:
            raise ValueError(
                "No DigitalOcean token provided. Set DIGITALOCEAN_TOKEN "
                "environment variable or pass token= to constructor."
            )
        self.region = region
        self.size = size
        self.manager = digitalocean.Manager(token=self.token)

    def create(self, image, name=None):
        if name is None:
            short = image.split("-")[0]
            hex_suffix = uuid.uuid4().hex[:4]
            name = f"test-{short}-{hex_suffix}"

        droplet = digitalocean.Droplet(
            token=self.token,
            name=name,
            region=self.region,
            size_slug=self.size,
            image=image,
            tags=[self.TAG],
            ssh_keys=self.manager.get_all_sshkeys(),
        )
        droplet.create()

        return {
            "id": droplet.id,
            "name": droplet.name,
            "status": droplet.status,
            "ip": None,
        }

    def wait_until_ready(self, droplet_id, timeout=300):
        droplet = digitalocean.Droplet(id=droplet_id, token=self.token)
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            droplet.load()
            if droplet.status == "active" and droplet.ip_address:
                return droplet.ip_address
            time.sleep(5)

        raise TimeoutError(
            f"Droplet {droplet_id} not ready after {timeout}s "
            f"(status={droplet.status}, ip={droplet.ip_address})"
        )

    def destroy(self, droplet_id):
        droplet = digitalocean.Droplet(id=droplet_id, token=self.token)
        try:
            droplet.destroy()
        except digitalocean.DataReadError:
            pass
        except digitalocean.NotFoundError:
            pass

    def destroy_all(self, tag=None):
        tag = tag or self.TAG
        droplets = self.manager.get_all_droplets(tag_name=tag)
        for droplet in droplets:
            droplet.destroy()
