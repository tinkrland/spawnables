# mint 22 cinnamon rootfs (the distro-selection promise, made concrete).
# base verified on docker hub 2026-10-28: linuxmintd/mint22-amd64:latest.
# built on a provision host with docker via build-rootfs.sh; the sandbox
# has no docker, so this file is the build definition, honestly not run here.
from linuxmintd/mint22-amd64:latest
env DEBIAN_FRONTEND=noninteractive
run apt-get update && apt-get install -y --no-install-recommends \
      cinnamon-core xorg lightdm dbus-x11 sudo zstd ca-certificates \
    && apt-get clean \
    && find /var/lib/apt/lists /tmp -mindepth 1 -delete
cmd ["/sbin/init"]
