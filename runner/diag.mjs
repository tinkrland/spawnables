import { TenkiSandbox, stdoutText } from "@tenkicloud/sandbox";
const s = new TenkiSandbox();
const sess = await s.create({ name: "spawnables-kvm-diag", cpuCores: 2, memoryMb: 2048,
  diskSizeGb: 10, allowOutbound: true, maxDurationMs: 10 * 60 * 1000 });
for (const cmd of [
  "uname -a; ls -l /dev/kvm 2>&1; egrep -c '(vmx|svm)' /proc/cpuinfo",
  "qemu-system-x86_64 --version 2>/dev/null || echo no-qemu",
  "id; groups"
]) {
  const r = await sess.exec(["bash", "-lc", cmd]);
  console.log(stdoutText(r).trim());
}
await sess.close();
