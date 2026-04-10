const fs = require("fs");
const vm = require("vm");
const path = require("path");
const crypto = require("crypto").webcrypto;

const LEGACY_MARKER = "t.init=we,t.sessionObserverToken=async function(t)";
const LIVE_TAIL_REGEX = /t\.init=(\w+),t\.token=(\w+),t\}\(\{\}\);?$/;
let _browserBundle = null;
let _browserState = null;

function loadPlaywright() {
  if (_browserBundle) {
    return _browserBundle;
  }
  const candidates = [
    "playwright-core",
    "playwright",
  ];
  for (const name of candidates) {
    try {
      _browserBundle = require(name);
      return _browserBundle;
    } catch (error) {}
  }
  return null;
}

function resolveBrowserExecutable() {
  const candidates = [
    "C:/Program Files/Google/Chrome/Application/chrome.exe",
    "C:/Program Files/Google/Chrome Beta/Application/chrome.exe",
    "C:/Program Files/Microsoft/Edge/Application/msedge.exe",
  ];
  return candidates.find((candidate) => fs.existsSync(candidate)) || "";
}

async function ensureBrowserState({ proxyUrl = "", userAgent = "", authUrl = "" } = {}) {
  const playwright = loadPlaywright();
  if (!playwright || !playwright.chromium) {
    throw new Error("playwright-core unavailable");
  }
  const executablePath = resolveBrowserExecutable();
  if (!executablePath) {
    throw new Error("browser executable unavailable");
  }
  const normalizedAuthUrl =
    String(authUrl || "").trim() || "https://auth.openai.com/create-account";
  const normalizedUserAgent =
    String(userAgent || "").trim() ||
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.7680.178 Safari/537.36";
  if (
    _browserState &&
    _browserState.proxyUrl === proxyUrl &&
    _browserState.userAgent === normalizedUserAgent &&
    _browserState.authUrl === normalizedAuthUrl
  ) {
    return _browserState;
  }
  if (_browserState) {
    try {
      await _browserState.browser.close();
    } catch (error) {}
    _browserState = null;
  }
  const launchOptions = {
    executablePath,
    headless: true,
  };
  const normalizedProxy = String(proxyUrl || "").trim();
  if (normalizedProxy) {
    const chromiumProxy = normalizedProxy.replace(/^socks5h:/i, "socks5:");
    launchOptions.proxy = { server: chromiumProxy };
  }
  const browser = await playwright.chromium.launch(launchOptions);
  const context = await browser.newContext({
    userAgent: normalizedUserAgent,
    locale: "en-US",
  });
  const page = await context.newPage();
  await page.goto(normalizedAuthUrl, { waitUntil: "domcontentloaded", timeout: 90000 });
  await page.waitForFunction(
    () => window.SentinelSDK && typeof window.SentinelSDK.token === "function",
    null,
    { timeout: 60000 },
  );
  _browserState = {
    browser,
    context,
    page,
    proxyUrl: normalizedProxy,
    userAgent: normalizedUserAgent,
    authUrl: normalizedAuthUrl,
  };
  return _browserState;
}

function resolveSdkFile() {
  const preferred = [
    "sentinel_sdk_live_20260219.js",
    "sentinel_sdk_live_20260408.js",
  ];
  for (const name of preferred) {
    const candidate = path.join(__dirname, name);
    if (fs.existsSync(candidate)) {
      return candidate;
    }
  }
  const dynamic = fs
    .readdirSync(__dirname)
    .filter((name) => /^sentinel_sdk_live_\d+\.js$/i.test(name))
    .map((name) => path.join(__dirname, name))
    .sort((a, b) => {
      try {
        return fs.statSync(b).mtimeMs - fs.statSync(a).mtimeMs;
      } catch {
        return 0;
      }
    });
  if (dynamic.length > 0) {
    return dynamic[0];
  }
  return path.join(__dirname, "sentinel_sdk_live_20260219.js");
}

function readPatchedSdk() {
  const code = fs.readFileSync(resolveSdkFile(), "utf8");
  const normalized = code.replace(/\s+$/, "");
  if (normalized.includes(LEGACY_MARKER)) {
    let patched = normalized.replace(
      LEGACY_MARKER,
      "t.P=P,t.D=D,t.getProof=$,t.transformDx=_n,t.xorDecode=Tn,t.makeToken=ce,t.reqUrl=Bn,t.frameUrl=Qn," +
        LEGACY_MARKER,
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
  const liveTailMatch = normalized.match(LIVE_TAIL_REGEX);
  if (liveTailMatch) {
    const initName = liveTailMatch[1];
    const tokenName = liveTailMatch[2];
    return normalized.replace(
      LIVE_TAIL_REGEX,
      `t.P=R,t.transformDx=jt,t.makeToken=cn,t.reqFetch=un,t.liveInit=${initName},t.liveToken=${tokenName},$&`,
    );
  }
  throw new Error("no known sdk marker found");
}

function createSandbox() {
  const RealDate = Date;
  const reactListeningKey = `_reactListening${Math.random().toString(36).slice(2, 12)}`;
  function formatEnglishDate(value) {
    const date = new RealDate(value);
    const days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
    const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    const pad = (n) => String(n).padStart(2, "0");
    return `${days[date.getDay()]} ${months[date.getMonth()]} ${pad(date.getDate())} ${date.getFullYear()} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())} GMT+0800 (Taiwan Standard Time)`;
  }
  function FakeDate(...args) {
    const instance = args.length > 0 ? new RealDate(...args) : new RealDate();
    Object.setPrototypeOf(instance, FakeDate.prototype);
    return instance;
  }
  FakeDate.prototype = Object.create(RealDate.prototype);
  FakeDate.prototype.constructor = FakeDate;
  FakeDate.prototype.toString = function () {
    return formatEnglishDate(this.getTime());
  };
  FakeDate.now = () => RealDate.now();
  FakeDate.parse = RealDate.parse.bind(RealDate);
  FakeDate.UTC = RealDate.UTC.bind(RealDate);

  const sandbox = {
    console,
    setTimeout,
    clearTimeout,
    Promise,
    Math,
    Date: FakeDate,
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
      now: () => 14240.299999952316,
      memory: { jsHeapSizeLimit: 4294967296 },
      timeOrigin: RealDate.now() - 14240.299999952316,
    },
    screen: { width: 1920, height: 1080 },
    navigator: {
      userAgent:
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.7680.178 Safari/537.36",
      language: "en-US",
      languages: ["en-US"],
      hardwareConcurrency: 32,
      platform: "Win32",
    },
    presentation: {
      toString() {
        return "[object Presentation]";
      },
    },
    ondevicemotion: null,
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
  sandbox[reactListeningKey] = true;
  sandbox.location = {
    href: "https://auth.openai.com/create-account",
    pathname: "/create-account",
    search: "",
    origin: "https://auth.openai.com",
  };
  sandbox.document = {
    currentScript: { src: "https://sentinel.openai.com/backend-api/sentinel/sdk.js" },
    documentElement: {
      getAttribute(name) {
        return null;
      },
    },
    scripts: [
      { src: "https://sentinel.openai.com/backend-api/sentinel/sdk.js" },
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

async function handleMode({ sandbox, sdk, mode, payload }) {
  if (mode === "sdk_token") {
    const flow = String(payload.flow || "").trim();
    if (!flow) {
      throw new Error("sdk_token mode requires flow");
    }
    const did = String(payload.did || "").trim();
    const state = await ensureBrowserState({
      proxyUrl: String(payload.proxy_url || "").trim(),
      userAgent: String(payload.user_agent || "").trim(),
      authUrl: String(payload.auth_url || "").trim(),
    });
    if (did) {
      await state.context.addCookies([
        {
          name: "oai-did",
          value: did,
          domain: "auth.openai.com",
          path: "/",
          secure: true,
          httpOnly: false,
          sameSite: "Lax",
        },
        {
          name: "oai-did",
          value: did,
          domain: "sentinel.openai.com",
          path: "/",
          secure: true,
          httpOnly: false,
          sameSite: "Lax",
        },
      ]);
    }
    const token = await state.page.evaluate(async (flowName) => {
      return await window.SentinelSDK.token(flowName);
    }, flow);
    return {
      ok: true,
      mode,
      token: String(token || ""),
      len: String(token || "").length,
      prefix: String(token || "").slice(0, 180),
    };
  }

  if (mode === "requirements") {
    const req = await sdk.P.getRequirementsToken();
    return {
      ok: true,
      mode,
      len: req.length,
      token: req,
      prefix: req.slice(0, 120),
    };
  }

  if (mode === "transform") {
    const reqJson = payload.req_json || {};
    const reqProof = String(payload.req_proof || "");
    const dx = String(payload.dx || (((reqJson || {}).turnstile || {}).dx) || "");
    let decodedRaw = "";
    let decoded = null;
    if (typeof sdk.D === "function" && typeof sdk.xorDecode === "function" && typeof sdk.getProof === "function") {
      sdk.D(reqJson, reqProof);
      decodedRaw = sdk.xorDecode(sandbox.atob(dx), sdk.getProof(reqJson) || "");
      decoded = JSON.parse(decodedRaw);
    }
    const t = dx
      ? await (typeof sdk.D === "function" ? sdk.transformDx(reqJson, dx) : sdk.transformDx(dx))
      : "";
    const enforcement = await sdk.P.getEnforcementToken(reqJson);
    return {
      ok: true,
      mode,
      t,
      enforcement,
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
    };
  }

  if (mode === "exact") {
    const reqJson = payload.req_json || {};
    const reqProof = String(payload.req_proof || "");
    const flow = String(payload.flow || "");
    const did = String(payload.did || "11111111-2222-4333-8444-555555555555");
    const dx = String(payload.dx || (((reqJson || {}).turnstile || {}).dx) || "");
    sandbox.document.cookie = `oai-did=${did}`;
    if (typeof sdk.D === "function") {
      sdk.D(reqJson, reqProof);
    }
    const t = dx
      ? await (typeof sdk.D === "function" ? sdk.transformDx(reqJson, dx) : sdk.transformDx(dx))
      : "";
    const enforcement = await sdk.P.getEnforcementToken(reqJson);
    const exact = String(
      sdk.makeToken({ p: enforcement, t, c: String(reqJson.token || "") }, flow) || ""
    );
    return {
      ok: true,
      mode,
      exact,
      exact_len: exact.length,
      exact_prefix: exact.slice(0, 160),
      t_len: t.length,
      p_len: enforcement.length,
    };
  }

  throw new Error(`unknown mode: ${mode}`);
}

async function main() {
  const mode = process.argv[2] || "requirements";
  const sandbox = loadSdkContext();
  const sdk = sandbox.SentinelSDK;

  if (mode === "serve") {
    let buffer = "";
    process.stdin.setEncoding("utf8");
    process.stdin.on("data", async (chunk) => {
      buffer += chunk;
      while (true) {
        const newlineIndex = buffer.indexOf("\n");
        if (newlineIndex < 0) break;
        const line = buffer.slice(0, newlineIndex).trim();
        buffer = buffer.slice(newlineIndex + 1);
        if (!line) continue;
        let req;
        try {
          req = JSON.parse(line);
        } catch (err) {
          process.stdout.write(JSON.stringify({ request_id: "", error: String(err) }) + "\n");
          continue;
        }
        try {
          const result = await handleMode({
            sandbox,
            sdk,
            mode: String(req.mode || ""),
            payload: req.payload || {},
          });
          process.stdout.write(JSON.stringify({ request_id: req.request_id || "", result }) + "\n");
        } catch (err) {
          process.stdout.write(
            JSON.stringify({
              request_id: req.request_id || "",
              error: String((err && err.stack) || err || "unknown"),
            }) + "\n"
          );
        }
      }
    });
    return;
  }

  const inputPath = process.argv[3];
  let payload = {};
  if (mode !== "requirements") {
    if (!inputPath) {
      throw new Error(`${mode} mode requires input json path`);
    }
    payload = JSON.parse(fs.readFileSync(inputPath, "utf8"));
  }
  const result = await handleMode({ sandbox, sdk, mode, payload });
  process.stdout.write(JSON.stringify(result, null, 2));
}

main().catch((err) => {
  process.stderr.write(String((err && err.stack) || err || "unknown"));
  process.exit(1);
});
