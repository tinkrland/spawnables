
const { parentPort, workerData } = require("node:worker_threads");
const vm = require("node:vm");
const ctx = vm.createContext({ console });
let actor = null;
try {
  const module = { exports: {} };
  const src = workerData.source + "\n;globalThis.__actor = module.exports;";
  vm.runInContext(src, ctx, { filename: "actor.js" });
  actor = ctx.__actor;
} catch (e) {
  parentPort.postMessage({ error: "actor module failed to load: " + e.message });
}
parentPort.on("message", (m) => {
  try {
    if (!actor || typeof actor.handle !== "function") {
      throw new Error("actor module must export handle(state, method, args) -> {state, out}");
    }
    const got = actor.handle(m.state, m.method, m.args);
    parentPort.postMessage({ state: got.state, out: got.out === undefined ? null : got.out });
  } catch (e) {
    parentPort.postMessage({ error: String(e && e.message || e) });
  }
});
