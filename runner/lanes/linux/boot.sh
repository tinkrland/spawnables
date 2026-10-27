#!/usr/bin/env bash
# the linux lane boot script: runs INSIDE a tenki sandbox vm.
# installs celesto, pulls the published ubuntu preset, and drives the
# spawnables provisioner against a real guest.
set -u
S() { if command -v sudo >/dev/null 2>&1; then sudo -n "$@"; else "$@"; fi; }
log() { echo "== $*"; }
export DEBIAN_FRONTEND=noninteractive

log "host: $(uname -a)"
[ -e /dev/kvm ] && log "kvm: present" || log "kvm: absent (qemu falls back to software emulation)"

log "system deps"
S apt-get update -qq 2>&1 | tail -1
S apt-get install -y -qq python3 python3-venv python3-pip git qemu-system-x86 qemu-utils zstd 2>&1 | tail -1

log "celesto install"
python3 -m venv "$HOME/venv"
"$HOME/venv/bin/pip" install -q --upgrade pip
"$HOME/venv/bin/pip" install -q celesto || { echo "SPAWNABLESFAIL pip-celesto"; exit 1; }
"$HOME/venv/bin/celesto" --version

if [ ! -e /dev/kvm ]; then
  log "no /dev/kvm: applying the tcg patch to celesto (software emulation, slow but real)"
  QA="$HOME/venv/lib/python3*/site-packages/celesto/runtime/qemu_args.py"
  sed -i 's|q35,accel=kvm", "host"|q35,accel=tcg", "max"|' $QA
  sed -i 's|microvm,accel=kvm|microvm,accel=tcg|' $QA
  sed -i 's|"-cpu", "host"|"-cpu", "max"|g' $QA
  grep -q 'accel=tcg' $QA && log "tcg patch applied" || { echo "SPAWNABLESFAIL tcg-patch"; exit 1; }
  export SPAWNABLES_BOOT_TIMEOUT=900
fi

log "clone spawnables"
cd "$HOME" && rm -rf spawnables
git clone -q "https://x-access-token:${GH}@github.com/tinkrland/spawnables.git" || { echo "SPAWNABLESFAIL clone"; exit 1; }
cd spawnables

log "provisioner against real celesto (ubuntu preset, apt git, fresh-point snapshot)"
[ -n "${SPAWNABLES_BOOT_TIMEOUT:-}" ] && log "boot timeout: ${SPAWNABLES_BOOT_TIMEOUT}s (tcg)"
PYTHONPATH=src SPAWNABLES_BOOT_TIMEOUT="${SPAWNABLES_BOOT_TIMEOUT:-30}" "$HOME/venv/bin/python" -m spawnables --catalog catalog provision orders/ubuntu-headless-smoke.json > "$HOME/provision.log" 2>&1
code=$?
tail -25 "$HOME/provision.log"
if [ $code -eq 0 ]; then
  echo "SPAWNABLESOK"
else
  echo "SPAWNABLESFAIL provision"
  log "celesto logs for debugging"
  find "$HOME/.local/share/celesto" -name "*.log" -mmin -20 2>/dev/null | while read -r f; do echo "--- $f"; tail -15 "$f"; done
fi
