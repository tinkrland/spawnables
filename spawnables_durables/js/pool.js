// one process, many isolates: the pool that replaces a node process per actor.
//
// a worker_thread is an isolate. a process is a lot more than an isolate - its own address space,
// its own startup cost, its own pid to reap - so serving eight actors used to mean eight processes.
// this host keeps one process and spawns workers inside it, which is what an isolate pool is.
//
// the rules stay the same as the single-isolate host:
//   one worker per actor at a time, and a worker belongs to one actor for its whole life
//   releasing a worker terminates the isolate: the isolate is a cache, so there is nothing to keep
//   a ceiling is a refusal, not a queue: a caller learns the pool is full instead of waiting forever
//
// the protocol is one request and one reply at a time, serialized by the caller. that is not a
// limitation to hide: concurrency lives inside the isolates, not in this pipe, and a pipe that
// pretended otherwise would interleave two actors' state into one reply.
const { Worker } = require("node:worker_threads");
const path = require("node:path");
const readline = require("node:readline");

const MAX = parseInt(process.env.POOL_MAX || "8", 10);
const IDLE_MS = parseInt(process.env.POOL_IDLE_MS || "60000", 10);

let nextId = 1;
const workers = new Map();   // id -> { worker, actor, last, spawned }
const byActor = new Map();   // actor -> id
const stats = { spawned: 0, released: 0, refused: 0, served: 0 };

function reply(msg) {
  process.stdout.write(JSON.stringify(msg) + "\n");
}

function spawn(actor, source) {
  if (workers.size >= MAX) {
    stats.refused += 1;
    return { error: `pool is full: ${workers.size} isolates in this process, ceiling ${MAX}. ` +
                    `raise POOL_MAX or release an actor; a durable call does not queue forever`,
             code: "ceiling" };
  }
  const id = nextId++;
  const worker = new Worker(path.join(__dirname, "isolate.js"), { workerData: { source } });
  const rec = { worker, actor, last: Date.now(), spawned: Date.now() };
  workers.set(id, rec);
  byActor.set(actor, id);
  stats.spawned += 1;
  // an isolate answers asynchronously, so the reply is written the moment it arrives: blocking here
  // to wait for it would stop the very event that carries the answer
  worker.on("message", (m) => {
    stats.served += 1;
    reply(m);
  });
  worker.on("error", (e) => reply({ error: "isolate error: " + e.message }));
  return { worker: id };
}

function handle(msg) {
  if (msg.op === "acquire") {
    const existing = byActor.get(msg.actor);
    if (existing !== undefined && workers.has(existing)) {
      return { worker: existing, reused: true };
    }
    const got = spawn(msg.actor, msg.source || "");
    if (got.error) return got;
    return { worker: got.worker, reused: false };
  }
  if (msg.op === "call") {
    const rec = workers.get(msg.worker);
    if (!rec) return { error: `no worker ${msg.worker}: released or never spawned` };
    rec.last = Date.now();
    rec.worker.postMessage({ state: msg.state, method: msg.method, args: msg.args });
    return null;                       // the isolate's message is the reply, written when it lands
  }
  if (msg.op === "release") {
    const rec = workers.get(msg.worker);
    if (!rec) return { released: null };
    workers.delete(msg.worker);
    if (byActor.get(rec.actor) === msg.worker) byActor.delete(rec.actor);
    rec.worker.terminate();
    stats.released += 1;
    return { released: msg.worker };
  }
  if (msg.op === "sweep") {
    const now = msg.now || Date.now();
    const evicted = [];
    for (const [id, rec] of workers) {
      if (now - rec.last >= IDLE_MS) {
        workers.delete(id);
        if (byActor.get(rec.actor) === id) byActor.delete(rec.actor);
        rec.worker.terminate();
        stats.released += 1;
        evicted.push(id);
      }
    }
    return { evicted };
  }
  if (msg.op === "stats") {
    return { pid: process.pid, workers: workers.size, max: MAX, idle_ms: IDLE_MS,
             actors: [...workers.entries()].map(([id, r]) => ({ worker: id, actor: r.actor })),
             ...stats };
  }
  if (msg.op === "stop") {
    for (const [, rec] of workers) rec.worker.terminate();
    reply({ stopped: true, ...stats });
    process.exit(0);
  }
  return { error: `no op ${msg.op}` };
}

const rl = readline.createInterface({ input: process.stdin });

// a pool whose caller is gone has nothing to serve. without this, a killed python process leaves
// this node process holding isolates with nobody to answer, which was measured before it was fixed.
rl.on("close", () => {
  for (const [, rec] of workers) rec.worker.terminate();
  process.exit(0);
});

rl.on("line", (line) => {
  if (!line.trim()) return;
  let msg;
  try {
    msg = JSON.parse(line);
  } catch (e) {
    reply({ error: "that line is not json" });
    return;
  }
  const out = handle(msg);
  if (out !== null) reply(out);
});
