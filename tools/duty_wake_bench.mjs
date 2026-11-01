// measure the wake of a sleeping guest: pause -> resume -> a command that returned output.
// the duty tier claims "the guest sleeps, the promise does not", so the number that matters is not
// resume alone, it is resume plus the first command coming back, because that is when the machine is
// actually usable. second question, equally load-bearing: does memory survive at all? a background
// process holding a counter in a shell variable answers it. if the counter keeps climbing, the
// session resumed; if the process is gone, it booted, and the tier must not claim continuity.
//
// usage: TENKI_API_KEY=... node tools/duty_wake_bench.mjs -n 12 [--cpu 2 --mem 3072 --disk 30]
// output: one json object on stdout, and a readable table on stderr. no numbers invented.
import { TenkiSandbox, stdoutText } from "@tenkicloud/sandbox";

function arg(name, dflt) {
  const i = process.argv.indexOf(name);
  return i === -1 ? dflt : process.argv[i + 1];
}
const N = Number(arg("-n", 12));
const cpuCores = Number(arg("--cpu", 2));
const memoryMb = Number(arg("--mem", 3072));
const diskSizeGb = Number(arg("--disk", 30));

const pct = (xs, q) => {
  const s = [...xs].sort((a, b) => a - b);
  return s[Math.min(s.length - 1, Math.max(0, Math.ceil(q * s.length) - 1))];
};

const sandbox = new TenkiSandbox();
const session = await sandbox.create({
  name: `spawnables-duty-wake-${Date.now()}`,
  cpuCores, memoryMb, diskSizeGb,
  allowOutbound: false,
  maxDurationMs: 20 * 60 * 1000,
});
await session.waitReady(240000).catch(() => {});

const sh = async (cmd) => stdoutText(await session.exec(["bash", "-lc", cmd])).trim();

// warm the guest and start the experiment. MEMORY_EPOCH is a shell variable, so only a resumed
// (not rebooted) guest still has it, and the pid only exists if the process was never killed.
await sh("echo warm; nproc; free -m | head -2");
await sh("nohup bash -lc 'EPOCH=$RANDOM; echo $EPOCH > /tmp/epoch; i=0; while true; do i=$((i+1)); echo $i > /tmp/counter; sleep 0.2; done' > /tmp/bg.log 2>&1 & echo $! > /tmp/bg.pid");
await new Promise((r) => setTimeout(r, 1200));

const warmExec = [];
for (let i = 0; i < 5; i++) {
  const t = performance.now();
  await sh("true");
  warmExec.push(performance.now() - t);
}

const epochBefore = await sh("cat /tmp/epoch");
const rows = [];
for (let i = 0; i < N; i++) {
  const counterBefore = Number(await sh("cat /tmp/counter"));
  const t0 = performance.now();
  await session.pause();
  await session.waitPaused(120000);
  const paused = performance.now() - t0;

  const t1 = performance.now();
  await session.resume();
  await session.waitResumed(180000);
  const resumed = performance.now() - t1;

  const t2 = performance.now();
  const out = await sh("echo awake");
  const firstExec = performance.now() - t2;

  const counterAfter = Number(await sh("cat /tmp/counter"));
  const alive = (await sh("kill -0 $(cat /tmp/bg.pid) 2>/dev/null && echo yes || echo no")) === "yes";
  const epochAfter = await sh("cat /tmp/epoch");
  rows.push({
    iteration: i + 1,
    pause_ms: Math.round(paused),
    resume_ms: Math.round(resumed),
    wake_ms: Math.round(resumed + firstExec),
    first_exec_ok: out === "awake",
    memory_survived: alive && epochAfter === epochBefore && counterAfter > counterBefore,
    counter_before: counterBefore,
    counter_after: counterAfter,
    pid_alive: alive,
  });
  console.error(`  #${i + 1} pause ${rows.at(-1).pause_ms}ms resume ${rows.at(-1).resume_ms}ms ` +
                `wake ${rows.at(-1).wake_ms}ms memory ${rows.at(-1).memory_survived}`);
}

const wakes = rows.map((r) => r.wake_ms);
const resumes = rows.map((r) => r.resume_ms);
const pauses = rows.map((r) => r.pause_ms);
const verdict = {
  host: { kind: "tenki sandbox", cpuCores, memoryMb, diskSizeGb },
  measured_at: new Date().toISOString(),
  iterations: N,
  wake_ms: { p50: pct(wakes, 0.5), p95: pct(wakes, 0.95), max: Math.max(...wakes) },
  resume_ms: { p50: pct(resumes, 0.5), p95: pct(resumes, 0.95), max: Math.max(...resumes) },
  pause_ms: { p50: pct(pauses, 0.5), p95: pct(pauses, 0.95), max: Math.max(...pauses) },
  warm_exec_ms: { p50: pct(warmExec, 0.5), p95: pct(warmExec, 0.95) },
  memory_survived_every_time: rows.every((r) => r.memory_survived),
  first_exec_ok_every_time: rows.every((r) => r.first_exec_ok),
  fidelity: rows.every((r) => r.memory_survived) ? "memory" : "disk (a boot: no continuity claim allowed)",
  rows,
};
console.log(JSON.stringify(verdict, null, 2));
console.error(`\nwake p50 ${verdict.wake_ms.p50}ms p95 ${verdict.wake_ms.p95}ms, ` +
              `memory survived ${verdict.memory_survived_every_time}, fidelity ${verdict.fidelity}`);
await session.close();
