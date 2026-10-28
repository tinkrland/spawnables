#!/usr/bin/env bash
# build a desktop rootfs tarball for one base image id, e.g.:
#   ./build-rootfs.sh mint-22-cinnamon
# docker build -> docker export -> tar.zst at images/<id>-rootfs.tar.zst.
# refuses honestly when there is no docker on this host.
set -u
id="${1:?usage: build-rootfs.sh <base-image-id>}"
df="$(dirname "$0")/${id}.Dockerfile"
[ -f "$df" ] || { echo "ROOTFSFAIL no dockerfile for ${id}"; exit 1; }
if ! command -v docker >/dev/null 2>&1; then
  echo "ROOTFSNEEDSDOCKER build-rootfs.sh needs docker on this host; the definitions in rootfs/ run on a provision host"
  exit 1
fi
tag="spawnables-rootfs:${id}"
docker build -t "$tag" -f "$df" "$(dirname "$0")" || { echo "ROOTFSFAIL docker build"; exit 1; }
mkdir -p images
c=$(docker create "$tag")
docker export "$c" | zstd -T0 -o "images/${id}-rootfs.tar.zst" || { docker rm -f "$c"; echo "ROOTFSFAIL export"; exit 1; }
docker rm -f "$c"
echo "ROOTFSOK images/${id}-rootfs.tar.zst"
