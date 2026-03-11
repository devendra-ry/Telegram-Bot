import { performance } from "perf_hooks";

const iterations = 10000000;

process.env.TELEGRAM_WEBHOOK_SECRET = "some_test_secret_value_for_benchmarking";

console.log(`Running benchmark with ${iterations} iterations...`);

// Test 1: Reading from process.env on every iteration
const start1 = performance.now();
let dummy1 = "";
for (let i = 0; i < iterations; i++) {
  dummy1 = process.env.TELEGRAM_WEBHOOK_SECRET || "";
}
const end1 = performance.now();
const time1 = end1 - start1;

// Test 2: Reading from a cached variable
let cachedSecret = process.env.TELEGRAM_WEBHOOK_SECRET || "";
const start2 = performance.now();
let dummy2 = "";
for (let i = 0; i < iterations; i++) {
  dummy2 = cachedSecret;
}
const end2 = performance.now();
const time2 = end2 - start2;

console.log(`\nResults:`);
console.log(`1. process.env read: ${time1.toFixed(2)} ms`);
console.log(`2. cached variable:  ${time2.toFixed(2)} ms`);
console.log(`\nImprovement: ${((time1 - time2) / time1 * 100).toFixed(2)}% faster`);
console.log(`Speedup multiplier: ${(time1 / time2).toFixed(2)}x`);
