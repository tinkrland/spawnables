// the isolate itself: one worker_thread, its own v8 isolate and heap, evaluating the actor module.
const { parentPort, workerData } = require("node:worker_threads");
const vm = require("node:vm");

// a commonjs-shaped sandbox: the actor module writes module.exports, exactly as it would in node
const sandbox = { module: { exports: {} }, console };
vm.createContext(sandbox);
let actor = null;
try {
  vm.runInContext(workerData.source, sandbox, { filename: "actor.js" });
  actor = sandbox.module.exports;
} catch (e) {
  parentPort.postMessage({ error: "actor module failed to load: " + e.message });
}

parentPort.on("message", (m) => {
  try {
    if (!actor || typeof actor.handle !== "function") {
      throw new Error("actor module must export handle(state, method, args) -> {state, out}");
    }
    const got = actor.handle(m.state, m.method, m.args) || {};
    parentPort.postMessage({ state: got.state === undefined ? m.state : got.state,
                             out: got.out === undefined ? null : got.out });
  } catch (e) {
    parentPort.postMessage({ error: String((e && e.message) || e) });
  }
});
