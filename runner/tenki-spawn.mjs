// spawn a tenki sandbox for a lane and run its boot script to a marker.
// usage: node tenki-spawn.mjs linux
import { readFileSync } from "node:fs";
import { TenkiSandbox, stdoutText } from "@tenkicloud/sandbox";

const lane = process.argv[2] || "linux";
const boot = readFileSync(new URL(`./lanes/${lane}/boot.sh`, import.meta.url), "utf8");

const sandbox = new TenkiSandbox();
console.log(`creating tenki session for lane: ${lane}`);
const session = await sandbox.create({
  name: `spawnables-${lane}-smoke`,
  cpuCores: 4,
  memoryMb: 8192,
  diskSizeGb: 30,
  allowOutbound: true,
  env: { GH: process.env.GITHUB_TOKEN_6 },
  maxDurationMs: 45 * 60 * 1000
});
console.log("session up, writing boot script");
const write = await session.exec(["bash", "-lc", `cat > ~/boot.sh <<'SPAWNABLESEOS'\n${boot}\nSPAWNABLESEOS\nchmod +x ~/boot.sh && echo written`]);
console.log(stdoutText(write).trim());

const start = await session.exec(["bash", "-lc", "nohup bash ~/boot.sh > ~/boot.log 2>&1 & echo bg-started"]);
console.log(stdoutText(start).trim());

const deadline = Date.now() + 28 * 60 * 1000;
let lastTail = "";
while (Date.now() < deadline) {
  await new Promise(r => setTimeout(r, 45000));
  const poll = await session.exec(["bash", "-lc", "tail -c 1500 ~/boot.log"]);
  const tail = stdoutText(poll);
  if (tail !== lastTail) {
    console.log("--- vm log ---");
    console.log(tail.trim());
    lastTail = tail;
  }
  const done = await session.exec(["bash", "-lc", "grep -c 'SPAWNABLESOK\\|SPAWNABLESFAIL' ~/boot.log || true"]);
  if (stdoutText(done).trim() !== "0") break;
}
const verdict = await session.exec(["bash", "-lc", "grep -E 'SPAWNABLESOK|SPAWNABLESFAIL' ~/boot.log || echo NO-MARKER-TIMEOUT"]);
console.log("VERDICT: " + stdoutText(verdict).trim());
const guestlog = await session.exec(["bash", "-lc", "tail -40 ~/provision.log 2>/dev/null || true"]);
if (stdoutText(guestlog).trim()) {
  console.log("--- provision.log tail ---");
  console.log(stdoutText(guestlog).trim());
}
await session.close();
console.log("session closed");
