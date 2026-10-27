import { TenkiSandbox, stdoutText } from "@tenkicloud/sandbox";
const VM = `set -u
S() { if command -v sudo >/dev/null 2>&1; then sudo -n "$@"; else "$@"; fi; }
log() { echo "== $*"; }
export DEBIAN_FRONTEND=noninteractive
S apt-get update -qq 2>&1 | tail -1
S apt-get install -y -qq python3 python3-venv python3-pip git qemu-system-x86 qemu-utils zstd 2>&1 | tail -1
python3 -m venv ~/venv
~/venv/bin/pip install -q --upgrade pip
~/venv/bin/pip install -q celesto || { echo FAILPIPE; exit 1; }
QA="$(echo ~/venv/lib/python3*/site-packages/celesto/runtime/qemu_args.py)"
sed -i 's|q35,accel=kvm", "host"|q35,accel=tcg", "max"|' $QA
sed -i 's|microvm,accel=kvm|microvm,accel=tcg|' $QA
log "patch check:"; grep -n "accel=tcg" $QA | head -3
cat > ~/dbg.py <<'PYEOF'
from pathlib import Path
from celesto import Celesto
import traceback
home = Path.home()
try:
    c = Celesto(os="ubuntu", backend="qemu", data_dir=home / "cdata")
    print("constructed, starting (tcg, 600s budget)")
    c.start(boot_timeout=600)
    print("BOOTED")
    r = c.run("uname -a && cat /etc/os-release | head -2")
    print("GUEST:", r.stdout.strip()[:200])
    c.stop()
    print("STOPPED-OK")
except Exception as e:
    print("STARTFAIL:", e)
    for f in sorted((home / "cdata").glob("*.log")):
        print(f"--- {f.name} (last 30) ---")
        print("\\n".join(f.read_text().splitlines()[-30:]))
PYEOF
PYTHONPATH= ~/venv/bin/python ~/dbg.py 2>&1 | tail -60
echo "EXITMARKER $?"
`;
const s = new TenkiSandbox();
const sess = await s.create({ name: "spawnables-qemu-debug", cpuCores: 4, memoryMb: 8192,
  diskSizeGb: 30, allowOutbound: true, maxDurationMs: 40 * 60 * 1000 });
console.log("session up");
const w = await sess.exec(["bash", "-lc", `cat > ~/dbg.sh <<'DBGEOS'\n${VM}\nDBGEOS\nnohup bash ~/dbg.sh > ~/dbg.log 2>&1 & echo bg`]);
console.log(stdoutText(w).trim());
let last = "";
const deadline = Date.now() + 30 * 60 * 1000;
while (Date.now() < deadline) {
  await new Promise(r => setTimeout(r, 45000));
  const p = await sess.exec(["bash", "-lc", "tail -c 2000 ~/dbg.log"]);
  const t = stdoutText(p);
  if (t !== last) { console.log("--- vm ---"); console.log(t.trim()); last = t; }
  const d = await sess.exec(["bash", "-lc", "grep -c 'BOOTED\\|STOPPED-OK\\|STARTFAIL\\|FAILPIPE' ~/dbg.log || true"]);
  if (stdoutText(d).trim() !== "0") break;
}
const v = await sess.exec(["bash", "-lc", "grep -E 'BOOTED|STOPPED-OK|STARTFAIL|FAILPIPE|EXITMARKER' ~/dbg.log || echo NO-MARKER"]);
console.log("VERDICT: " + stdoutText(v).trim());
await sess.close();
