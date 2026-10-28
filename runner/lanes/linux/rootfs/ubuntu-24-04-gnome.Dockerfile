# ubuntu 24.04 gnome rootfs (verified on docker hub 2026-10-28: library/ubuntu:24.04).
from ubuntu:24.04
env DEBIAN_FRONTEND=noninteractive
run apt-get update && apt-get install -y --no-install-recommends \
      gnome-shell gdm3 xorg dbus-x11 sudo zstd ca-certificates \
    && apt-get clean \
    && find /var/lib/apt/lists /tmp -mindepth 1 -delete
cmd ["/sbin/init"]
