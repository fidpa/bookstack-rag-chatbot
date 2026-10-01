// Runs the two widget scripts against DOM stand-ins and prints what they did as
// JSON, for tests/test_widget_js.py. Needs only node, no packages.
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const root = path.resolve(__dirname, "..", "..");

// An element that accepts any property access and any call.
function stub(props = {}) {
  const own = {
    classList: { add() {}, remove() {}, contains() { return false; } },
    style: {},
    ...props,
  };
  return new Proxy(own, {
    get(target, prop) {
      if (prop in target) return target[prop];
      if (typeof prop === "symbol") return undefined;
      return () => stub();
    },
    set(target, prop, value) {
      target[prop] = value;
      return true;
    },
  });
}

function scriptOf(file, replacements = {}) {
  let html = fs.readFileSync(path.join(root, file), "utf8");
  for (const [from, to] of Object.entries(replacements)) html = html.split(from).join(to);
  const match = html.match(/<script>([\s\S]*?)<\/script>/);
  if (!match) throw new Error(`no <script> in ${file}`);
  return match[1];
}

// A page the script can run in. `answers` are the JSON bodies fetch() returns, in order;
// an answer with `__status` comes back with that HTTP status instead of 200.
function sandbox({ href, answers = [], storedSession = null, inputIds = [] }) {
  const url = new URL(href);
  const fetchCalls = [];
  const storageWrites = [];
  const handlers = {};
  const elements = {};
  for (const id of inputIds) elements[id] = stub({ value: "hello", focus() {} });

  const window = {
    location: { hostname: url.hostname, origin: url.origin, href: url.href, pathname: url.pathname, port: url.port },
    addEventListener(type, fn) { handlers[type] = fn; },
  };
  window.parent = window;
  const document = {
    readyState: "complete",
    title: "A page",
    body: stub(),
    getElementById: (id) => elements[id] || (elements[id] = stub()),
    createElement: () => stub(),
    querySelector: () => null,
    querySelectorAll: () => [],
    addEventListener() {},
  };
  const context = vm.createContext({
    window,
    document,
    URL,
    console: { log() {}, error() {} },
    setTimeout() {},
    requestAnimationFrame: (fn) => fn(),
    sessionStorage: {
      getItem: () => storedSession,
      setItem: (key, value) => storageWrites.push([key, value]),
    },
    fetch: async (target, options) => {
      fetchCalls.push({ url: target, headers: options.headers, body: JSON.parse(options.body) });
      const answer = answers.shift() || {};
      const status = answer.__status || 200;
      return { ok: status < 400, status, json: async () => answer };
    },
  });
  return { context, window, elements, handlers, fetchCalls, storageWrites };
}

const result = { apiUrl: {}, embedded: {}, standalone: {}, refused: {} };
const TOO_LONG = { __status: 400, success: false, error: "Message too long (at most 2000 characters)" };

// --- the embedded widget: where it posts, and how it keeps the session ---------
const embeddedScript = scriptOf("bookstack-integration/widget.html");
const pages = {
  "http://localhost:6875/books/x/page/y": null,
  "http://127.0.0.1:6875/": null,
  "https://wiki.example.com:8443/books/a/page/b": null,
  "http://wiki.lan/books/a/page/b": null,
};
for (const href of Object.keys(pages)) {
  const sb = sandbox({ href });
  vm.runInContext(embeddedScript, sb.context);
  result.apiUrl[href] = sb.window.KnowledgeBotChat.apiUrl;
}

async function embeddedSession() {
  const sb = sandbox({
    href: "https://wiki.example.com/books/a/page/b",
    answers: [
      { success: true, session_id: "srv-1", response: "first" },
      { success: true, session_id: "srv-1", response: "second" },
    ],
    inputIds: ["kbChatInput", "kbSendButton"],
  });
  vm.runInContext(embeddedScript, sb.context);
  const chat = sb.window.KnowledgeBotChat;
  await chat.sendMessage();
  sb.elements.kbChatInput.value = "and then?";
  await chat.sendMessage();
  return {
    headers: sb.fetchCalls.map((call) => call.headers["X-Widget-Session"]),
    stored: sb.storageWrites,
    sentContext: Object.keys(sb.fetchCalls[0].body.bookstack_context).sort(),
  };
}

// --- the standalone chat page: page context only from BookStack's origin -------
async function standalone() {
  const allowed = "https://wiki.example.com:8443";
  const script = scriptOf("chatbot/templates/chat/widget.html", {
    "{{ bookstack_origin|tojson }}": JSON.stringify(allowed),
  });
  const sb = sandbox({
    href: "https://chatbot.example.com/chat/widget",
    answers: [
      { success: true, session_id: "srv-9", response: "first" },
      { success: true, session_id: "srv-9", response: "second" },
    ],
    inputIds: ["chatInput", "sendButton"],
  });
  vm.runInContext(script, sb.context);
  const title = () => vm.runInContext("bookstackContext.title", sb.context);
  const message = (origin, page) => sb.handlers.message({ origin, data: { type: "bookstack-context", page } });

  const out = { before: title() };
  message("https://evil.example.com", { title: "planted by another origin" });
  out.afterForeignOrigin = title();
  message("https://wiki.example.com", { title: "right host, wrong port" });
  out.afterWrongPort = title();
  message(allowed, { title: "from BookStack" });
  out.afterBookStack = title();

  await vm.runInContext("sendMessage()", sb.context);
  sb.elements.chatInput.value = "and then?";
  await vm.runInContext("sendMessage()", sb.context);
  out.headers = sb.fetchCalls.map((call) => call.headers["X-Widget-Session"]);
  out.stored = sb.storageWrites;
  return out;
}

// --- a question the API refuses: the widget shows the API's reason -------------
async function refusedEmbedded() {
  const sb = sandbox({
    href: "https://wiki.example.com/books/a/page/b",
    answers: [TOO_LONG],
    inputIds: ["kbChatInput", "kbSendButton"],
  });
  vm.runInContext(embeddedScript, sb.context);
  const chat = sb.window.KnowledgeBotChat;
  const shown = [];
  chat.addMessage = (content, isUser) => { if (!isUser) shown.push(content); };
  await chat.sendMessage();
  return shown;
}

async function refusedStandalone() {
  const script = scriptOf("chatbot/templates/chat/widget.html", {
    "{{ bookstack_origin|tojson }}": JSON.stringify("https://wiki.example.com"),
  });
  const sb = sandbox({
    href: "https://chatbot.example.com/chat/widget",
    answers: [TOO_LONG],
    inputIds: ["chatInput", "sendButton"],
  });
  vm.runInContext(script, sb.context);
  vm.runInContext("var __shown = []; addMessage = (content, isUser) => { if (!isUser) __shown.push(content); };", sb.context);
  await vm.runInContext("sendMessage()", sb.context);
  return vm.runInContext("__shown", sb.context);
}

(async () => {
  result.embedded = await embeddedSession();
  result.standalone = await standalone();
  result.refused = { embedded: await refusedEmbedded(), standalone: await refusedStandalone() };
  process.stdout.write(JSON.stringify(result));
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
