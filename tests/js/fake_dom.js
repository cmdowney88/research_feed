// Minimal fake DOM + fetch/localStorage stubs for smoke-testing the UI page scripts under
// macOS JXA (osascript -l JavaScript); see run_ui_smoke.sh and run_manage_smoke.sh. Not a
// browser: no layout, and events are called directly via node.listeners.<type>().
var FakeNode = class {
  constructor(tag) { this.tagName = tag.toUpperCase(); this.children = []; this.attrs = {};
    this.className = ''; this.style = {}; this.dataset = {}; this.parentElement = null;
    this.textContent = ''; this.listeners = {}; this.checked = false; this.value = '';
    this.disabled = false; this.open = false;
    this.classList = { set: new Set(), add(c) { this.set.add(c); }, remove(c) { this.set.delete(c); },
      toggle(c, on) { (on === undefined ? !this.set.has(c) : on) ? this.set.add(c) : this.set.delete(c); },
      contains(c) { return this.set.has(c); } }; }
  setAttribute(k, v) { this.attrs[k] = v; if (k === 'checked') this.checked = true;
    if (k === 'open') this.open = true; }
  append(...nodes) { for (const n of nodes) { if (n instanceof FakeNode) n.parentElement = this; this.children.push(n); } }
  replaceChildren(...nodes) { this.children = []; this.append(...nodes); }
  addEventListener(type, fn) { this.listeners[type] = fn; }
  classes() { return new Set([...this.className.split(/\s+/).filter(Boolean), ...this.classList.set]); }
  descendants() { const out = []; (function walk(n) { for (const c of n.children)
    if (c instanceof FakeNode) { out.push(c); walk(c); } })(this); return out; }
  // supports "tag.class[type=x]:checked" compounds joined by descendant spaces
  querySelectorAll(selector) { const parts = selector.trim().split(/\s+/);
    return this.descendants().filter(node => matchesChain(node, parts, this)); }
  closest() { return null; } scrollIntoView() {}
  text() { return this.children.map(c => c instanceof FakeNode ? c.text() : String(c)).join('') + this.textContent; } }
function matchesCompound(node, compound) {
  const match = compound.match(/^([a-z0-9]*)((?:\.[\w-]+)*)((?:\[[\w-]+=[\w-]+\])*)(:checked)?$/i);
  if (!match) throw new Error('fake DOM cannot match ' + compound);
  if (match[1] && node.tagName !== match[1].toUpperCase()) return false;
  const classes = node.classes();
  for (const c of match[2].split('.').filter(Boolean)) if (!classes.has(c)) return false;
  for (const [, k, v] of match[3].matchAll(/\[([\w-]+)=([\w-]+)\]/g)) if (node.attrs[k] !== v) return false;
  return !match[4] || node.checked; }
function matchesChain(node, parts, root) {
  if (!matchesCompound(node, parts[parts.length - 1])) return false;
  if (parts.length === 1) return true;
  for (let up = node.parentElement; up && up !== root; up = up.parentElement)
    if (matchesChain(up, parts.slice(0, -1), root)) return true;
  return false; }
// find nodes under `root` by predicate, e.g. buttons by their text
function findAll(root, predicate) { return root.descendants().filter(predicate); }
function byText(root, tag, text) {
  return findAll(root, n => n.tagName === tag && n.text().includes(text)); }

var Node = FakeNode, nodes = {}, calls = [], bodies = [], intervals = [], responses = {};
var document = { createElement: t => new FakeNode(t), createTextNode: s => String(s),
  // page roots (ids in the server HTML) are created on first lookup; ids set by page scripts
  // are found among their descendants
  getElementById: id => { if (id === 'data') return { textContent: PAGE_DATA };
    if (nodes[id]) return nodes[id];
    for (const root of Object.values(nodes)) {
      const found = root.descendants().find(n => n.attrs.id === id);
      if (found) return found; }
    nodes[id] = new FakeNode(id === 'autosave' ? 'input' : 'div'); return nodes[id]; },
  querySelectorAll: selector => Object.values(nodes).flatMap(n => n.querySelectorAll(selector)) };
var localStorage = { getItem() { throw new Error('blocked'); }, setItem() { throw new Error('blocked'); } };
var location = { search: '', hash: '', href: '', reload() { calls.push('reload'); } };
if (typeof URLSearchParams === 'undefined') {
  var URLSearchParams = class { constructor() {} get() { return null; } }; }
var setInterval = fn => { intervals.push(fn); return intervals.length; };
var clearInterval = () => {};
var confirm = () => true;
var alert = message => calls.push('alert:' + message);
// `responses[url]` (a function of the request body) overrides the default replies
function fetch(url, options) { const body = JSON.parse(options.body); calls.push(url); bodies.push(body);
  const result = responses[url] ? responses[url](body)
    : url === '/api/thumb'
    ? { entry: { paperId: body.paperId, thumb: body.thumb, in_seeds: body.thumb === 'up', seed_change: null } }
    : { row: { key: 'k', collection: body.collection, pdf: '' } };
  return Promise.resolve({ ok: true, json: () => Promise.resolve(result) }); }
