const fs = require("fs");
const vm = require("vm");
const crypto = require("crypto").webcrypto;

const LIVE_SDK_FILE = "sentinel_sdk_live_20260219.js";
const MARKER = "t.init=we,t.sessionObserverToken=async function(t)";

function readPatchedSdk() {
  const code = fs.readFileSync(LIVE_SDK_FILE, "utf8");
  if (!code.includes(MARKER)) {
    throw new Error("marker not found");
  }
  let patched = code.replace(
    MARKER,
    "t.P=P,t.D=D,t.getProof=$,t.transformDx=_n,t.xorDecode=Tn,t.makeToken=ce,t.reqUrl=Bn,t.frameUrl=Qn," +
      MARKER,
  );
  const bindOp =
    "bn[t(4)](Ht,((n,e,r)=>bn[t(4)](n,bn[t(10)](e)[bn[t(10)](r)][t(28)](bn.get(e))))),";
  if (patched.includes(bindOp)) {
    patched = patched.replace(
      bindOp,
      "bn[t(4)](Ht,((n,e,r)=>{const __obj=bn[t(10)](e);const __prop=bn[t(10)](r);const __target=__obj?__obj[__prop]:void 0;if(void 0===__target||null===__target){window.__bind_probe={prop:__prop,obj_type:typeof __obj,obj_string:String(__obj),obj_keys:__obj&&typeof __obj==='object'?Object.keys(__obj).slice(0,40):[]};throw new Error('__BIND_MISSING__:'+String(__prop));}return bn[t(4)](n,__target[t(28)](bn.get(e)))})),",
    );
  }
  return patched;
}

function createSandbox() {
  const sandbox = {
    console,
    setTimeout,
    clearTimeout,
    Promise,
    Math,
    Date,
    JSON,
    URL,
    URLSearchParams,
    TextEncoder,
    Buffer,
    atob: (s) => Buffer.from(String(s), "base64").toString("binary"),
    btoa: (s) => Buffer.from(String(s), "binary").toString("base64"),
    unescape,
    encodeURIComponent,
    decodeURIComponent,
    crypto,
    performance: {
      now: () => Date.now() % 100000,
      memory: { jsHeapSizeLimit: 4294967296 },
      timeOrigin: Date.now() - 12345,
    },
    screen: { width: 1920, height: 1080 },
    navigator: {
      userAgent:
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.7680.178 Safari/537.36",
      language: "zh-TW",
      languages: ["zh-TW", "zh", "en-US", "en"],
      hardwareConcurrency: 8,
      platform: "Win32",
    },
    localStorage: {
      _s: new Map(),
      getItem(k) {
        return this._s.has(k) ? this._s.get(k) : null;
      },
      setItem(k, v) {
        this._s.set(k, String(v));
      },
      removeItem(k) {
        this._s.delete(k);
      },
    },
    history: {},
    Reflect,
    Object,
    Array,
    Number,
    String,
    Boolean,
    Intl,
    RegExp,
    Function,
    Error,
    addEventListener() {},
    removeEventListener() {},
    fetch: async () => {
      throw new Error("fetch disabled in probe");
    },
    requestIdleCallback: (cb) =>
      setTimeout(() => cb({ timeRemaining: () => 50, didTimeout: false }), 0),
  };

  sandbox.window = sandbox;
  sandbox.top = sandbox;
  sandbox.location = { href: "https://chatgpt.com/", pathname: "/", search: "" };
  sandbox.document = {
    currentScript: { src: "https://sentinel.openai.com/sentinel/20260219f9f6/sdk.js" },
    documentElement: {
      getAttribute(name) {
        return name === "data-build" ? "prod-20260404" : null;
      },
    },
    scripts: [
      { src: "https://chatgpt.com/assets/app.js" },
      { src: "https://chatgpt.com/c/abc123/_next/static/chunks/app.js" },
    ],
    cookie: "oai-did=11111111-2222-4333-8444-555555555555",
    createElement(tag) {
      return {
        style: {},
        tagName: tag,
        ariaHidden: "",
        innerText: "",
        children: [],
        addEventListener() {},
        removeEventListener() {},
        remove() {},
        appendChild(child) {
          this.children.push(child);
          return child;
        },
        removeChild(child) {
          this.children = this.children.filter((item) => item !== child);
          return child;
        },
        contentWindow: sandbox,
        getBoundingClientRect() {
          return {
            x: 0,
            y: 0,
            width: 320,
            height: 180,
            top: 0,
            left: 0,
            right: 320,
            bottom: 180,
          };
        },
        set src(v) {
          this._src = v;
        },
        get src() {
          return this._src;
        },
      };
    },
    head: {
      children: [],
      appendChild(child) {
        this.children.push(child);
        return child;
      },
      removeChild(child) {
        this.children = this.children.filter((item) => item !== child);
        return child;
      },
    },
    body: {
      children: [],
      appendChild(child) {
        this.children.push(child);
        return child;
      },
      removeChild(child) {
        this.children = this.children.filter((item) => item !== child);
        return child;
      },
      getBoundingClientRect() {
        return {
          x: 0,
          y: 0,
          width: 1280,
          height: 720,
          top: 0,
          left: 0,
          right: 1280,
          bottom: 720,
        };
      },
    },
    addEventListener() {},
    removeEventListener() {},
  };
  return sandbox;
}

function loadSdkContext() {
  const sandbox = createSandbox();
  vm.createContext(sandbox);
  vm.runInContext(readPatchedSdk(), sandbox, { timeout: 20000 });
  return sandbox;
}

async function main() {
  const mode = process.argv[2] || "requirements";
  const sandbox = loadSdkContext();
  const sdk = sandbox.SentinelSDK;

  if (mode === "requirements") {
    const req = await sdk.P.getRequirementsToken();
    process.stdout.write(
      JSON.stringify(
        {
          ok: true,
          mode,
          len: req.length,
          token: req,
          prefix: req.slice(0, 120),
        },
        null,
        2,
      ),
    );
    return;
  }

  if (mode === "transform") {
    const inputPath = process.argv[3];
    if (!inputPath) {
      throw new Error("transform mode requires input json path");
    }
    const payload = JSON.parse(fs.readFileSync(inputPath, "utf8"));
    const reqJson = payload.req_json || {};
    const reqProof = String(payload.req_proof || "");
    const dx = String(payload.dx || (((reqJson || {}).turnstile || {}).dx) || "");
    sdk.D(reqJson, reqProof);
    const decodedRaw = sdk.xorDecode(sandbox.atob(dx), sdk.getProof(reqJson) || "");
    const decoded = JSON.parse(decodedRaw);
    const t = dx ? await sdk.transformDx(reqJson, dx) : "";
    const enforcement = await sdk.P.getEnforcementToken(reqJson);
    process.stdout.write(
      JSON.stringify(
        {
          ok: true,
          mode,
          t: t,
          enforcement: enforcement,
          bind_probe: sandbox.__bind_probe || null,
          req_proof_len: reqProof.length,
          dx_len: dx.length,
          decoded_raw_len: decodedRaw.length,
          decoded_type: Array.isArray(decoded) ? "array" : typeof decoded,
          decoded_len: Array.isArray(decoded) ? decoded.length : -1,
          decoded_head: Array.isArray(decoded) ? decoded.slice(0, 80) : decoded,
          t_len: t.length,
          t_prefix: t.slice(0, 160),
          enforcement_len: enforcement.length,
          enforcement_prefix: enforcement.slice(0, 160),
        },
        null,
        2,
      ),
    );
    return;
  }

  throw new Error(`unknown mode: ${mode}`);
}

main().catch((err) => {
  process.stderr.write(String((err && err.stack) || err || "unknown"));
  process.exit(1);
});
