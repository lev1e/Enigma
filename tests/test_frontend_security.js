"use strict";
// Execute the production renderers with a minimal text-node DOM adapter.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const root = path.resolve(__dirname, "..");
const nodes = new Map();
function element() {
  return {content: "test-token", hidden: false, innerHTML: "", style: {},
    addEventListener() {}, focus() {}, setAttribute() {}, querySelectorAll() { return []; }};
}
const document = {
  querySelector(selector) {
    if (!nodes.has(selector)) nodes.set(selector, element());
    return nodes.get(selector);
  },
  querySelectorAll() { return []; },
  createElement() {
    let text = "";
    return {set textContent(v) { text = String(v); }, get innerHTML() {
      return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }};
  },
};
const sandbox = {document, window: {}, setTimeout, clearTimeout};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(root, "anonymizer/addin_web/taskpane.js"), "utf8"), sandbox);
const attack = '<img src=x onerror="globalThis.compromised=true">';
sandbox.attack = attack;
vm.runInContext(`renderReview({result: {total: 7, suggestions: [{text: attack, reason: attack, context: attack, count: 2}]}, files: [{messages: [{level: attack, text: attack}]}]})`, sandbox);
let html = nodes.get("#result").innerHTML;
assert(!html.includes("<img"));
assert(html.includes("&lt;img"));
assert(html.includes('class="info"'));
assert(html.includes("×2"));
assert(html.includes("7."));
vm.runInContext(`renderFinal("restore", {result: {restored: 3, unknown: {[attack]: true}}, files: [{messages: []}]}, {problems: [{text: attack}], notes: [attack]}, [attack])`, sandbox);
html = nodes.get("#result").innerHTML;
assert(!html.includes("<img"));
assert(html.includes("&lt;img"));
assert(html.includes("3."));
vm.runInContext(`renderError(new Error(attack), true)`, sandbox);
assert(!nodes.get("#result").innerHTML.includes("<img"));
vm.runInContext(`renderChanged("anonymize", {changed: 4});`, sandbox);
assert(nodes.get("#result").innerHTML.includes("4)"));
console.log("Frontend security render checks passed");

async function verifyDevelopmentRequestGuards() {
  const calls = [];
  const fake = {
    URLSearchParams, location: {search: "?host=Word"}, window: {},
    fetch: async (url, options = {}) => {
      calls.push({url, options});
      return {arrayBuffer: async () => new ArrayBuffer(0), json: async () => ({})};
    },
  };
  vm.createContext(fake);
  vm.runInContext(fs.readFileSync(path.join(root, "tools/fake_office.js"), "utf8"), fake);
  await fake.window.Office.onReady();
  await new Promise(resolve => fake.window.Office.context.document.settings.saveAsync(resolve));
  assert.equal(calls.length, 5);
  for (const {url, options} of calls) {
    assert(url.startsWith("/dev/"));
    assert.equal(options.headers["X-Requested-With"], "anonymizer", url);
  }
  assert.deepEqual(calls.map(c => c.options.method || "GET"), ["GET", "GET", "POST", "PUT", "PUT"]);
  console.log("Development Office request guard checks passed");
}
verifyDevelopmentRequestGuards().catch(error => { console.error(error); process.exitCode = 1; });
