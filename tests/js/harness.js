// Minimal DOM and browser stand-ins so the buildless /check scripts run under `node --test`.
// Only what frontend/baseline.js, check.js and check-resident.js touch is implemented.
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const FRONTEND = path.join(__dirname, '..', '..', 'frontend');

class Node_ {
  constructor(doc) { this.ownerDocument = doc; this.parentNode = null; this.childNodes = []; }
  get textContent() { return this.childNodes.map((c) => c.textContent).join(''); }
  set textContent(v) { this.childNodes = []; if (v !== '' && v != null) this.append(String(v)); }
  _adopt(child) {
    const node = typeof child === 'string' ? new Text_(this.ownerDocument, child) : child;
    if (node.parentNode) node.parentNode.childNodes = node.parentNode.childNodes.filter((c) => c !== node);
    node.parentNode = this;
    return node;
  }
  append(...children) { children.forEach((c) => this.childNodes.push(this._adopt(c))); }
  prepend(...children) { this.childNodes.unshift(...children.map((c) => this._adopt(c))); }
  replaceChildren(...children) { this.childNodes = []; this.append(...children); }
}

class Text_ extends Node_ {
  constructor(doc, text) { super(doc); this.text = text; }
  get textContent() { return this.text; }
  set textContent(v) { this.text = String(v); }
}

class Element_ extends Node_ {
  constructor(doc, tag) {
    super(doc);
    this.tagName = tag.toUpperCase();
    this.attributes = new Map();
    this.listeners = {};
    const self = this;
    this.dataset = new Proxy({}, {
      get: (_, k) => self.getAttribute(`data-${k}`) ?? undefined,
      set: (_, k, v) => { self.setAttribute(`data-${k}`, v); return true; },
    });
    this.style = {};
  }
  get children() { return this.childNodes.filter((c) => c instanceof Element_); }
  setAttribute(k, v) { this.attributes.set(k, String(v)); }
  getAttribute(k) { return this.attributes.has(k) ? this.attributes.get(k) : null; }
  hasAttribute(k) { return this.attributes.has(k); }
  removeAttribute(k) { this.attributes.delete(k); }
  get className() { return this.getAttribute('class') || ''; }
  set className(v) { this.setAttribute('class', v); }
  get id() { return this.getAttribute('id') || ''; }
  get hidden() { return this.hasAttribute('hidden'); }
  set hidden(v) { if (v) this.setAttribute('hidden', ''); else this.removeAttribute('hidden'); }
  get disabled() { return this.hasAttribute('disabled'); }
  set disabled(v) { if (v) this.setAttribute('disabled', ''); else this.removeAttribute('disabled'); }
  get href() { return this.getAttribute('href'); }
  get value() {
    if (this.tagName === 'SELECT') {
      const opts = this.children.filter((c) => c.tagName === 'OPTION');
      const chosen = opts.find((o) => o.hasAttribute('selected')) || opts[0];
      return chosen ? chosen.getAttribute('value') : '';
    }
    return this.getAttribute('value') || '';
  }
  set value(v) { this.setAttribute('value', v); }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  removeEventListener(type, fn) { this.listeners[type] = (this.listeners[type] || []).filter((f) => f !== fn); }
  dispatchEvent(event) {
    event.target ||= this;
    (this.listeners[event.type] || []).forEach((fn) => fn(event));
    if (event.bubbles !== false && this.parentNode && this.parentNode.dispatchEvent) {
      this.parentNode.dispatchEvent(event);
    }
  }
  getContext() { return new Proxy({}, {get: () => () => {}, set: () => true}); }
  click() { if (!this.disabled) this.dispatchEvent({type: 'click', bubbles: true}); }
  focus() { this.ownerDocument.activeElement = this; }
  matches(selector) {
    const m = selector.match(/^([a-z0-9]*)(?:\.([\w-]+))?(?:\[([\w-]+)(?:=([\w-]+))?\])?$/i);
    if (!m) throw new Error(`unsupported selector ${selector}`);
    const [, tag, cls, attr, val] = m;
    if (tag && this.tagName !== tag.toUpperCase()) return false;
    if (cls && !this.className.split(/\s+/).includes(cls)) return false;
    if (attr && !this.hasAttribute(attr)) return false;
    if (attr && val !== undefined && this.getAttribute(attr) !== val) return false;
    return true;
  }
  querySelectorAll(selector) {
    const out = [];
    const walk = (node) => node.children.forEach((c) => { if (c.matches(selector)) out.push(c); walk(c); });
    walk(this);
    return out;
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
}

class Document_ {
  constructor() {
    this.activeElement = null;
    this.visibilityState = 'visible';
    this.listeners = {};
    this.documentElement = new Element_(this, 'html');
    this.head = new Element_(this, 'head');
    this.body = new Element_(this, 'body');
    this.documentElement.append(this.head, this.body);
  }
  createElement(tag) { return new Element_(this, tag); }
  createElementNS(_, tag) { return new Element_(this, tag); }
  getElementById(id) { return this.documentElement.querySelectorAll('*').find((e) => e.id === id) || null; }
  querySelectorAll(s) { return this.documentElement.querySelectorAll(s); }
  querySelector(s) { return this.documentElement.querySelector(s); }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  removeEventListener() {}
}
// `querySelectorAll('*')` for getElementById.
const origMatches = Element_.prototype.matches;
Element_.prototype.matches = function (s) { return s === '*' ? true : origMatches.call(this, s); };

class FakeRecorder {
  static isTypeSupported(t) { return t === 'audio/webm'; }
  constructor(stream, opts) { this.stream = stream; this.mimeType = (opts && opts.mimeType) || ''; this.state = 'inactive'; FakeRecorder.last = this; }
  start() { this.state = 'recording'; }
  stop() {
    this.state = 'inactive';
    if (this.ondataavailable) this.ondataavailable({data: {size: 3, toString: () => 'abc'}});
    setTimeout(() => this.onstop && this.onstop(), 0);
  }
}

// Builds a page at `url` with stubbed fetch/mic/speech. `routes` maps "METHOD path" to a
// function returning a JSON body (or throwing {status}).
function loadPage(url, {routes = {}, mic = 'granted', speech = true, patients, storage = 'ok',
                         consent = {}, pswToken = 'psw-t'} = {}) {
  const doc = new Document_();
  const main = doc.createElement('main');
  main.setAttribute('id', 'bl-main');
  const nav = doc.createElement('nav');
  const link = doc.createElement('a');
  link.setAttribute('data-route', 'check');
  nav.append(link);
  doc.body.append(nav, main);
  const parsed = new URL(url, 'https://demo.test');
  const calls = [];
  const spoken = [];
  const errors = [];
  const session = {token: 't', patients: patients || [
    {id: 'p1', name: 'Alex Morgan'}, {id: 'p2', name: 'Jamie Chen'}, {id: 'p3', name: 'Sam Rivera'}]};
  if (pswToken) session.psw_token = pswToken;
  const consentRoutes = Object.fromEntries(session.patients.map((p) => [
    `GET /v1/patients/${p.id}/consent`, () => ({scope: 'voice_check', state: consent[p.id] || 'granted',
                                               decided_by: 'synthetic_fixture'})]));
  const allRoutes = {'GET /demo/session': () => session, ...consentRoutes,
    'GET /v1/checks/due': () => ({residents: session.patients.map((p) => ({patient_id: p.id,
      display_name: p.name, status: 'due', consent_state: consent[p.id] || 'granted'}))}), ...routes};
  const fetch = async (p, opts = {}) => {
    const key = `${(opts.method || 'GET').toUpperCase()} ${p}`;
    calls.push({key, opts});
    const handler = allRoutes[key];
    if (!handler) return {ok: false, status: 404, json: async () => ({})};
    try {
      const body = await handler(opts);
      return {ok: true, status: 200, json: async () => body};
    } catch (error) {
      return {ok: false, status: error.status || 500, json: async () => ({})};
    }
  };
  const stored = new Map();
  const localStorage = {getItem: (k) => (stored.has(k) ? stored.get(k) : null),
                        setItem: (k, v) => stored.set(k, String(v))};
  const window = {
    document: doc, location: {pathname: parsed.pathname, search: parsed.search},
    fetch, URLSearchParams, Blob, FormData, URL, Promise, JSON, Math, Date, Object, Array, Map,
    Number, String, Error, setTimeout, clearTimeout, setInterval, clearInterval,
    console: {error: (e) => errors.push(e), log() {}, warn() {}},
    getComputedStyle: () => ({getPropertyValue: () => ''}),
    MediaRecorder: FakeRecorder,
    stored,
    navigator: {mediaDevices: {getUserMedia: async () => {
      if (mic !== 'granted') { const e = new Error('NotAllowedError: Permission denied'); e.name = 'NotAllowedError'; throw e; }
      return {getTracks: () => [{stop() {}}]};
    }}},
  };
  if (speech) {
    window.speechSynthesis = {speak: (u) => spoken.push(u), cancel() {}, getVoices: () => [{lang: 'en-CA', name: 'v'}]};
    window.SpeechSynthesisUtterance = function (text) { this.text = text; };
  }
  Object.defineProperty(window, 'localStorage', {get: () => {
    if (storage !== 'ok') throw new Error('SecurityError: storage blocked');
    return localStorage;
  }});
  window.window = window;
  window.globalThis = window;
  const ctx = vm.createContext(window);
  // check-fixtures.js is lazily injected via <script>; load it on demand through head.append.
  const origAppend = doc.head.append.bind(doc.head);
  doc.head.append = (...nodes) => {
    origAppend(...nodes);
    nodes.forEach((n) => {
      if (n.tagName === 'SCRIPT' && n.src) {
        vm.runInContext(fs.readFileSync(path.join(FRONTEND, path.basename(n.src)), 'utf8'), ctx);
        setTimeout(() => n.onload && n.onload(), 0);
      }
    });
  };
  for (const file of ['check-resident.js', 'check.js', 'baseline.js']) {
    vm.runInContext(fs.readFileSync(path.join(FRONTEND, file), 'utf8'), ctx, {filename: file});
  }
  return {doc, main, window, ctx, calls, spoken, errors};
}

const tick = (ms = 0) => new Promise((r) => setTimeout(r, ms));
async function until(predicate, ms = 3000) {
  const end = Date.now() + ms;
  while (!predicate()) {
    if (Date.now() > end) throw new Error('timed out waiting for page state');
    await tick(10);
  }
}

// All visible text plus every attribute value: what a resident could see or a screen reader read.
function exposedText(node) {
  if (!(node instanceof Element_)) return node.textContent;
  if (node.hidden) return '';
  const attrs = [...node.attributes.entries()].filter(([k]) => !['class', 'id', 'href', 'for',
    'type', 'tabindex', 'role', 'lang', 'value', 'hidden', 'aria-live', 'aria-pressed',
    'aria-hidden', 'width', 'height'].includes(k) && !k.startsWith('data-'))
    .map(([, v]) => v);
  return [...attrs, ...node.childNodes.map(exposedText)].join(' ');
}

module.exports = {loadPage, tick, until, exposedText, FakeRecorder};
