// the host side of one durable: reads a line, asks the isolate, writes a line back.
// deliberately dumb - serialization and the commit live in python, not here.
const { Worker } = require("node:worker_threads");
const path = require("node:path");
const readline = require("node:readline");

const source = process.env.DURABLE_SOURCE || "";
const worker = new Worker(path.join(__dirname, "isolate.js"), { workerData: { source } });

// one request in, one reply out, in order: the protocol is a queue of size one by construction
worker.on("message", (m) => {
  process.stdout.write(JSON.stringify(m) + "\n");
});

worker.on("error", (e) => {
  process.stdout.write(JSON.stringify({ error: "isolate error: " + e.message }) + "\n");
  process.exit(4);
});

readline.createInterface({ input: process.stdin }).on("line", (line) => {
  if (!line.trim()) return;
  worker.postMessage(JSON.parse(line));
});
