import json
import os
import re
import sys
import time
import uuid
import math
import random
import string
import secrets
import hashlib
import base64
import tempfile
import threading
import argparse
import subprocess
import shutil
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse
from dataclasses import dataclass
from typing import Any, Dict, Optional, List, Tuple
import urllib.parse
from upload_management_file import ZeaburAuthFileManager
from curl_cffi import requests

DEFAULT_CPA_BASE_URL = "http://127.0.0.1:8317"
DEFAULT_CPA_TOKEN = "00hhg5210"
AUTO_WORKERS_PER_HCPU = 44


def _read_first_env_value(*names: str, default: str = "") -> str:
    for name in names:
        value = str(os.environ.get(name, "")).strip()
        if value:
            return value
    return default


def _resolve_cpa_settings(
    cli_base_url: str = "",
    cli_token: str = "",
) -> Tuple[str, str]:
    base_url = str(cli_base_url or "").strip() or _read_first_env_value(
        "CPA_BASE_URL",
        "CPA_URL",
        "ZEABUR_AUTH_BASE_URL",
        default=DEFAULT_CPA_BASE_URL,
    )
    token = str(cli_token or "").strip() or _read_first_env_value(
        "CPA_TOKEN",
        "ZEABUR_AUTH_TOKEN",
        default=DEFAULT_CPA_TOKEN,
    )
    return base_url, token


manage = ZeaburAuthFileManager(*_resolve_cpa_settings())

def _configure_stdio() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None or not hasattr(stream, "reconfigure"):
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


_configure_stdio()


def _find_node_executable() -> str:
    for candidate in ("node", "nodejs"):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return ""


def _read_text_file(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def _detect_cgroup_cpu_limit() -> Optional[float]:
    cpu_max_text = _read_text_file("/sys/fs/cgroup/cpu.max")
    if cpu_max_text:
        parts = cpu_max_text.split()
        if len(parts) >= 2 and parts[0] != "max":
            try:
                quota = float(parts[0])
                period = float(parts[1])
                if quota > 0 and period > 0:
                    return quota / period
            except Exception:
                pass

    quota_text = _read_text_file("/sys/fs/cgroup/cpu/cpu.cfs_quota_us")
    period_text = _read_text_file("/sys/fs/cgroup/cpu/cpu.cfs_period_us")
    if quota_text and period_text:
        try:
            quota = float(quota_text)
            period = float(period_text)
            if quota > 0 and period > 0:
                return quota / period
        except Exception:
            pass
    return None


def _detect_effective_cpu_count() -> float:
    logical = float(os.cpu_count() or 1)
    affinity_count = 0.0
    try:
        affinity_count = float(len(os.sched_getaffinity(0)))
    except Exception:
        affinity_count = 0.0

    effective = affinity_count if affinity_count > 0 else logical
    cgroup_limit = _detect_cgroup_cpu_limit()
    if cgroup_limit and cgroup_limit > 0:
        effective = min(effective, cgroup_limit)
    return max(0.1, effective)


def _compute_auto_workers() -> Tuple[int, float]:
    cpu_units = _detect_effective_cpu_count()
    workers = max(1, int(math.floor(cpu_units * AUTO_WORKERS_PER_HCPU + 0.5)))
    return workers, cpu_units


class RetryNewEmail(RuntimeError):
    pass


class DropMailHTTPError(RuntimeError):
    def __init__(self, op: str, status_code: int, text: str = ""):
        self.op = str(op or "").strip() or "DropMail"
        self.status_code = int(status_code or 0)
        compact = re.sub(r"\s+", " ", str(text or "")).strip()
        if compact:
            compact = compact[:160]
            super().__init__(f"{self.op} http {self.status_code}: {compact}")
        else:
            super().__init__(f"{self.op} http {self.status_code}")


class DropMailAuthError(RuntimeError):
    pass

# ==========================================
# 全局配置
# ==========================================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MAIL_SOURCES = {
    "self_hosted_messages_api": True,
    "dropmail": False,
    "tempmail_lol": False,
    "skymail": False,
    "onesecmail": False,
    "duckmail": False,
    "mailtm": False,
}
MAIL_PROVIDER_MODE = "self_hosted_messages_api"
SELF_HOSTED_MESSAGES_API_URL = "http://38.76.206.21:8000/messages"
SELF_HOSTED_MESSAGES_DOMAINS = (
        "asdso.site",

)

DUCKMAIL_KEY = ""

SUB2API_ENABLED = True
SUB2API_URL = "http://uc.hicd.cc:8080"
SUB2API_EMAIL = "admin@sub2api.local"
SUB2API_PASSWORD = "1l123451"

# V2RayN 本地代理（默认走 127.0.0.1:10808，协议自动探测）
V2RAYN_PROXY = "127.0.0.1:7897"
DEFAULT_PROXY_PORT_CANDIDATES = ["10808", "7890", "7897", "7898", "7899", "20171"]
SCRIPT_BUILD = "v2rayn-10808-probe-2026-04-01-04"
DOMAIN_BLACKLIST_FILE = os.path.join(SCRIPT_DIR, "blocked_domains.txt")
RUNTIME_DOMAIN_BLACKLIST_FILE = os.path.join(SCRIPT_DIR, "blocked_domains_runtime.txt")
DOMAIN_QUARANTINE_FILE = os.path.join(SCRIPT_DIR, "domain_quarantine.json")
DOMAIN_STATS_FILE = os.path.join(SCRIPT_DIR, "domain_stats.json")
EXPERIMENT_CREATE_ACCOUNT_BRANCH_FILE = os.path.join(SCRIPT_DIR, "experiment_create_account_branches.jsonl")
EXPERIMENT2_RUN_RESULT_FILE = os.path.join(SCRIPT_DIR, "experiment2_run_results.jsonl")
AERO_ALPHA_SEEN_IDS_FILE = os.path.join(SCRIPT_DIR, "aero_alpha_seen_ids.json")
AERO_LOCAL_API_BASE = "http://127.0.0.1:8008"
AERO_ALPHA_PROVIDER = "infini-ai.eu.cc"
MAX_BLACKLIST_RETRY_PER_WORKER = 5
FAILED_CREATE_QUARANTINE_TTL_SECONDS = 12 * 60 * 60
FAILED_CREATE_BLACKLIST_THRESHOLD = 12
AUTH_SESSION_MINIMIZED_COOKIE = "auth-session-minimized-client-checksum"
SKYMAIL_CONFIG_FILE = os.path.join(SCRIPT_DIR, "skymail_config.json")
SKYMAIL_FALLBACK_CONFIG_FILE = os.path.join(SCRIPT_DIR, "config.json")

# ==========================================
# 临时邮箱 API
# ==========================================

MAILTM_BASE = "https://api.mail.tm"
TEMPMAIL_LOL_BASE = "https://api.tempmail.lol/v2"
DUCKMAIL_BASE = "https://api.duckmail.sbs"
ONESECMAIL_BASE = "https://www.1secmail.com/api/v1/"
DROPMAIL_TOKEN_URL = "https://dropmail.me/api/token/generate"
DROPMAIL_TOKEN_RENEW_URL = "https://dropmail.me/api/token/renew"
DROPMAIL_GRAPHQL_BASE = "https://dropmail.me/api/graphql"
SKYMAIL_TOKEN_TTL_SECONDS = 20 * 60
DROPMAIL_PRIMARY_DOMAINS = [
    "10mail.info",
    "mimimail.me",
    "mailpwr.com",
    "maximail.fyi",
]
DROPMAIL_BACKUP_DOMAINS = [
    "10mail.org",
    "emlhub.com",
    "emltmp.com",
    "freeml.net",
    "maximail.vip",
    "yomail.info",
]
DROPMAIL_API_TOKEN_FILE = os.path.join(SCRIPT_DIR, "dropmail_api_token.json")
DROPMAIL_GENERATE_TOKEN_LIFETIME = "1h"
DROPMAIL_RENEW_TOKEN_LIFETIME = "1d"
DROPMAIL_GENERATE_ROUTE_ROUNDS = 6
DROPMAIL_OUTAGE_BASE_SECONDS = 45
DROPMAIL_OUTAGE_MAX_SECONDS = 240
DROPMAIL_DOMAIN_CACHE_TTL = 300
DROPMAIL_MAX_ACTIVE_MAILBOXES = 5

DEFAULT_V2RAYN_PROXY = V2RAYN_PROXY
_PROXY_DIRECT_VALUES = {"", "off", "none", "direct"}
_SOCKS_PROXY_PORTS = {"1080", "10808"}
_BLOCKED_PROXY_LOCS = {"CN", "HK"}
_PROXY_TRACE_URL = "https://cloudflare.com/cdn-cgi/trace"
_domain_blacklist_lock = threading.Lock()
_domain_blacklist_cache = None
_domain_quarantine_lock = threading.Lock()
_domain_quarantine_cache = None
_domain_stats_lock = threading.Lock()
_domain_stats_cache = None
_dropmail_api_token_lock = threading.RLock()
_dropmail_api_token_cache = None
_dropmail_outage_lock = threading.Lock()
_dropmail_outage_until_ts = 0.0
_dropmail_outage_failures = 0
_dropmail_outage_reason = ""
_dropmail_domain_cache_lock = threading.Lock()
_dropmail_domain_cache = {"pool": "", "expires_at_ts": 0.0, "domains": []}
_dropmail_mailbox_slots = threading.BoundedSemaphore(DROPMAIL_MAX_ACTIVE_MAILBOXES)
_historical_success_lock = threading.Lock()
_historical_success_cache = None
_recent_success_lock = threading.Lock()
_recent_success_cache = None
_static_family_risk_lock = threading.Lock()
_static_family_risk_cache = None
_worker_count_hint = 1
_experiment2_force_family = "cloudvxz.com"
_experiment2_profile_name = "chrome146_current"
_experiment2_accept_language = "en-US,en;q=0.9"
_experiment2_domain_pool = [
    "xci.cloudvxz.com",
    "7kg.cloudvxz.com",
    "ix.cloudvxz.com",
    "q9l.cloudvxz.com",
    "ssi.cloudvxz.com",
    "m2.cloudvxz.com",
    "2fi.cloudvxz.com",
    "tv.cloudvxz.com",
    "53.cloudvxz.com",
    "jc.cloudvxz.com",
]
_beta_domain_pool = [
    "jc.cloudvxz.com",
    "2fi.cloudvxz.com",
]
_beta2_domain_pool = [
    "oh.cloudvxz.com",
    "z6.cloudvxz.com",
]
_beta2_low_domain_pool = [
    "ek.cloudvxz.com",
    "si.cloudvxz.com",
]
_alpha_infini_domain_pool = [
    "qir.infini-ai.eu.cc",
    "qor.infini-ai.eu.cc",
    "tlm.infini-ai.eu.cc",
    "dyx.infini-ai.eu.cc",
    "wal.infini-ai.eu.cc",
    "yfg.infini-ai.eu.cc",
    "vrx.infini-ai.eu.cc",
    "bru.infini-ai.eu.cc",
    "qjg.infini-ai.eu.cc",
    "xbe.infini-ai.eu.cc",
    "uhz.infini-ai.eu.cc",
    "rwq.infini-ai.eu.cc",
    "uvk.infini-ai.eu.cc",
    "mmz.infini-ai.eu.cc",
    "csb.infini-ai.eu.cc",
    "kxq.infini-ai.eu.cc",
    "nmm.infini-ai.eu.cc",
    "nyz.infini-ai.eu.cc",
    "skx.infini-ai.eu.cc",
    "kum.infini-ai.eu.cc",
]
_experiment_branch_lock = threading.Lock()
_run_context_local = threading.local()
_stage_limiters: Dict[str, Optional[threading.BoundedSemaphore]] = {
    "mailbox": None,
    "otp": None,
    "register": None,
}
_experiment_enabled = False
_experiment2_enabled = False
_beta_enabled = False
_beta2_enabled = False
_alpha_enabled = False
_skymail_preferred = False
_legacy_mail_mode = False
_dropmail_pool_mode = "primary"
_no_blacklist_mode = False
_browser_mode = False
_low_mode = False
_experiment2_fresh_cloudvxz = False
_experiment2_fresh_count = 8
_experiment2_fresh_lengths = [2]
_experiment2_fresh_pool: List[str] = []
_TRANSIENT_HTTP_STATUSES = {408, 409, 425, 429, 500, 502, 503, 504}
DEFAULT_RUN_RETRIES = 2
DEFAULT_EMAIL_SOURCE_ROUNDS = 4
TEMPMAIL_LOL_MAX_CREATE_ATTEMPTS = 30
SENTINEL_FLOW_SIGNUP_EMAIL = "authorize_continue"
SENTINEL_FLOW_CREATE_PASSWORD = "create_account_password"
SENTINEL_FLOW_EMAIL_OTP = "email_otp_verification"
SENTINEL_FLOW_PASSWORD_VERIFY = "password_verify"
SENTINEL_FLOW_ABOUT_YOU = "about_you"
SENTINEL_FLOW_WORKSPACE = "workspace"
SENTINEL_FLOW_CODEX_CONSENT = "sign_in_with_chatgpt_codex_consent"
_SENTINEL_SDK_SUPPORTED_FLOWS = {
    SENTINEL_FLOW_SIGNUP_EMAIL,
    SENTINEL_FLOW_CREATE_PASSWORD,
    SENTINEL_FLOW_EMAIL_OTP,
    SENTINEL_FLOW_PASSWORD_VERIFY,
    SENTINEL_FLOW_ABOUT_YOU,
    SENTINEL_FLOW_WORKSPACE,
    SENTINEL_FLOW_CODEX_CONSENT,
}
SENTINEL_SDK_CACHE_TTL = 480
_SENTINEL_BROWSER_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]
_sentinel_sdk_cache_lock = threading.Lock()
_sentinel_sdk_cache: Dict[str, Dict[str, Any]] = {}
_sentinel_requirements_cache_lock = threading.Lock()
_sentinel_requirements_cache: Dict[str, Any] = {"token": "", "expires_at_ts": 0.0}
_skymail_config_lock = threading.Lock()
_skymail_config_cache: Optional[Dict[str, Any]] = None
_skymail_token_lock = threading.RLock()
_skymail_token_cache: Dict[str, Any] = {"token": "", "expires_at_ts": 0.0}
_skymail_used_codes_lock = threading.Lock()
_skymail_used_codes: set = set()
_local_browser_profile_lock = threading.Lock()
_local_browser_profile_cache: Optional[tuple] = None
_run_session_id = (
    f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
    f"-p{os.getpid()}-{secrets.token_hex(2)}"
)


def _dedupe_keep_order(items: List[str]) -> List[str]:
    seen = set()
    result = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _current_run_context() -> Optional[Dict[str, Any]]:
    state = getattr(_run_context_local, "state", None)
    return state if isinstance(state, dict) else None


def _begin_run_context(*, run_id: str, worker_slot: int) -> None:
    _run_context_local.state = {
        "run_id": str(run_id),
        "worker_slot": int(worker_slot),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "attempts": 0,
        "branch_count": 0,
        "branch_results": [],
        "branch_domains": [],
    }


def _update_run_context(**kwargs: Any) -> None:
    ctx = _current_run_context()
    if ctx is None:
        return
    for key, value in kwargs.items():
        ctx[key] = value


def _append_run_context_value(key: str, value: Any) -> None:
    if value is None:
        return
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return
    ctx = _current_run_context()
    if ctx is None:
        return
    items = ctx.setdefault(key, [])
    if isinstance(items, list) and value not in items:
        items.append(value)


def _clear_run_context() -> None:
    if hasattr(_run_context_local, "state"):
        delattr(_run_context_local, "state")


def _read_jsonl_objects(path: str) -> List[Dict[str, Any]]:
    if not os.path.exists(path):
        return []
    rows: List[Dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except Exception:
                    continue
                if isinstance(item, dict):
                    rows.append(item)
    except Exception:
        return rows
    return rows


def _cloudvxz_domains_from_text_lines(path: str) -> List[str]:
    domains: List[str] = []
    if not os.path.exists(path):
        return domains
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for raw in f:
                value = str(raw or "").strip().lower()
                if value.endswith(".cloudvxz.com"):
                    domains.append(value)
    except Exception:
        return domains
    return domains


def _load_known_cloudvxz_domains() -> set:
    known = set(_cloudvxz_domains_from_text_lines(DOMAIN_BLACKLIST_FILE))
    known.update(_cloudvxz_domains_from_text_lines(RUNTIME_DOMAIN_BLACKLIST_FILE))
    for domain, entry in (_load_domain_quarantine() or {}).items():
        if not isinstance(entry, dict):
            continue
        if str(domain).strip().lower().endswith(".cloudvxz.com"):
            known.add(str(domain).strip().lower())
    for row in _read_jsonl_objects(EXPERIMENT_CREATE_ACCOUNT_BRANCH_FILE):
        domain = str(row.get("domain") or "").strip().lower()
        if domain.endswith(".cloudvxz.com"):
            known.add(domain)
    for row in _read_jsonl_objects(EXPERIMENT2_RUN_RESULT_FILE):
        domain = str(row.get("domain") or "").strip().lower()
        if domain.endswith(".cloudvxz.com"):
            known.add(domain)
    for domain in _experiment2_domain_pool:
        value = str(domain or "").strip().lower()
        if value.endswith(".cloudvxz.com"):
            known.add(value)
    for domain in _beta_domain_pool:
        value = str(domain or "").strip().lower()
        if value.endswith(".cloudvxz.com"):
            known.add(value)
    for domain in _beta2_domain_pool:
        value = str(domain or "").strip().lower()
        if value.endswith(".cloudvxz.com"):
            known.add(value)
    for domain in _beta2_low_domain_pool:
        value = str(domain or "").strip().lower()
        if value.endswith(".cloudvxz.com"):
            known.add(value)
    return known


def _parse_fresh_cloudvxz_lengths(raw: str) -> List[int]:
    values: List[int] = []
    for item in str(raw or "").split(","):
        item = item.strip()
        if not item:
            continue
        try:
            length = int(item)
        except Exception:
            continue
        if 1 <= length <= 8 and length not in values:
            values.append(length)
    return values or [2]


def _generate_fresh_cloudvxz_domains(count: int, lengths: List[int]) -> List[str]:
    target = max(1, int(count or 0))
    lengths = [length for length in lengths if 1 <= int(length) <= 8]
    if not lengths:
        lengths = [2]
    known = _load_known_cloudvxz_domains()
    chars = string.ascii_lowercase + string.digits
    generated: List[str] = []
    attempts = 0
    max_attempts = max(200, target * 200)
    while len(generated) < target and attempts < max_attempts:
        attempts += 1
        length = lengths[min(len(lengths) - 1, (attempts - 1) % len(lengths))]
        label = "".join(secrets.choice(chars) for _ in range(length))
        domain = f"{label}.cloudvxz.com"
        if domain in known:
            continue
        known.add(domain)
        generated.append(domain)
    return generated


def _resolve_stage_limit(requested: int) -> Optional[int]:
    if requested > 0:
        return requested
    return None


def _set_stage_limit(name: str, limit: Optional[int]) -> None:
    if limit is None:
        _stage_limiters[name] = None
        return
    _stage_limiters[name] = threading.BoundedSemaphore(max(1, limit))


def _retry_wait(attempt: int, *, base: float = 1.0, cap: float = 8.0) -> float:
    backoff = min(cap, base * (2 ** max(0, attempt - 1)))
    return backoff + random.uniform(0.0, 0.8)


def _request_with_retries(
    send_fn,
    *,
    label: str,
    attempts: int = 3,
    retry_statuses: Optional[set] = None,
):
    retry_statuses = retry_statuses or _TRANSIENT_HTTP_STATUSES
    last_resp = None
    last_exc = None

    for attempt in range(1, max(1, attempts) + 1):
        try:
            resp = send_fn()
            if resp.status_code not in retry_statuses or attempt >= attempts:
                return resp
            last_resp = resp
            wait_time = _retry_wait(attempt)
            print(
                f"[Retry] {label} transient status {resp.status_code}; "
                f"sleep {wait_time:.1f}s"
            )
            time.sleep(wait_time)
        except Exception as exc:
            last_exc = exc
            if attempt >= attempts:
                raise
            wait_time = _retry_wait(attempt)
            print(
                f"[Retry] {label} exception {type(exc).__name__}: {exc}; "
                f"sleep {wait_time:.1f}s"
            )
            time.sleep(wait_time)

    if last_resp is not None:
        return last_resp
    if last_exc is not None:
        raise last_exc
    raise RuntimeError(f"{label} failed without response")


def _sleep_poll_delay() -> None:
    time.sleep(random.uniform(2.0, 4.5))


def _sentinel_js_date_string() -> str:
    return datetime.now(timezone.utc).strftime("%a %b %d %Y %H:%M:%S GMT+0000 (UTC)")


def _sentinel_template_data(user_agent: str) -> List[Any]:
    return [
        3000,
        _sentinel_js_date_string(),
        0,
        0,
        user_agent,
        "https://auth.openai.com/log-in",
        "",
        "en-US",
        "en-US,en",
        0,
        "userAgent",
        "createElement",
        "location",
        0,
        str(uuid.uuid4()).lower(),
        "",
        8,
        int(time.time() * 1000),
        0,
        0,
        0,
        1,
        0,
        1,
        1,
    ]


def _sentinel_encode_payload(data: List[Any]) -> str:
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def _sentinel_hash_hex(value: str) -> str:
    acc = 2166136261
    for ch in value:
        acc ^= ord(ch)
        acc = (acc * 16777619) & 0xFFFFFFFF
    acc ^= acc >> 16
    acc = (acc * 2246822507) & 0xFFFFFFFF
    acc ^= acc >> 13
    acc = (acc * 3266489909) & 0xFFFFFFFF
    acc ^= acc >> 16
    return f"{acc & 0xFFFFFFFF:08x}"


def _extract_proxy_url_from_proxies(proxies: Any) -> str:
    if isinstance(proxies, dict):
        return str(proxies.get("https") or proxies.get("http") or "").strip()
    return ""


def _find_sentinel_browser_executable() -> str:
    for candidate in _SENTINEL_BROWSER_CANDIDATES:
        if os.path.exists(candidate):
            return candidate
    return ""


def _browser_proxy_url(proxy_url: str) -> str:
    normalized = _normalize_proxy_url(proxy_url)
    raw = str(normalized or "").strip()
    if raw.startswith("socks5h://"):
        return "socks5://" + raw[len("socks5h://"):]
    return raw


def _fetch_sentinel_sdk_token(
    *,
    flow: str,
    user_agent: str,
    proxy_url: str = "",
) -> str:
    node_cmd = _find_node_executable()
    if not _browser_mode:
        return ""
    if flow not in _SENTINEL_SDK_SUPPORTED_FLOWS:
        return ""
    if not node_cmd:
        print("[Warn] sentinel sdk token bridge skipped: node/nodejs not found")
        return ""
    browser_path = _find_sentinel_browser_executable()
    if not browser_path:
        return ""
    browser_proxy = _browser_proxy_url(proxy_url)

    node_script = r"""
function loadPlaywright() {
  const candidates = [
    'playwright-core',
    './node_modules/playwright-core',
    './test/node_modules/playwright-core',
    'playwright',
    './node_modules/playwright',
    './test/node_modules/playwright',
  ];
  for (const name of candidates) {
    try {
      return require(name);
    } catch (error) {}
  }
  throw new Error('Cannot find playwright-core/playwright');
}

const { chromium } = loadPlaywright();

const executablePath = process.argv[1];
const proxyServer = process.argv[2];
const flow = process.argv[3];
const userAgent = process.argv[4];

(async() => {
  const launchOptions = {
    executablePath,
    headless: true,
  };
  if (proxyServer) launchOptions.proxy = { server: proxyServer };
  const browser = await chromium.launch(launchOptions);
  const page = await browser.newPage({ userAgent });
  await page.goto('https://sentinel.openai.com/backend-api/sentinel/frame.html', { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.addScriptTag({ url: 'https://sentinel.openai.com/backend-api/sentinel/sdk.js' });
  await page.waitForFunction(() => window.SentinelSDK && typeof window.SentinelSDK.token === 'function', null, { timeout: 60000 });
  const token = await page.evaluate(async (flowName) => {
    const withTimeout = (promise, ms) => Promise.race([
      promise,
      new Promise(resolve => setTimeout(() => resolve('__TIMEOUT__'), ms)),
    ]);
    return await withTimeout(window.SentinelSDK.token(flowName), 12000);
  }, flow);
  await browser.close();
  process.stdout.write(String(token || ''));
})().catch(async (error) => {
  process.stderr.write(String((error && error.stack) || error || 'unknown error'));
  process.exit(1);
});
"""

    try:
        result = subprocess.run(
            [
                node_cmd,
                "-e",
                node_script,
                browser_path,
                browser_proxy,
                flow,
                user_agent,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=SCRIPT_DIR,
            timeout=120,
            check=False,
        )
    except Exception as e:
        print(f"[Warn] sentinel sdk token bridge failed: {e}")
        return ""

    token = (result.stdout or "").strip()
    if result.returncode != 0 or not token or token == "__TIMEOUT__":
        err = (result.stderr or "").strip()
        if err:
            print(f"[Warn] sentinel sdk token bridge error: {err[:300]}")
        return ""
    return token


def _fetch_sentinel_requirements_token() -> str:
    node_cmd = _find_node_executable()
    now = time.time()
    with _sentinel_requirements_cache_lock:
        token = str(_sentinel_requirements_cache.get("token") or "").strip()
        expires_at = float(_sentinel_requirements_cache.get("expires_at_ts") or 0.0)
        if token and expires_at > now + 10:
            return token

    probe_path = os.path.join(SCRIPT_DIR, "sentinel_node_vm_probe.js")
    if not node_cmd or not os.path.exists(probe_path):
        return ""
    try:
        result = subprocess.run(
            [node_cmd, probe_path, "requirements"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=SCRIPT_DIR,
            timeout=60,
            check=False,
        )
    except Exception as e:
        print(f"[Warn] sentinel requirements token bridge failed: {e}")
        return ""

    if result.returncode != 0:
        err = (result.stderr or "").strip()
        if err:
            print(f"[Warn] sentinel requirements token error: {err[:300]}")
        return ""

    try:
        payload = json.loads((result.stdout or "").strip() or "{}")
    except Exception as e:
        print(f"[Warn] sentinel requirements token json decode failed: {e}")
        return ""

    token = str((payload or {}).get("token") or "").strip()
    if token:
        ttl = min(
            SENTINEL_SDK_CACHE_TTL,
            max(30, int((payload or {}).get("len") and 120 or 120)),
        )
        with _sentinel_requirements_cache_lock:
            _sentinel_requirements_cache["token"] = token
            _sentinel_requirements_cache["expires_at_ts"] = time.time() + ttl
    return token


def _transform_turnstile_material(
    *,
    req_proof: str,
    req_json: Dict[str, Any],
) -> Dict[str, str]:
    node_cmd = _find_node_executable()
    probe_path = os.path.join(SCRIPT_DIR, "sentinel_node_vm_probe.js")
    if not node_cmd or not os.path.exists(probe_path):
        return {}

    temp_path = ""
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="\n",
            suffix=".json",
            delete=False,
            dir=SCRIPT_DIR,
        ) as f:
            json.dump(
                {
                    "req_proof": str(req_proof or ""),
                    "req_json": req_json or {},
                },
                f,
                ensure_ascii=False,
            )
            temp_path = f.name

        result = subprocess.run(
            [node_cmd, probe_path, "transform", temp_path],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=SCRIPT_DIR,
            timeout=90,
            check=False,
        )
    except Exception as e:
        print(f"[Warn] sentinel dx transform bridge failed: {e}")
        return {}
    finally:
        try:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)
        except Exception:
            pass

    if result.returncode != 0:
        err = (result.stderr or "").strip()
        if err:
            print(f"[Warn] sentinel dx transform error: {err[:300]}")
        return {}

    try:
        payload = json.loads((result.stdout or "").strip() or "{}")
    except Exception as e:
        print(f"[Warn] sentinel dx transform json decode failed: {e}")
        return {}

    t_val = str((payload or {}).get("t") or "").strip()
    p_val = str((payload or {}).get("enforcement") or "").strip()
    if t_val:
        try:
            decoded = base64.b64decode(t_val).decode("utf-8", "replace")
            if "__BIND_MISSING__" in decoded or decoded.startswith("TypeError:") or "TypeError:" in decoded:
                return {}
        except Exception:
            pass
    return {"t": t_val, "p": p_val}


def _build_sentinel_fallback_token(
    *,
    did: str,
    flow: str,
    user_agent: str,
    req_json: Dict[str, Any],
) -> str:
    c_token = str((req_json or {}).get("token") or "").strip()
    turnstile = (req_json or {}).get("turnstile") or {}
    t_val = ""
    if isinstance(turnstile, dict):
        dx = str(turnstile.get("dx") or "").strip()
        req_proof = str((req_json or {}).get("_requirements_token") or "").strip()
        if not req_proof:
            req_proof = _fetch_sentinel_requirements_token()
        if dx and req_proof:
            material = _transform_turnstile_material(req_proof=req_proof, req_json=req_json)
            t_val = str((material or {}).get("t") or "").strip()
            p_val = str((material or {}).get("p") or "").strip()
        else:
            p_val = ""
        if not t_val:
            t_val = dx
        if not p_val:
            p_val = _build_sentinel_pow_token(req_json, user_agent) or ""
    else:
        p_val = _build_sentinel_pow_token(req_json, user_agent) or ""
    return json.dumps(
        {"p": p_val, "t": t_val, "c": c_token, "id": did, "flow": flow}
    )


def _build_sentinel_pow_token(chat_req: Dict[str, Any], user_agent: str) -> str:
    pow_data = chat_req.get("proofofwork") or {}
    if not isinstance(pow_data, dict) or not pow_data.get("required"):
        return ""

    seed = str(pow_data.get("seed") or "").strip()
    difficulty = str(pow_data.get("difficulty") or "").strip().lower()
    if not seed or not difficulty:
        return ""

    base_data = _sentinel_template_data(user_agent)
    started = time.perf_counter()
    max_attempts = 500000
    for attempt in range(max_attempts):
        payload = list(base_data)
        payload[3] = attempt
        payload[9] = round((time.perf_counter() - started) * 1000)
        encoded = _sentinel_encode_payload(payload)
        hashed = _sentinel_hash_hex(seed + encoded)
        if hashed[: len(difficulty)] <= difficulty:
            return "gAAAAAB" + encoded + "~S"

    return ""


def _fetch_sentinel_payload(
    *,
    did: str,
    flow: str,
    user_agent: str,
    sec_ch_ua: str,
    proxies: Any,
    impersonate: str,
    label: str,
) -> Dict[str, Any]:
    req_token = _fetch_sentinel_requirements_token()
    body = json.dumps({"p": req_token, "id": did, "flow": flow})
    last_error = None

    for domain in ("https://sentinel.openai.com", "https://chatgpt.com"):
        try:
            resp = _request_with_retries(
                lambda domain=domain: requests.post(
                    f"{domain}/backend-api/sentinel/req",
                    headers={
                        "origin": domain,
                        "referer": f"{domain}/backend-api/sentinel/frame.html",
                        "content-type": "text/plain;charset=UTF-8",
                        "user-agent": user_agent,
                        "sec-ch-ua": sec_ch_ua,
                        "sec-ch-ua-mobile": "?0",
                        "sec-ch-ua-platform": '"Windows"',
                    },
                    data=body,
                    proxies=proxies,
                    impersonate=impersonate,
                    timeout=15,
                ),
                label=f"{label}:{domain}",
            )
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict):
                    if req_token:
                        data["_requirements_token"] = req_token
                    return data
                raise RuntimeError("sentinel payload is not a JSON object")
            last_error = RuntimeError(f"sentinel status {resp.status_code} from {domain}")
        except Exception as exc:
            last_error = exc
            print(f"[Retry] sentinel fallback from {domain}: {exc}")

    if last_error is not None:
        raise last_error
    raise RuntimeError("sentinel request failed without error")


@contextmanager
def _stage_slot(name: str):
    sem = _stage_limiters.get(name)
    if sem is None:
        yield
        return
    sem.acquire()
    try:
        yield
    finally:
        sem.release()


def _extract_email_domain(email_or_domain: str) -> str:
    value = str(email_or_domain or "").strip().lower()
    if "@" in value:
        value = value.rsplit("@", 1)[1]
    return value.strip()


def _domain_family(email_or_domain: str) -> str:
    domain = _extract_email_domain(email_or_domain)
    if not domain:
        return ""
    parts = [part for part in domain.split(".") if part]
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return domain


def _stats_mode_key(mode_key: Optional[str] = None) -> str:
    raw = str(mode_key or "").strip().lower()
    if raw in {"low", "browser"}:
        return raw
    return "browser" if _browser_mode else "low"


def _merge_stat_mapping(target: Dict[str, Any], source: Dict[str, Any]) -> None:
    for key, value in (source or {}).items():
        if isinstance(value, dict):
            existing = target.get(key)
            if not isinstance(existing, dict):
                existing = {}
                target[key] = existing
            _merge_stat_mapping(existing, value)
        elif isinstance(value, int):
            target[key] = int(target.get(key) or 0) + value
        else:
            target[key] = value


def _mode_stats_entry(
    entry: Dict[str, Any],
    mode_key: Optional[str] = None,
    *,
    create: bool = False,
) -> Dict[str, Any]:
    if not isinstance(entry, dict):
        return {}
    modes = entry.get("by_mode")
    if not isinstance(modes, dict):
        if not create:
            return {}
        modes = {}
        entry["by_mode"] = modes
    key = _stats_mode_key(mode_key)
    current = modes.get(key)
    if isinstance(current, dict):
        return current
    if not create:
        return {}
    current = {}
    modes[key] = current
    return current


def _load_domain_blacklist() -> set:
    global _domain_blacklist_cache
    if _no_blacklist_mode:
        return set()
    with _domain_blacklist_lock:
        if _domain_blacklist_cache is None:
            loaded = set()
            for path in (DOMAIN_BLACKLIST_FILE, RUNTIME_DOMAIN_BLACKLIST_FILE):
                if os.path.exists(path):
                    with open(path, "r", encoding="utf-8") as f:
                        for line in f:
                            domain = _extract_email_domain(line)
                            if domain:
                                loaded.add(domain)
            _domain_blacklist_cache = loaded
        return set(_domain_blacklist_cache)


def _read_domain_quarantine_file() -> Dict[str, Any]:
    if _no_blacklist_mode:
        return {}
    loaded: Dict[str, Any] = {}
    if os.path.exists(DOMAIN_QUARANTINE_FILE):
        try:
            with open(DOMAIN_QUARANTINE_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                loaded = raw
        except Exception:
            loaded = {}
    return loaded


def _cleanup_domain_quarantine_entries(data: Dict[str, Any]) -> Dict[str, Any]:
    now = int(time.time())
    cleaned: Dict[str, Any] = {}
    for domain, entry in (data or {}).items():
        normalized = _extract_email_domain(domain)
        if not normalized or not isinstance(entry, dict):
            continue
        by_mode = entry.get("by_mode")
        cleaned_modes: Dict[str, Any] = {}
        if isinstance(by_mode, dict):
            for mode_key, mode_entry in by_mode.items():
                if not isinstance(mode_entry, dict):
                    continue
                last_seen = int(mode_entry.get("last_seen") or 0)
                escalated = bool(mode_entry.get("escalated"))
                if not escalated and last_seen and (now - last_seen) > FAILED_CREATE_QUARANTINE_TTL_SECONDS:
                    continue
                cleaned_modes[str(mode_key).strip().lower()] = dict(mode_entry)
        if cleaned_modes:
            cleaned[normalized] = {"by_mode": cleaned_modes}
    return cleaned


def _save_domain_quarantine_locked() -> None:
    os.makedirs(os.path.dirname(DOMAIN_QUARANTINE_FILE), exist_ok=True)
    with open(DOMAIN_QUARANTINE_FILE, "w", encoding="utf-8") as f:
        json.dump(_domain_quarantine_cache or {}, f, ensure_ascii=False, indent=2, sort_keys=True)


def _load_domain_quarantine() -> Dict[str, Any]:
    global _domain_quarantine_cache
    if _no_blacklist_mode:
        return {}
    with _domain_quarantine_lock:
        if _domain_quarantine_cache is None:
            _domain_quarantine_cache = _cleanup_domain_quarantine_entries(_read_domain_quarantine_file())
            _save_domain_quarantine_locked()
        return json.loads(json.dumps(_domain_quarantine_cache))


def _quarantine_mode_entry(
    domain: str,
    mode_key: Optional[str] = None,
    *,
    create: bool = False,
) -> Dict[str, Any]:
    global _domain_quarantine_cache
    if _domain_quarantine_cache is None:
        _domain_quarantine_cache = _cleanup_domain_quarantine_entries(_read_domain_quarantine_file())
    entry = _domain_quarantine_cache.setdefault(domain, {})
    by_mode = entry.get("by_mode")
    if not isinstance(by_mode, dict):
        if not create:
            return {}
        by_mode = {}
        entry["by_mode"] = by_mode
    key = _stats_mode_key(mode_key)
    current = by_mode.get(key)
    if isinstance(current, dict):
        return current
    if not create:
        return {}
    current = {}
    by_mode[key] = current
    return current


def _is_domain_quarantined(email_or_domain: str, mode_key: Optional[str] = None) -> bool:
    domain = _extract_email_domain(email_or_domain)
    if not domain:
        return False
    data = _load_domain_quarantine()
    entry = data.get(domain)
    if not isinstance(entry, dict):
        return False
    by_mode = entry.get("by_mode")
    if not isinstance(by_mode, dict):
        return False
    current = by_mode.get(_stats_mode_key(mode_key))
    if not isinstance(current, dict):
        return False
    last_seen = int(current.get("last_seen") or 0)
    escalated = bool(current.get("escalated"))
    if escalated:
        return False
    if not last_seen:
        return False
    return (int(time.time()) - last_seen) <= FAILED_CREATE_QUARANTINE_TTL_SECONDS


def _domain_unavailable_reason(email_or_domain: str, mode_key: Optional[str] = None) -> str:
    if _no_blacklist_mode:
        return ""
    if _is_domain_blacklisted(email_or_domain):
        return "blacklisted"
    if _is_domain_quarantined(email_or_domain, mode_key=mode_key):
        return "quarantined"
    return ""


def _is_domain_blacklisted(email_or_domain: str) -> bool:
    domain = _extract_email_domain(email_or_domain)
    if not domain:
        return False
    return domain in _load_domain_blacklist()


def _filter_blacklisted_domains(domains: List[str]) -> List[str]:
    return [domain for domain in domains if not _domain_unavailable_reason(domain)]


def _read_domain_stats_file() -> Dict[str, Dict[str, Any]]:
    loaded: Dict[str, Dict[str, Any]] = {}
    if os.path.exists(DOMAIN_STATS_FILE):
        try:
            with open(DOMAIN_STATS_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                for domain, info in raw.items():
                    normalized = _domain_family(domain)
                    if normalized and isinstance(info, dict):
                        target = loaded.setdefault(normalized, {})
                        _merge_stat_mapping(target, info)
        except Exception:
            loaded = {}
    return loaded


def _load_historical_success_counts(mode_key: Optional[str] = None) -> Dict[str, int]:
    global _historical_success_cache
    cache_key = str(mode_key or "__all__").strip().lower() or "__all__"
    with _historical_success_lock:
        if not isinstance(_historical_success_cache, dict):
            _historical_success_cache = {}
        cached = _historical_success_cache.get(cache_key)
        if cached is None:
            counts: Dict[str, int] = {}
            tokens_dir = os.path.join(SCRIPT_DIR, "tokens")
            if os.path.isdir(tokens_dir):
                for name in os.listdir(tokens_dir):
                    if not name.endswith(".json"):
                        continue
                    path = os.path.join(tokens_dir, name)
                    try:
                        with open(path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        stored_mode = str(data.get("run_mode") or "").strip().lower()
                        if cache_key != "__all__":
                            if stored_mode != cache_key:
                                continue
                        family = _domain_family(data.get("email") or "")
                        if family:
                            counts[family] = counts.get(family, 0) + 1
                    except Exception:
                        continue
            _historical_success_cache[cache_key] = counts
        return dict(_historical_success_cache.get(cache_key) or {})


def _load_recent_success_counts(limit: int = 12, mode_key: Optional[str] = None) -> Dict[str, int]:
    global _recent_success_cache
    limit_key = max(1, limit)
    cache_key = f"{str(mode_key or '__all__').strip().lower() or '__all__'}:{limit_key}"
    mode_filter = cache_key.split(":", 1)[0]
    with _recent_success_lock:
        if not isinstance(_recent_success_cache, dict):
            _recent_success_cache = {}
        cached = _recent_success_cache.get(cache_key)
        if cached is None:
            counts: Dict[str, int] = {}
            tokens_dir = os.path.join(SCRIPT_DIR, "tokens")
            if os.path.isdir(tokens_dir):
                entries: List[tuple] = []
                for name in os.listdir(tokens_dir):
                    if not name.endswith(".json"):
                        continue
                    path = os.path.join(tokens_dir, name)
                    try:
                        entries.append((os.path.getmtime(path), path))
                    except Exception:
                        continue
                entries.sort(reverse=True)
                for _, path in entries[:limit_key]:
                    try:
                        with open(path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        stored_mode = str(data.get("run_mode") or "").strip().lower()
                        if mode_filter != "__all__":
                            if stored_mode != mode_filter:
                                continue
                        family = _domain_family(data.get("email") or "")
                        if family:
                            counts[family] = counts.get(family, 0) + 1
                    except Exception:
                        continue
            _recent_success_cache[cache_key] = counts
        return dict(_recent_success_cache.get(cache_key) or {})


def _load_static_family_risk() -> Dict[str, int]:
    global _static_family_risk_cache
    with _static_family_risk_lock:
        if _static_family_risk_cache is None:
            counts: Dict[str, int] = {}
            if os.path.exists(DOMAIN_BLACKLIST_FILE):
                with open(DOMAIN_BLACKLIST_FILE, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        family = _domain_family(line)
                        if family:
                            counts[family] = counts.get(family, 0) + 1
            _static_family_risk_cache = counts
        return dict(_static_family_risk_cache)


def _load_domain_stats() -> Dict[str, Dict[str, Any]]:
    global _domain_stats_cache
    with _domain_stats_lock:
        if _domain_stats_cache is None:
            _domain_stats_cache = _read_domain_stats_file()
        return json.loads(json.dumps(_domain_stats_cache))


def _save_domain_stats_locked() -> None:
    os.makedirs(os.path.dirname(DOMAIN_STATS_FILE), exist_ok=True)
    with open(DOMAIN_STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(_domain_stats_cache or {}, f, ensure_ascii=False, indent=2, sort_keys=True)


def _record_domain_outcome(email_or_domain: str, outcome: str) -> None:
    global _domain_stats_cache, _recent_success_cache
    domain = _domain_family(email_or_domain)
    if not domain:
        return

    current_cache = _read_domain_stats_file()
    with _domain_stats_lock:
        if _domain_stats_cache is None:
            _domain_stats_cache = current_cache
        entry = _domain_stats_cache.setdefault(domain, {})
        mode_entry = _mode_stats_entry(entry, create=True)
        for target in (entry, mode_entry):
            target["success"] = int(target.get("success") or 0)
            target["phone_required"] = int(target.get("phone_required") or 0)
            target["unsupported_email"] = int(target.get("unsupported_email") or 0)
            target["failed_to_create_account"] = int(target.get("failed_to_create_account") or 0)
            target["registration_disallowed"] = int(target.get("registration_disallowed") or 0)
            target["blacklist"] = int(target.get("blacklist") or 0)
            target["other_failure"] = int(target.get("other_failure") or 0)

            if outcome in target:
                target[outcome] += 1
            else:
                target["other_failure"] += 1
            target["last_outcome"] = outcome
            target["updated_at"] = int(time.time())
        entry["last_mode"] = _stats_mode_key()
        _recent_success_cache = None
        _save_domain_stats_locked()


def _domain_score(email_or_domain: str, mode_key: Optional[str] = None) -> int:
    domain = _domain_family(email_or_domain)
    if not domain:
        return 0
    entry = _load_domain_stats().get(domain) or {}
    active_mode = _stats_mode_key(mode_key)
    stats = _mode_stats_entry(entry, mode_key=active_mode) or {}
    recent_success = int(_load_recent_success_counts(mode_key=active_mode).get(domain) or 0)
    historical_success = int(_load_historical_success_counts(mode_key=active_mode).get(domain) or 0)
    static_risk = int(_load_static_family_risk().get(domain) or 0)
    success_total = int(stats.get("success") or 0) + historical_success
    phone_required = int(stats.get("phone_required") or 0)
    failed_to_create = int(stats.get("failed_to_create_account") or 0)
    registration_disallowed = int(stats.get("registration_disallowed") or 0)
    blacklist = int(stats.get("blacklist") or 0)
    unsupported = int(stats.get("unsupported_email") or 0)
    other_failure = int(stats.get("other_failure") or 0)
    success_gap = max(0, phone_required - success_total * 3)
    return (
        recent_success * 70
        + success_total * 14
        - success_gap * 2
        - unsupported * 20
        - failed_to_create * 12
        - registration_disallowed * 12
        - blacklist * 50
        - other_failure * 2
        - min(static_risk, 300) // 60
    )


def _prioritize_domains(domains: List[str]) -> List[str]:
    candidates = [d for d in domains if d]
    random.shuffle(candidates)
    candidates.sort(key=lambda domain: _domain_score(domain), reverse=True)
    return candidates


def _pick_domain(domains: List[str]) -> str:
    ranked = _prioritize_domains(domains)
    if not ranked:
        return ""
    floor = min(_domain_score(domain) for domain in ranked)
    weighted_domains: List[str] = []
    weights: List[float] = []
    for index, domain in enumerate(ranked):
        score = _domain_score(domain)
        # Keep lower-ranked families possible, but no longer equally likely.
        weight = max(1.0, float(score - floor + 3))
        weight /= 1.0 + index * 0.22
        weighted_domains.append(domain)
        weights.append(weight)
    return random.choices(weighted_domains, weights=weights, k=1)[0]


def _should_skip_low_score_domain(email_or_domain: str) -> bool:
    family = _domain_family(email_or_domain)
    if not family:
        return False

    entry = _load_domain_stats().get(family) or {}
    active_mode = _stats_mode_key()
    stats = _mode_stats_entry(entry, mode_key=active_mode) or {}
    success = int(stats.get("success") or 0) + int(_load_historical_success_counts(mode_key=active_mode).get(family) or 0)
    phone_required = int(stats.get("phone_required") or 0)
    failed_to_create = int(stats.get("failed_to_create_account") or 0)
    registration_disallowed = int(stats.get("registration_disallowed") or 0)
    blacklist = int(stats.get("blacklist") or 0)
    unsupported = int(stats.get("unsupported_email") or 0)

    if success > 0:
        return False
    if blacklist > 0 or unsupported > 0:
        return True
    if registration_disallowed >= 1:
        return True
    if failed_to_create >= 3:
        return True
    if phone_required >= 12:
        return True
    return False


def _should_temporarily_avoid_domain(email_or_domain: str) -> bool:
    family = _domain_family(email_or_domain)
    if not family:
        return False
    if _experiment2_enabled and family == _experiment2_force_family:
        return False
    if family in set(_preferred_domain_families(limit=4, score_window=80)):
        return False

    entry = _load_domain_stats().get(family) or {}
    active_mode = _stats_mode_key()
    stats = _mode_stats_entry(entry, mode_key=active_mode) or {}
    success = int(stats.get("success") or 0) + int(_load_historical_success_counts(mode_key=active_mode).get(family) or 0)
    phone_required = int(stats.get("phone_required") or 0)
    if phone_required < 18:
        return False
    if success >= 6 and phone_required < success * 4:
        return False

    pressure = phone_required / max(1, success + 1)
    if pressure < 4.0:
        return False

    chance = 0.18 + min(0.30, (pressure - 4.0) * 0.10)
    last_outcome = str(stats.get("last_outcome") or "").strip().lower()
    updated_at = int(stats.get("updated_at") or 0)
    if last_outcome == "phone_required" and updated_at and (time.time() - updated_at) < 1800:
        chance += 0.12
    chance = min(0.68, chance)
    return random.random() < chance


def _preferred_domain_families(limit: int = 4, score_window: int = 80) -> List[str]:
    stats = _load_domain_stats()
    active_mode = _stats_mode_key()
    historical = _load_historical_success_counts(mode_key=active_mode)
    families = sorted({family for family in [*stats.keys(), *historical.keys()] if family})
    if not families:
        return []

    recent = _load_recent_success_counts(mode_key=active_mode)
    recent_ranked = sorted(
        (family for family in families if int(recent.get(family) or 0) > 0),
        key=lambda family: (int(recent.get(family) or 0), _domain_score(family, mode_key=active_mode)),
        reverse=True,
    )
    if recent_ranked:
        return recent_ranked[:limit]

    ranked = sorted(
        ((family, _domain_score(family, mode_key=active_mode)) for family in families),
        key=lambda item: item[1],
        reverse=True,
    )
    best_score = ranked[0][1]
    preferred: List[str] = []
    for family, score in ranked:
        if preferred and score < best_score - score_window:
            break
        preferred.append(family)
        if len(preferred) >= limit:
            break
    return preferred[:limit]


def _fallback_login_families(limit: int = 2) -> List[str]:
    active_mode = _stats_mode_key()
    recent = _load_recent_success_counts(mode_key=active_mode)
    ranked = sorted(
        (family for family, count in recent.items() if int(count or 0) > 0),
        key=lambda family: (int(recent.get(family) or 0), _domain_score(family, mode_key=active_mode)),
        reverse=True,
    )
    if ranked:
        return ranked[:max(1, limit)]
    return _preferred_domain_families(limit=max(1, limit), score_window=80)




def _blacklist_email_domain(email_or_domain: str, reason: str = "") -> str:
    global _domain_blacklist_cache
    domain = _extract_email_domain(email_or_domain)
    if not domain:
        return ""
    if _no_blacklist_mode:
        print(f"[Blacklist] skipped due to --no-blacklist: {domain} reason={reason or 'n/a'}")
        return domain

    current_cache = _load_domain_blacklist()
    with _domain_blacklist_lock:
        if _domain_blacklist_cache is None:
            _domain_blacklist_cache = current_cache
        if domain in _domain_blacklist_cache:
            return domain
        _domain_blacklist_cache.add(domain)
        os.makedirs(os.path.dirname(RUNTIME_DOMAIN_BLACKLIST_FILE), exist_ok=True)
        with open(RUNTIME_DOMAIN_BLACKLIST_FILE, "a", encoding="utf-8", newline="\n") as f:
            f.write(domain)
            f.write("\n")

    if reason:
        print(f"[Blacklist] added domain {domain}: {reason}")
    else:
        print(f"[Blacklist] added domain {domain}")
    _record_domain_outcome(domain, "blacklist")
    return domain


def _quarantine_email_domain(email_or_domain: str, reason: str = "") -> Dict[str, Any]:
    global _domain_quarantine_cache
    domain = _extract_email_domain(email_or_domain)
    if not domain:
        return {"domain": "", "count": 0, "escalated": False}
    if _no_blacklist_mode:
        print(f"[Quarantine] skipped due to --no-blacklist: {domain} reason={reason or 'failed_to_create_account'}")
        return {
            "domain": domain,
            "count": 0,
            "escalated": False,
            "mode": _stats_mode_key(),
        }

    now = int(time.time())
    with _domain_quarantine_lock:
        if _domain_quarantine_cache is None:
            _domain_quarantine_cache = _cleanup_domain_quarantine_entries(_read_domain_quarantine_file())
        mode_entry = _quarantine_mode_entry(domain, create=True)
        count = int(mode_entry.get("count") or 0) + 1
        mode_entry["count"] = count
        mode_entry["reason"] = reason or "failed_to_create_account"
        mode_entry["first_seen"] = int(mode_entry.get("first_seen") or now)
        mode_entry["last_seen"] = now
        mode_entry["escalated"] = bool(mode_entry.get("escalated"))
        _save_domain_quarantine_locked()

    _record_domain_outcome(domain, "failed_to_create_account")

    escalated = count >= FAILED_CREATE_BLACKLIST_THRESHOLD
    if escalated:
        with _domain_quarantine_lock:
            if _domain_quarantine_cache is None:
                _domain_quarantine_cache = _cleanup_domain_quarantine_entries(_read_domain_quarantine_file())
            mode_entry = _quarantine_mode_entry(domain, create=True)
            mode_entry["escalated"] = True
            mode_entry["last_seen"] = int(time.time())
            _save_domain_quarantine_locked()
        _blacklist_email_domain(domain, f"{reason or 'failed_to_create_account'} threshold={count}")

    return {
        "domain": domain,
        "count": count,
        "escalated": escalated,
        "mode": _stats_mode_key(),
    }


def _response_json_or_empty(resp: Any) -> Dict[str, Any]:
    text = str(getattr(resp, "text", "") or "").strip()
    if not text:
        return {}
    try:
        data = resp.json()
        return data if isinstance(data, dict) else {}
    except Exception:
        try:
            data = json.loads(text)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}


def _blacklist_reason_from_response(resp: Any) -> str:
    payload = _response_json_or_empty(resp)
    error = payload.get("error")
    if not isinstance(error, dict):
        return ""

    message = str(error.get("message") or "").strip()
    code = str(error.get("code") or "").strip()

    if code == "unsupported_email" or message == "The email you provided is not supported.":
        return "unsupported_email"
    if message == "Failed to create account. Please try again.":
        return "failed_to_create_account"
    if code == "registration_disallowed" or message == "Sorry, we cannot create your account with the given information.":
        return "registration_disallowed"
    return ""


def _response_error_reason(resp: Any, *, fallback: str = "") -> str:
    payload = _response_json_or_empty(resp)
    error = payload.get("error")
    if isinstance(error, dict):
        code = str(error.get("code") or "").strip().lower()
        if code:
            return code
        message = str(error.get("message") or "").strip().lower()
        if message:
            compact = re.sub(r"[^a-z0-9]+", "_", message).strip("_")
            if compact:
                return compact[:80]
    return fallback.strip().lower()


def _raise_if_blacklistable_email_error(resp: Any, email: str, *, stage: str = "") -> None:
    reason = _blacklist_reason_from_response(resp)
    if not reason:
        return
    if reason == "failed_to_create_account":
        domain = _extract_email_domain(email)
        label = str(stage or "unknown").strip() or "unknown"
        print(f"[SentinelSuspect] keep domain {domain}: {reason} stage={label}")
        return
    if _no_blacklist_mode:
        domain = _extract_email_domain(email)
        print(f"[NoBlacklist] retry domain {domain}: {reason}")
        raise RetryNewEmail(f"retry domain {domain}: {reason}")
    domain = _blacklist_email_domain(email, reason)
    raise RetryNewEmail(f"blacklisted domain {domain}: {reason}")


def _candidate_proxy_urls(proxy: Optional[str]) -> List[str]:
    if proxy is None:
        raw = DEFAULT_V2RAYN_PROXY
    else:
        raw = str(proxy).strip()

    if not raw:
        return []

    lowered = raw.lower()
    if lowered == "auto":
        candidates: List[str] = []
        for port in DEFAULT_PROXY_PORT_CANDIDATES:
            candidates.extend(_candidate_proxy_urls(port))
        return _dedupe_keep_order(candidates)
    if lowered in _PROXY_DIRECT_VALUES:
        return []

    if "://" in raw:
        parsed = urlparse(raw)
        host = parsed.hostname or ""
        port = str(parsed.port or "")
        if host in {"127.0.0.1", "localhost"}:
            return _dedupe_keep_order([
                raw,
                f"socks5h://{host}:{port}",
                f"socks5://{host}:{port}",
                f"http://{host}:{port}",
            ])
        return [raw]

    if raw.isdigit():
        raw = f"127.0.0.1:{raw}"

    parsed = urlparse(f"placeholder://{raw}")
    host = parsed.hostname or ""
    port = str(parsed.port or "")
    if not host or not port:
        normalized = _normalize_proxy_url(raw)
        return [normalized] if normalized else []

    if host in {"127.0.0.1", "localhost"}:
        return _dedupe_keep_order([
            f"socks5h://{host}:{port}",
            f"socks5://{host}:{port}",
            f"http://{host}:{port}",
        ])

    if port in _SOCKS_PROXY_PORTS:
        return _dedupe_keep_order([
            f"socks5h://{host}:{port}",
            f"socks5://{host}:{port}",
            f"http://{host}:{port}",
        ])
    return [f"http://{host}:{port}"]


def _probe_proxy_trace(proxy_url: str, timeout: int = 10) -> Dict[str, str]:
    proxies = {"http": proxy_url, "https": proxy_url}
    s = requests.Session(proxies=proxies, impersonate="chrome")
    resp = s.get(_PROXY_TRACE_URL, timeout=timeout)
    resp.raise_for_status()
    data: Dict[str, str] = {"loc": "", "ip": ""}
    for line in resp.text.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key in data:
            data[key] = value
    return data
def _normalize_proxy_url(proxy: Optional[str]) -> Optional[str]:
    raw = DEFAULT_V2RAYN_PROXY if proxy is None else str(proxy).strip()
    if not raw:
        return None

    lowered = raw.lower()
    if lowered == "auto":
        raw = DEFAULT_V2RAYN_PROXY
        lowered = raw.lower()
    if lowered in _PROXY_DIRECT_VALUES:
        return None
    if "://" in raw:
        return raw
    if raw.isdigit():
        return f"socks5h://127.0.0.1:{raw}"

    parsed = urlparse(f"placeholder://{raw}")
    host = parsed.hostname or ""
    port = str(parsed.port or "")
    if host and port:
        scheme = "socks5h" if port in _SOCKS_PROXY_PORTS else "http"
        return f"{scheme}://{host}:{port}"

    return raw


def _build_proxies(proxy: Optional[str]) -> Any:
    if proxy is None:
        return None
    proxy_url = _normalize_proxy_url(proxy)
    if not proxy_url:
        return None
    return {"http": proxy_url, "https": proxy_url}


def _safe_export_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", (value or "").strip())
    return cleaned.strip("._") or "unknown"


def _append_text_line(path: str, value: str) -> None:
    text = (value or "").strip()
    if not text:
        return
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(text)
        f.write("\n")


def _append_jsonl_line(path: str, payload: Dict[str, Any], *, lock: Optional[threading.Lock] = None) -> None:
    if lock is None:
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(payload, ensure_ascii=False))
            f.write("\n")
        return
    with lock:
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(payload, ensure_ascii=False))
            f.write("\n")


def _read_json_file_or_default(path: str, default: Any) -> Any:
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _write_json_file(path: str, payload: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=True)


def _token_exports(token_json: str) -> Dict[str, str]:
    data = json.loads(token_json)
    return {
        "email": str(data.get("email") or "").strip(),
        "access_token": str(data.get("access_token") or "").strip(),
        "refresh_token": str(data.get("refresh_token") or "").strip(),
    }


def _token_payload_or_empty(token_json: str) -> Dict[str, Any]:
    try:
        data = json.loads(token_json)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _is_experiment_token_payload(payload: Dict[str, Any]) -> bool:
    token_type = str(payload.get("type") or "").strip().lower()
    return token_type == "chatgpt_experiment"


def _is_locally_promoted_experiment_payload(payload: Dict[str, Any]) -> bool:
    return str(payload.get("source_type") or "").strip().lower() == "chatgpt_experiment"


def _looks_like_formal_refresh_token(refresh_token: str) -> bool:
    token = str(refresh_token or "").strip()
    if len(token) < 40:
        return False
    return token.startswith("rt_") or token.startswith("oaistb_rt_")


def _should_treat_as_formal_token(payload: Dict[str, Any]) -> bool:
    if not isinstance(payload, dict):
        return False
    if _is_experiment_token_payload(payload):
        return False
    if _is_locally_promoted_experiment_payload(payload):
        return False
    return _looks_like_formal_refresh_token(str(payload.get("refresh_token") or ""))


def _token_export_filename(email: str) -> str:
    stamp = time.time_ns()
    suffix = uuid.uuid4().hex[:8]
    return f"token_{_safe_export_name(email)}_{stamp}_{suffix}.json"


def _persist_token_artifacts(
    base_dir: str, token_json: str, file_lock: threading.Lock
) -> Dict[str, str]:
    payload = _token_payload_or_empty(token_json)
    source_is_experiment = _is_experiment_token_payload(payload)
    was_local_promotion = False
    is_experiment = not _should_treat_as_formal_token(payload)
    exported = {"email": "", "access_token": "", "refresh_token": ""}
    try:
        exported.update(_token_exports(token_json))
    except Exception:
        pass
    if isinstance(payload, dict) and payload:
        payload["run_mode"] = _stats_mode_key()
        payload["low_mode"] = bool(_low_mode)
        payload["browser_mode"] = bool(_browser_mode)
        payload["saved_at"] = int(time.time())
        token_json = json.dumps(payload, ensure_ascii=False)
    tokens_dir = os.path.join(
        base_dir,
        "tokens_experiment" if is_experiment else "tokens",
    )
    ak_path = os.path.join(base_dir, "ak.txt")
    rk_path = os.path.join(base_dir, "rk.txt")
    os.makedirs(tokens_dir, exist_ok=True)

    token_path = os.path.join(
        tokens_dir, _token_export_filename(exported.get("email", ""))
    )
    with file_lock:
        with open(token_path, "w", encoding="utf-8") as f:
            f.write(token_json)
        if not is_experiment:
            _append_text_line(ak_path, exported.get("access_token", ""))
            _append_text_line(rk_path, exported.get("refresh_token", ""))

    return {
        "token_path": token_path,
        "ak_path": ak_path if not is_experiment else "",
        "rk_path": rk_path if not is_experiment else "",
        "access_token": exported.get("access_token", ""),
        "refresh_token": exported.get("refresh_token", ""),
        "email": exported.get("email", ""),
        "is_experiment": is_experiment,
        "source_is_experiment": source_is_experiment,
        "was_local_promotion": was_local_promotion,
        "stored_token_json": token_json,
    }


def _aero_alpha_seen_ids() -> set:
    raw = _read_json_file_or_default(AERO_ALPHA_SEEN_IDS_FILE, [])
    if isinstance(raw, list):
        return {int(item) for item in raw if str(item).strip().isdigit()}
    return set()


def _save_aero_alpha_seen_ids(seen_ids: set) -> None:
    payload = sorted(int(item) for item in seen_ids if isinstance(item, int) or str(item).isdigit())
    _write_json_file(AERO_ALPHA_SEEN_IDS_FILE, payload)


def _aero_alpha_request(method: str, path: str, *, json_body: Optional[Dict[str, Any]] = None, timeout: int = 20) -> Any:
    url = AERO_LOCAL_API_BASE.rstrip("/") + path
    if method.upper() == "GET":
        return requests.get(url, timeout=timeout, impersonate="chrome")
    if method.upper() == "POST":
        return requests.post(url, json=json_body, timeout=timeout, impersonate="chrome")
    if method.upper() == "PUT":
        return requests.put(url, json=json_body, timeout=timeout, impersonate="chrome")
    raise ValueError(f"unsupported method: {method}")


def _aero_alpha_fetch_ready_account(*, timeout_seconds: int = 180) -> Optional[Dict[str, Any]]:
    settings_resp = _aero_alpha_request("GET", "/api/settings")
    if settings_resp.status_code != 200:
        raise RuntimeError(f"aero settings read failed: {settings_resp.status_code}: {settings_resp.text[:200]}")
    settings = settings_resp.json() if settings_resp.text.strip() else {}
    values = settings.get("values") or {}
    if str(values.get("email_provider") or "").strip() != AERO_ALPHA_PROVIDER:
        update_resp = _aero_alpha_request("PUT", "/api/settings", json_body={"values": {"email_provider": AERO_ALPHA_PROVIDER}})
        if update_resp.status_code != 200:
            raise RuntimeError(f"aero settings update failed: {update_resp.status_code}: {update_resp.text[:200]}")

    seen_ids = _aero_alpha_seen_ids()
    start_payload = {
        "threads": 1,
        "target_accounts": 1,
        "min_sleep": 0,
        "max_sleep": 0,
        "proxy": "Auto",
    }
    start_resp = _aero_alpha_request("POST", "/api/start", json_body=start_payload, timeout=30)
    if start_resp.status_code not in (200, 409):
        raise RuntimeError(f"aero start failed: {start_resp.status_code}: {start_resp.text[:200]}")

    deadline = time.time() + max(30, timeout_seconds)
    latest_candidate: Optional[Dict[str, Any]] = None
    while time.time() < deadline:
        acc_resp = _aero_alpha_request("GET", "/api/accounts")
        if acc_resp.status_code == 200:
            items = acc_resp.json() if acc_resp.text.strip() else []
            if isinstance(items, list):
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    account_id = int(item.get("Id") or 0)
                    email = str(item.get("Email") or "").strip()
                    status = str(item.get("Status") or "").strip().lower()
                    if account_id <= 0 or account_id in seen_ids:
                        continue
                    if not email.lower().endswith(f".{AERO_ALPHA_PROVIDER}") and not email.lower().endswith(f"@{AERO_ALPHA_PROVIDER}"):
                        continue
                    latest_candidate = item
                    if status == "success":
                        seen_ids.add(account_id)
                        _save_aero_alpha_seen_ids(seen_ids)
                        try:
                            _aero_alpha_request("POST", "/api/stop", json_body={})
                        except Exception:
                            pass
                        return item
        time.sleep(4)

    try:
        _aero_alpha_request("POST", "/api/stop", json_body={})
    except Exception:
        pass
    if latest_candidate is not None:
        raise RuntimeError(f"aero alpha latest account not ready: {latest_candidate}")
    raise RuntimeError("aero alpha timed out waiting for new account")


def _aero_alpha_token_json(timeout_seconds: int = 180) -> Optional[str]:
    account = _aero_alpha_fetch_ready_account(timeout_seconds=timeout_seconds)
    if not account:
        return None
    account_id = int(account.get("Id") or 0)
    if account_id <= 0:
        raise RuntimeError(f"aero alpha invalid account id: {account}")

    tokens_resp = _aero_alpha_request("GET", f"/api/vault/accounts/{account_id}/tokens", timeout=30)
    if tokens_resp.status_code != 200:
        raise RuntimeError(f"aero token fetch failed: {tokens_resp.status_code}: {tokens_resp.text[:200]}")
    tokens = tokens_resp.json() if tokens_resp.text.strip() else {}
    access_token = str(tokens.get("access_token") or "").strip()
    refresh_token = str(tokens.get("refresh_token") or "").strip()
    device_id = str(tokens.get("device_id") or "").strip()
    email = str(account.get("Email") or "").strip()
    password = str(account.get("Password") or "").strip()
    if not access_token or not refresh_token or not email:
        raise RuntimeError(f"aero alpha incomplete tokens: {tokens}")

    payload = {
        "email": email,
        "password": password,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "device_id": device_id,
        "type": "codex",
        "source_type": "aero_alpha",
        "provider": AERO_ALPHA_PROVIDER,
        "aero_account_id": account_id,
    }
    return json.dumps(payload, ensure_ascii=False)


def _move_file_with_unique_name(src_path: str, dst_dir: str) -> str:
    os.makedirs(dst_dir, exist_ok=True)
    name = os.path.basename(src_path)
    stem, ext = os.path.splitext(name)
    candidate = os.path.join(dst_dir, name)
    counter = 1
    while os.path.exists(candidate):
        candidate = os.path.join(dst_dir, f"{stem}_{counter}{ext}")
        counter += 1
    os.replace(src_path, candidate)
    return candidate


def _repair_token_exports(base_dir: str) -> Dict[str, int]:
    tokens_dir = os.path.join(base_dir, "tokens")
    experiment_dir = os.path.join(base_dir, "tokens_experiment")
    ak_path = os.path.join(base_dir, "ak.txt")
    rk_path = os.path.join(base_dir, "rk.txt")
    repaired = {"moved_invalid": 0, "moved_formal": 0, "rebuilt": 0}
    valid_token_paths: List[str] = []

    if os.path.isdir(tokens_dir):
        for name in os.listdir(tokens_dir):
            if not name.endswith(".json"):
                continue
            path = os.path.join(tokens_dir, name)
            try:
                payload = json.load(open(path, "r", encoding="utf-8"))
            except Exception:
                continue
            if _should_treat_as_formal_token(payload):
                valid_token_paths.append(path)
                continue
            _move_file_with_unique_name(path, experiment_dir)
            repaired["moved_invalid"] += 1

    if os.path.isdir(experiment_dir):
        for name in os.listdir(experiment_dir):
            if not name.endswith(".json"):
                continue
            path = os.path.join(experiment_dir, name)
            try:
                payload = json.load(open(path, "r", encoding="utf-8"))
            except Exception:
                continue
            if not _should_treat_as_formal_token(payload):
                continue
            moved = _move_file_with_unique_name(path, tokens_dir)
            valid_token_paths.append(moved)
            repaired["moved_formal"] += 1

    access_tokens: List[str] = []
    refresh_tokens: List[str] = []
    for path in sorted(valid_token_paths):
        try:
            payload = json.load(open(path, "r", encoding="utf-8"))
        except Exception:
            continue
        access_token = str(payload.get("access_token") or "").strip()
        refresh_token = str(payload.get("refresh_token") or "").strip()
        if access_token:
            access_tokens.append(access_token)
        if refresh_token:
            refresh_tokens.append(refresh_token)

    with open(ak_path, "w", encoding="utf-8", newline="\n") as f:
        for token in access_tokens:
            f.write(token)
            f.write("\n")
    with open(rk_path, "w", encoding="utf-8", newline="\n") as f:
        for token in refresh_tokens:
            f.write(token)
            f.write("\n")

    repaired["rebuilt"] = len(valid_token_paths)
    return repaired


def _dropmail_json_headers() -> Dict[str, Any]:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _load_dropmail_api_token_file() -> Dict[str, Any]:
    if not os.path.exists(DROPMAIL_API_TOKEN_FILE):
        return {}
    try:
        with open(DROPMAIL_API_TOKEN_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_dropmail_api_token_file(data: Dict[str, Any]) -> None:
    try:
        with open(DROPMAIL_API_TOKEN_FILE, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _dropmail_cached_api_token(*, allow_stale: bool = False) -> str:
    global _dropmail_api_token_cache
    now = time.time()
    with _dropmail_api_token_lock:
        cached = _dropmail_api_token_cache
        if not isinstance(cached, dict):
            cached = _load_dropmail_api_token_file()
            _dropmail_api_token_cache = cached if cached else {}
        token = str((cached or {}).get("token") or "").strip()
        expires_at = float((cached or {}).get("expires_at_ts") or 0)
        if token and (allow_stale or expires_at > now + 30):
            return token
    return ""


def _dropmail_store_api_token(token: str, ttl_seconds: int = 55 * 60) -> None:
    global _dropmail_api_token_cache
    token = str(token or "").strip()
    if not token:
        return
    payload = {
        "token": token,
        "expires_at_ts": time.time() + max(60, int(ttl_seconds)),
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }
    with _dropmail_api_token_lock:
        _dropmail_api_token_cache = payload
        _save_dropmail_api_token_file(payload)


def _dropmail_clear_api_token() -> None:
    global _dropmail_api_token_cache
    with _dropmail_api_token_lock:
        _dropmail_api_token_cache = {}
        try:
            if os.path.exists(DROPMAIL_API_TOKEN_FILE):
                os.remove(DROPMAIL_API_TOKEN_FILE)
        except Exception:
            pass


def _dropmail_allowed_domains() -> List[str]:
    mode = str(_dropmail_pool_mode or "primary").strip().lower()
    if mode == "backup":
        return list(DROPMAIL_BACKUP_DOMAINS)
    if mode == "all":
        merged: List[str] = []
        for domain in DROPMAIL_PRIMARY_DOMAINS + DROPMAIL_BACKUP_DOMAINS:
            if domain not in merged:
                merged.append(domain)
        return merged
    return list(DROPMAIL_PRIMARY_DOMAINS)


def _dropmail_service_status() -> Tuple[bool, float, str]:
    with _dropmail_outage_lock:
        remaining = max(0.0, float(_dropmail_outage_until_ts or 0.0) - time.time())
        reason = str(_dropmail_outage_reason or "").strip()
    return remaining <= 0.0, remaining, reason


def _dropmail_mark_transient_outage(status_code: int, reason: str = "") -> float:
    global _dropmail_outage_until_ts, _dropmail_outage_failures, _dropmail_outage_reason
    with _dropmail_outage_lock:
        _dropmail_outage_failures = min(6, max(1, int(_dropmail_outage_failures or 0) + 1))
        backoff = min(
            DROPMAIL_OUTAGE_MAX_SECONDS,
            DROPMAIL_OUTAGE_BASE_SECONDS * _dropmail_outage_failures,
        )
        backoff += random.uniform(0.0, min(8.0, backoff * 0.15))
        _dropmail_outage_until_ts = max(float(_dropmail_outage_until_ts or 0.0), time.time() + backoff)
        _dropmail_outage_reason = str(reason or f"http_{int(status_code or 0)}").strip()
        return max(0.0, _dropmail_outage_until_ts - time.time())


def _dropmail_clear_transient_outage() -> None:
    global _dropmail_outage_until_ts, _dropmail_outage_failures, _dropmail_outage_reason
    with _dropmail_outage_lock:
        _dropmail_outage_until_ts = 0.0
        _dropmail_outage_failures = 0
        _dropmail_outage_reason = ""


def _dropmail_cached_domains() -> List[Dict[str, Any]]:
    now = time.time()
    pool = str(_dropmail_pool_mode or "primary").strip().lower()
    with _dropmail_domain_cache_lock:
        cached_pool = str(_dropmail_domain_cache.get("pool") or "").strip().lower()
        expires_at = float(_dropmail_domain_cache.get("expires_at_ts") or 0.0)
        items = _dropmail_domain_cache.get("domains") or []
        if cached_pool == pool and expires_at > now and isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    return []


def _dropmail_store_domains(domains: List[Dict[str, Any]]) -> None:
    pool = str(_dropmail_pool_mode or "primary").strip().lower()
    items = [item for item in (domains or []) if isinstance(item, dict)]
    with _dropmail_domain_cache_lock:
        _dropmail_domain_cache["pool"] = pool
        _dropmail_domain_cache["expires_at_ts"] = time.time() + DROPMAIL_DOMAIN_CACHE_TTL
        _dropmail_domain_cache["domains"] = items


def _dropmail_valid_cached_token(*, allow_stale: bool = False) -> str:
    token = _dropmail_cached_api_token(allow_stale=allow_stale)
    return str(token or "").strip()


def _dropmail_token_ttl_seconds(lifetime: str = "") -> int:
    key = str(lifetime or DROPMAIL_RENEW_TOKEN_LIFETIME or "1d").strip().lower()
    mapping = {
        "1h": 55 * 60,
        "1d": 23 * 60 * 60,
        "7d": 6 * 24 * 60 * 60 + 23 * 60 * 60,
        "30d": 29 * 24 * 60 * 60 + 23 * 60 * 60,
        "90d": 89 * 24 * 60 * 60 + 23 * 60 * 60,
    }
    return int(mapping.get(key, 23 * 60 * 60))


def _dropmail_generate_api_token(proxies: Any = None) -> str:
    lifetime = str(DROPMAIL_GENERATE_TOKEN_LIFETIME or "1h").strip().lower() or "1h"
    request_body = json.dumps({"type": "af", "lifetime": lifetime})

    def _run_generate(req_proxies: Any, label: str):
        return _request_with_retries(
            lambda: requests.post(
                DROPMAIL_TOKEN_URL,
                headers=_dropmail_json_headers(),
                data=request_body,
                proxies=req_proxies,
                impersonate="chrome",
                timeout=20,
            ),
            label=label,
            attempts=3,
            retry_statuses={403, 429, 500, 502, 503, 504},
        )

    proxy_url = _extract_proxy_url_from_proxies(proxies)
    route_attempts: List[Tuple[str, Any]] = [("proxy", proxies)]
    if proxy_url:
        route_attempts.append(("direct", None))

    rounds = max(1, int(DROPMAIL_GENERATE_ROUTE_ROUNDS or 1))
    resp = None
    last_proxy_like_failure = False
    for round_index in range(rounds):
        for route_name, route_proxies in route_attempts:
            if round_index > 0 or route_name != route_attempts[0][0]:
                time.sleep(0.45 + random.uniform(0.0, 0.9))
            label = "dropmail-token-generate" if route_name == "proxy" else "dropmail-token-generate-direct"
            current = _run_generate(route_proxies, label)
            resp = current
            if current.status_code == 200:
                if route_name == "direct" and proxy_url:
                    print("[*] DropMail token 改走直连生成")
                round_index = rounds
                break
            if current.status_code in {402, 403, 429, 500, 502, 503, 504}:
                last_proxy_like_failure = True
                continue
            round_index = rounds
            break
        else:
            if round_index + 1 < rounds:
                time.sleep(0.6 + random.uniform(0.0, 0.8))
            continue
        break
    if resp is None:
        raise RuntimeError("DropMail token request missing response")
    if resp.status_code in (402, 403):
        cached = _dropmail_valid_cached_token(allow_stale=True)
        if cached:
            _dropmail_store_api_token(cached, ttl_seconds=30 * 60)
            return cached
        raise DropMailHTTPError("DropMail token", resp.status_code, getattr(resp, "text", ""))
    if resp.status_code == 401:
        _dropmail_clear_api_token()
        raise DropMailAuthError("DropMail token unauthorized")
    if resp.status_code != 200:
        if resp.status_code in {429, 500, 502, 503, 504}:
            _dropmail_mark_transient_outage(resp.status_code, "token_generate")
        elif last_proxy_like_failure and resp.status_code == 402:
            _dropmail_mark_transient_outage(resp.status_code, "token_generate_captcha")
        raise DropMailHTTPError("DropMail token", resp.status_code, getattr(resp, "text", ""))
    data = resp.json() if resp.text.strip() else {}
    token = str((data or {}).get("token") or "").strip()
    if not token:
        raise RuntimeError("DropMail token missing")
    _dropmail_store_api_token(token, ttl_seconds=_dropmail_token_ttl_seconds(lifetime))
    return token


def _dropmail_renew_api_token(existing_token: str, proxies: Any = None) -> str:
    token = str(existing_token or "").strip()
    if not token:
        raise DropMailAuthError("DropMail renew missing token")
    lifetime = str(DROPMAIL_RENEW_TOKEN_LIFETIME or "1d").strip().lower() or "1d"
    resp = _request_with_retries(
        lambda: requests.post(
            DROPMAIL_TOKEN_RENEW_URL,
            headers=_dropmail_json_headers(),
            data=json.dumps({"token": token, "lifetime": lifetime}),
            proxies=proxies,
            impersonate="chrome",
            timeout=20,
        ),
        label="dropmail-token-renew",
        attempts=3,
        retry_statuses={403, 429, 500, 502, 503, 504},
    )
    body_text = getattr(resp, "text", "") or ""
    lowered = body_text.lower()
    if resp.status_code == 200:
        data = resp.json() if body_text.strip() else {}
        renewed = str((data or {}).get("token") or "").strip() or token
        _dropmail_store_api_token(renewed, ttl_seconds=_dropmail_token_ttl_seconds(lifetime))
        return renewed
    if resp.status_code == 400:
        if "invalid_token" in lowered or "token_expired" in lowered:
            raise DropMailAuthError("DropMail renew invalid_token")
        raise DropMailHTTPError("DropMail renew", resp.status_code, body_text)
    if resp.status_code in (402, 403):
        if "captcha_required" in lowered:
            _dropmail_store_api_token(token, ttl_seconds=30 * 60)
            return token
        if "invalid_token" in lowered or "token_expired" in lowered or "authentication_error" in lowered:
            raise DropMailAuthError("DropMail renew unauthorized")
        raise DropMailHTTPError("DropMail renew", resp.status_code, body_text)
    if resp.status_code in {429, 500, 502, 503, 504}:
        _dropmail_mark_transient_outage(resp.status_code, "token_renew")
    raise DropMailHTTPError("DropMail renew", resp.status_code, body_text)


def _dropmail_acquire_api_token(proxies: Any = None, *, force_refresh: bool = False) -> str:
    cached = "" if force_refresh else _dropmail_valid_cached_token()
    if cached:
        return cached
    with _dropmail_api_token_lock:
        cached = "" if force_refresh else _dropmail_valid_cached_token()
        if cached:
            return cached
        stale = _dropmail_valid_cached_token(allow_stale=True)
        if stale:
            try:
                return _dropmail_renew_api_token(stale, proxies)
            except DropMailAuthError:
                _dropmail_clear_api_token()
            except DropMailHTTPError as e:
                if e.status_code in {402, 429, 500, 502, 503, 504}:
                    _dropmail_store_api_token(stale, ttl_seconds=30 * 60)
                    return stale
        return _dropmail_generate_api_token(proxies)


def _dropmail_graphql(
    token: str,
    query: str,
    variables: Optional[Dict[str, Any]] = None,
    proxies: Any = None,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {"query": query}
    if variables is not None:
        body["variables"] = variables
    request_body = json.dumps(body)

    def _run_graphql(req_proxies: Any, label: str):
        return _request_with_retries(
            lambda: requests.post(
                f"{DROPMAIL_GRAPHQL_BASE}/{token}",
                headers=_dropmail_json_headers(),
                data=request_body,
                proxies=req_proxies,
                impersonate="chrome",
                timeout=20,
            ),
            label=label,
            attempts=3,
            retry_statuses={429, 500, 502, 503, 504},
        )

    proxy_url = _extract_proxy_url_from_proxies(proxies)
    try:
        resp = _run_graphql(proxies, "dropmail-graphql")
    except Exception:
        if not proxy_url:
            raise
        print("[*] DropMail graphql 改走直连回退")
        resp = _run_graphql(None, "dropmail-graphql-direct")
    if proxy_url and resp.status_code in {429, 500, 502, 503, 504}:
        direct_resp = _run_graphql(None, "dropmail-graphql-direct")
        if direct_resp.status_code == 200:
            print("[*] DropMail graphql 改走直连回退")
        resp = direct_resp
    if resp.status_code == 401:
        _dropmail_clear_api_token()
        raise DropMailAuthError("DropMail graphql unauthorized")
    if resp.status_code == 403:
        body_text = getattr(resp, "text", "") or ""
        lowered = body_text.lower()
        if "token_expired" in lowered or "authentication_error" in lowered:
            _dropmail_clear_api_token()
            raise DropMailAuthError("DropMail graphql token_expired")
        raise DropMailHTTPError("DropMail graphql", resp.status_code, body_text)
    if resp.status_code != 200:
        if resp.status_code in {429, 500, 502, 503, 504}:
            _dropmail_mark_transient_outage(resp.status_code, "graphql")
        raise DropMailHTTPError("DropMail graphql", resp.status_code, getattr(resp, "text", ""))
    data = resp.json() if resp.text.strip() else {}
    errors = data.get("errors") or []
    if errors:
        first = errors[0] if isinstance(errors, list) and errors else {}
        if isinstance(first, dict):
            message = str(first.get("message") or "DropMail graphql error").strip()
            lowered = message.lower()
            if "unauthorized" in lowered or ("invalid" in lowered and "token" in lowered):
                _dropmail_clear_api_token()
                raise DropMailAuthError(message or "DropMail graphql unauthorized")
            raise RuntimeError(message)
        raise RuntimeError("DropMail graphql error")
    result = data.get("data")
    return result if isinstance(result, dict) else {}


def _dropmail_list_domains(proxies: Any = None, api_token: str = "") -> List[Dict[str, Any]]:
    cached_domains = _dropmail_cached_domains()
    if cached_domains:
        return cached_domains
    token = str(api_token or "").strip() or _dropmail_acquire_api_token(proxies)
    data = _dropmail_graphql(
        token,
        "query {domains {id name introducedAt expiresAt availableVia}}",
        proxies=proxies,
    )
    allowed = {item.lower() for item in _dropmail_allowed_domains()}
    items = data.get("domains") or []
    domains: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip().lower()
        available_via = item.get("availableVia") or []
        if name not in allowed:
            continue
        if isinstance(available_via, list) and "API" not in available_via:
            continue
        domains.append(item)
    if domains:
        _dropmail_store_domains(domains)
    return domains


def _dropmail_parse_token(token: str) -> Tuple[str, str]:
    parts = str(token or "").split(":", 2)
    if len(parts) != 3 or parts[0] != "dropmail":
        return "", ""
    return str(parts[1] or "").strip(), str(parts[2] or "").strip()


def _dropmail_list_messages(api_token: str, session_id: str, proxies: Any = None) -> List[Dict[str, Any]]:
    if not api_token or not session_id:
        return []
    data = _dropmail_graphql(
        api_token,
        "query ($id: ID!) {session(id:$id) { mails {rawSize fromAddr toAddr downloadUrl text html headerSubject}}}",
        variables={"id": session_id},
        proxies=proxies,
    )
    session = data.get("session") or {}
    mails = session.get("mails") or []
    return mails if isinstance(mails, list) else []


def _dropmail_message_content(message: Dict[str, Any]) -> str:
    if not isinstance(message, dict):
        return ""
    return "\n".join(
        [
            str(message.get("fromAddr") or ""),
            str(message.get("headerSubject") or ""),
            str(message.get("text") or ""),
            str(message.get("html") or ""),
        ]
    )


def _dropmail_create_mailbox(token: str, proxies: Any = None) -> tuple:
    with _dropmail_mailbox_slots:
        token = str(token or "").strip()
        if not token:
            raise RuntimeError("DropMail token missing")
        domains = _dropmail_list_domains(proxies, api_token=token)
        if not domains:
            raise RuntimeError("DropMail 没有可用白名单域名")
        domain_entry = random.choice(domains)
        session_data = _dropmail_graphql(
            token,
            "mutation {introduceSession {id expiresAt addresses {address}}}",
            proxies=proxies,
        )
        intro = session_data.get("introduceSession") or {}
        session_id = str(intro.get("id") or "").strip()
        if not session_id:
            raise RuntimeError("DropMail session id missing")
        address_data = _dropmail_graphql(
            token,
            "mutation ($input: IntroduceAddressInput!) {introduceAddress(input: $input) {address restoreKey}}",
            variables={
                "input": {
                    "sessionId": session_id,
                    "domainId": domain_entry.get("id"),
                }
            },
            proxies=proxies,
        )
        intro_addr = address_data.get("introduceAddress") or {}
        email = str(intro_addr.get("address") or "").strip()
        if not email:
            raise RuntimeError("DropMail address missing")
        domain = _extract_email_domain(email)
        if domain not in _dropmail_allowed_domains():
            raise RuntimeError(f"DropMail domain not allowed: {domain}")
        return email, f"dropmail:{token}:{session_id}"


def _mailtm_headers(*, token: str = "", use_json: bool = False) -> Dict[str, Any]:
    headers = {"Accept": "application/json"}
    if use_json:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _try_dropmail(proxies: Any) -> tuple:
    try:
        dropmail_ready, cooldown_left, cooldown_reason = _dropmail_service_status()
        if not dropmail_ready:
            wait_time = min(12.0, max(1.0, cooldown_left)) + random.uniform(0.2, 0.9)
            print(
                f"[*] DropMail 冷却中，等待 {wait_time:.1f}s"
                f" reason={cooldown_reason or 'service_unavailable'}"
            )
            time.sleep(wait_time)
        cached_token = _dropmail_valid_cached_token()
        token_attempts = [cached_token] if cached_token else [""]
        auth_refresh_used = False
        attempt_index = 0
        while attempt_index < len(token_attempts):
            existing = token_attempts[attempt_index]
            attempt_index += 1
            try:
                token = _dropmail_acquire_api_token(proxies, force_refresh=not bool(existing))
            except Exception as e:
                print(f"[*] DropMail token 不可用: {e}")
                continue
            try:
                email, mailbox_token = _dropmail_create_mailbox(token, proxies)
                _dropmail_clear_transient_outage()
                print(f"[*] DropMail 邮箱: {email}")
                return email, mailbox_token
            except DropMailAuthError as e:
                print(f"[*] DropMail 创建邮箱失败: {e}")
                _dropmail_clear_api_token()
                if existing and not auth_refresh_used:
                    auth_refresh_used = True
                    token_attempts.append("")
                continue
            except DropMailHTTPError as e:
                print(f"[*] DropMail 创建邮箱失败: {e}")
                if e.status_code in {429, 500, 502, 503, 504}:
                    cooldown = _dropmail_mark_transient_outage(e.status_code, "mailbox")
                    wait_time = min(8.0, max(1.0, cooldown)) + random.uniform(0.2, 0.8)
                    print(f"[*] DropMail 服务抖动，等待 {wait_time:.1f}s 后重试")
                    time.sleep(wait_time)
                    continue
                if e.status_code == 402 and existing:
                    continue
                raise
            except Exception as e:
                print(f"[*] DropMail 创建邮箱失败: {e}")
                continue
    except Exception as e:
        print(f"[*] DropMail 不可用: {e}")
    return "", ""


def _mailtm_domains(proxies: Any = None) -> List[str]:
    resp = requests.get(
        f"{MAILTM_BASE}/domains",
        headers=_mailtm_headers(),
        proxies=proxies,
        impersonate="chrome",
        timeout=15,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"获取 Mail.tm 域名失败，状态码: {resp.status_code}")

    body_text = resp.text or ""
    content_type = str(resp.headers.get("Content-Type") or "").lower()
    domains: List[str] = []
    parsed = False

    if body_text.strip() and (body_text.lstrip().startswith("<") or "xml" in content_type):
        try:
            root = ET.fromstring(body_text)
            for item in root.findall(".//item"):
                values = {child.attrib.get("key") or child.tag: (child.text or "") for child in list(item)}
                domain = str(values.get("domain") or "").strip()
                is_active = str(values.get("isActive") or "1").strip() not in {"0", "false", "False"}
                is_private = str(values.get("isPrivate") or "0").strip() in {"1", "true", "True"}
                if domain and is_active and not is_private:
                    domains.append(domain)
            parsed = True
        except Exception:
            parsed = False

    if not parsed:
        try:
            data = resp.json()
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict):
                items = data.get("hydra:member") or data.get("items") or []
            else:
                items = []

            for item in items:
                if not isinstance(item, dict):
                    continue
                domain = str(item.get("domain") or "").strip()
                is_active = item.get("isActive", True)
                is_private = item.get("isPrivate", False)
                if domain and is_active and not is_private:
                    domains.append(domain)
            parsed = True
        except Exception:
            parsed = False

    if not parsed:
        raise RuntimeError(f"Mail.tm domains 解析失败: {content_type or 'unknown'}")

    return _filter_blacklisted_domains(domains)


def _normalize_skymail_domains(raw: Any) -> List[str]:
    if isinstance(raw, str):
        items = [part.strip() for part in raw.split(",")]
    elif isinstance(raw, list):
        items = [str(part or "").strip() for part in raw]
    else:
        items = []
    cleaned = [item for item in items if item]
    return _dedupe_keep_order(cleaned)


def _load_skymail_config() -> Dict[str, Any]:
    global _skymail_config_cache
    with _skymail_config_lock:
        if isinstance(_skymail_config_cache, dict):
            return dict(_skymail_config_cache)

        data: Dict[str, Any] = {}
        for path in (SKYMAIL_CONFIG_FILE, SKYMAIL_FALLBACK_CONFIG_FILE):
            try:
                if not os.path.exists(path):
                    continue
                with open(path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict) and (
                    loaded.get("skymail_admin_email")
                    or loaded.get("skymail_admin_password")
                    or loaded.get("skymail_domains")
                    or loaded.get("skymail_api_base")
                ):
                    data.update(loaded)
                    break
            except Exception:
                continue

        env_email = str(os.environ.get("SKYMAIL_ADMIN_EMAIL") or "").strip()
        env_password = str(os.environ.get("SKYMAIL_ADMIN_PASSWORD") or "").strip()
        env_domains = str(os.environ.get("SKYMAIL_DOMAINS") or "").strip()
        env_api_base = str(os.environ.get("SKYMAIL_API_BASE") or "").strip()
        env_proxy = str(os.environ.get("SKYMAIL_PROXY") or "").strip()
        env_verify_ssl = str(os.environ.get("SKYMAIL_VERIFY_SSL") or "").strip().lower()

        if env_email:
            data["skymail_admin_email"] = env_email
        if env_password:
            data["skymail_admin_password"] = env_password
        if env_domains:
            data["skymail_domains"] = _normalize_skymail_domains(env_domains)
        if env_api_base:
            data["skymail_api_base"] = env_api_base
        if env_proxy:
            data["skymail_proxy"] = env_proxy
        if env_verify_ssl in {"1", "true", "yes", "on"}:
            data["skymail_verify_ssl"] = True
        elif env_verify_ssl in {"0", "false", "no", "off"}:
            data["skymail_verify_ssl"] = False

        admin_email = str(data.get("skymail_admin_email") or "").strip()
        admin_password = str(data.get("skymail_admin_password") or "").strip()
        domains = _normalize_skymail_domains(data.get("skymail_domains"))
        api_base = str(data.get("skymail_api_base") or "").strip()
        if not api_base and admin_email and "@" in admin_email:
            api_base = f"https://{admin_email.split('@', 1)[1]}"
        verify_ssl = bool(data.get("skymail_verify_ssl", False))
        proxy = str(data.get("skymail_proxy") or data.get("proxy") or "").strip()

        normalized = {
            "admin_email": admin_email,
            "admin_password": admin_password,
            "domains": domains,
            "api_base": api_base.rstrip("/"),
            "proxy": proxy,
            "verify_ssl": verify_ssl,
            "enabled": bool(admin_email and admin_password and domains and api_base),
        }
        _skymail_config_cache = normalized
        return dict(normalized)


def _skymail_is_configured() -> bool:
    return bool(_load_skymail_config().get("enabled"))


def _skymail_request_proxies(proxies: Any = None) -> Any:
    cfg = _load_skymail_config()
    custom_proxy = str(cfg.get("proxy") or "").strip()
    if custom_proxy:
        return _build_proxies(custom_proxy)
    return proxies


def _skymail_cached_api_token() -> str:
    now = time.time()
    with _skymail_token_lock:
        token = str(_skymail_token_cache.get("token") or "").strip()
        expires_at = float(_skymail_token_cache.get("expires_at_ts") or 0.0)
        if token and expires_at > now + 15:
            return token
    return ""


def _skymail_store_api_token(token: str, ttl_seconds: int = SKYMAIL_TOKEN_TTL_SECONDS) -> None:
    token = str(token or "").strip()
    if not token:
        return
    with _skymail_token_lock:
        _skymail_token_cache["token"] = token
        _skymail_token_cache["expires_at_ts"] = time.time() + max(60, int(ttl_seconds or SKYMAIL_TOKEN_TTL_SECONDS))


def _skymail_clear_api_token() -> None:
    with _skymail_token_lock:
        _skymail_token_cache["token"] = ""
        _skymail_token_cache["expires_at_ts"] = 0.0


def _skymail_acquire_api_token(proxies: Any = None) -> str:
    cached = _skymail_cached_api_token()
    if cached:
        return cached

    cfg = _load_skymail_config()
    if not cfg.get("enabled"):
        raise RuntimeError("Skymail is not configured")

    effective_proxies = _skymail_request_proxies(proxies)
    resp = requests.post(
        f"{cfg['api_base']}/api/public/genToken",
        json={
            "email": cfg["admin_email"],
            "password": cfg["admin_password"],
        },
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        proxies=effective_proxies,
        impersonate="chrome",
        timeout=20,
        verify=bool(cfg.get("verify_ssl", False)),
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Skymail genToken http {resp.status_code}: {(resp.text or '')[:160]}")

    data = resp.json() if resp.text.strip() else {}
    if not isinstance(data, dict) or int(data.get("code") or 0) != 200:
        raise RuntimeError(f"Skymail genToken rejected: {(resp.text or '')[:160]}")

    token = str(((data.get("data") or {}).get("token") or "")).strip()
    if not token:
        raise RuntimeError("Skymail token missing")
    _skymail_store_api_token(token)
    return token


def _skymail_fetch_emails(email: str, proxies: Any = None) -> List[Dict[str, Any]]:
    cfg = _load_skymail_config()
    if not cfg.get("enabled"):
        return []

    effective_proxies = _skymail_request_proxies(proxies)
    token = _skymail_acquire_api_token(proxies)
    for attempt in range(2):
        try:
            resp = requests.post(
                f"{cfg['api_base']}/api/public/emailList",
                json={
                    "toEmail": email,
                    "timeSort": "desc",
                    "num": 1,
                    "size": 50,
                },
                headers={
                    "Authorization": token,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                proxies=effective_proxies,
                impersonate="chrome",
                timeout=20,
                verify=bool(cfg.get("verify_ssl", False)),
            )
            if resp.status_code == 200:
                data = resp.json() if resp.text.strip() else {}
                if isinstance(data, dict) and int(data.get("code") or 0) == 200:
                    items = data.get("data") or []
                    if isinstance(items, list):
                        return [item for item in items if isinstance(item, dict)]
                return []
            if resp.status_code in {401, 403} and attempt == 0:
                _skymail_clear_api_token()
                token = _skymail_acquire_api_token(proxies)
                continue
            return []
        except Exception:
            if attempt == 0:
                _skymail_clear_api_token()
                token = _skymail_acquire_api_token(proxies)
                continue
            return []
    return []


def _skymail_message_sort_key(message: Dict[str, Any]) -> tuple:
    if not isinstance(message, dict):
        return (0.0, "")
    raw_time = str(
        message.get("createTime")
        or message.get("createdAt")
        or message.get("created_at")
        or ""
    ).strip()
    ts = 0.0
    if raw_time:
        normalized = raw_time.replace("Z", "+00:00").replace("T", " ")
        try:
            parsed = datetime.fromisoformat(normalized)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            ts = parsed.timestamp()
        except Exception:
            pass
    email_id = str(message.get("emailId") or "").strip()
    return (ts, email_id)


def _skymail_seen_key(message: Dict[str, Any]) -> str:
    if not isinstance(message, dict):
        return ""
    email_id = str(message.get("emailId") or "").strip()
    if email_id:
        return f"skymail:{email_id}"
    return _mail_message_seen_key(message)


def _skymail_message_content(message: Dict[str, Any]) -> str:
    if not isinstance(message, dict):
        return ""
    return "\n".join(
        [
            str(message.get("subject") or ""),
            str(message.get("text") or ""),
            str(message.get("content") or ""),
        ]
    )


def _skymail_code_key(email: str, code: str) -> str:
    return f"{str(email or '').strip().lower()}::{str(code or '').strip()}"


def _skymail_code_used(email: str, code: str) -> bool:
    key = _skymail_code_key(email, code)
    if not key or key.endswith("::"):
        return False
    with _skymail_used_codes_lock:
        return key in _skymail_used_codes


def _skymail_remember_code(email: str, code: str) -> None:
    key = _skymail_code_key(email, code)
    if not key or key.endswith("::"):
        return
    with _skymail_used_codes_lock:
        _skymail_used_codes.add(key)


def _try_skymail(proxies: Any) -> tuple:
    try:
        cfg = _load_skymail_config()
        if not cfg.get("enabled"):
            return "", ""
        _skymail_acquire_api_token(proxies)
        domain = random.choice(cfg.get("domains") or [])
        prefix_length = random.randint(6, 10)
        prefix = "".join(random.choices(string.ascii_lowercase + string.digits, k=prefix_length))
        email = f"{prefix}@{domain}"
        print(f"[*] Skymail 邮箱: {email}")
        return email, f"skymail:{email}"
    except Exception as e:
        print(f"[*] Skymail 创建邮箱失败: {e}")
        return "", ""


def _try_duckmail(proxies: Any, duckmail_key: str) -> tuple:
    """尝试用 DuckMail 创建邮箱。有 key 用认证模式，无 key 用公共模式。"""
    try:
        if duckmail_key:
            auth_headers = {"Authorization": f"Bearer {duckmail_key}", "Accept": "application/json"}
            dom_resp = requests.get(
                f"{DUCKMAIL_BASE}/domains",
                headers=auth_headers,
                proxies=proxies, impersonate="chrome", timeout=15,
            )
            domains = []
            if dom_resp.status_code == 200:
                for d in (dom_resp.json().get("hydra:member") or []):
                    if d.get("isVerified", False):
                        domains.append(d["domain"])
            domains = _filter_blacklisted_domains(domains)
            if not domains:
                print("[*] DuckMail(key) 无已验证域名")
                return "", ""
            domain = _pick_domain(domains)
            local = f"u{secrets.token_hex(4)}"
            email = f"{local}@{domain}"
            mail_pwd = secrets.token_urlsafe(12)
            create_resp = requests.post(
                f"{DUCKMAIL_BASE}/accounts",
                headers={**auth_headers, "Content-Type": "application/json"},
                json={"address": email, "password": mail_pwd, "expiresIn": 86400},
                proxies=proxies, impersonate="chrome", timeout=15,
            )
            if create_resp.status_code not in (200, 201):
                print(f"[*] DuckMail(key) 创建失败: {create_resp.status_code}")
                return "", ""
            token_resp = requests.post(
                f"{DUCKMAIL_BASE}/token",
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                json={"address": email, "password": mail_pwd},
                proxies=proxies, impersonate="chrome", timeout=15,
            )
            if token_resp.status_code == 200:
                token = token_resp.json().get("token", "")
                if token:
                    print(f"[*] DuckMail(key) 邮箱: {email}")
                    return email, f"duckmail:{token}"
            print(f"[*] DuckMail(key) 获取 token 失败")
            return "", ""
        else:
            # 公共模式：无 key，使用公开端点
            dom_resp = requests.get(
                f"{DUCKMAIL_BASE}/domains",
                headers={"Accept": "application/json"},
                proxies=proxies, impersonate="chrome", timeout=15,
            )
            domains = []
            if dom_resp.status_code == 200:
                data = dom_resp.json()
                if isinstance(data, list):
                    items = data
                elif isinstance(data, dict):
                    items = data.get("hydra:member") or []
                else:
                    items = []
                for d in items:
                    if isinstance(d, dict):
                        dom = str(d.get("domain") or "").strip()
                        if dom and d.get("isActive", True) and not d.get("isPrivate", False):
                            domains.append(dom)
            domains = _filter_blacklisted_domains(domains)
            if not domains:
                print("[*] DuckMail(公共) 无可用域名")
                return "", ""
            domain = _pick_domain(domains)
            local = f"u{secrets.token_hex(4)}"
            email = f"{local}@{domain}"
            mail_pwd = secrets.token_urlsafe(12)
            create_resp = requests.post(
                f"{DUCKMAIL_BASE}/accounts",
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                json={"address": email, "password": mail_pwd},
                proxies=proxies, impersonate="chrome", timeout=15,
            )
            if create_resp.status_code not in (200, 201):
                print(f"[*] DuckMail(公共) 创建失败: {create_resp.status_code}")
                return "", ""
            token_resp = requests.post(
                f"{DUCKMAIL_BASE}/token",
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                json={"address": email, "password": mail_pwd},
                proxies=proxies, impersonate="chrome", timeout=15,
            )
            if token_resp.status_code == 200:
                token = token_resp.json().get("token", "")
                if token:
                    print(f"[*] DuckMail(公共) 邮箱: {email}")
                    return email, f"duckmail:{token}"
            print("[*] DuckMail(公共) 获取 token 失败")
            return "", ""
    except Exception as e:
        print(f"[*] DuckMail 不可用: {e}")
        return "", ""


def _try_tempmail_lol(proxies: Any) -> tuple:
    """尝试用 tempmail.lol 创建邮箱"""
    try:
        managed_family = _managed_target_family()
        if managed_family:
            primary_families = [managed_family]
            preferred_families = [managed_family]
        else:
            primary_families = _fallback_login_families(limit=2)
            preferred_families = _preferred_domain_families(limit=4, score_window=80)
        for attempt in range(1, TEMPMAIL_LOL_MAX_CREATE_ATTEMPTS + 1):
            request_payload: Dict[str, Any] = {}
            domains = _managed_target_domains()
            if domains:
                request_payload["domain"] = _pick_experiment2_domain(domains)
            resp = requests.post(
                f"{TEMPMAIL_LOL_BASE}/inbox/create",
                headers={"Content-Type": "application/json"},
                data=json.dumps(request_payload),
                proxies=proxies, impersonate="chrome", timeout=15,
            )
            if resp.status_code in (200, 201):
                data = resp.json()
                email = data.get("address", "")
                token = data.get("token", "")
                if email and token:
                    family = _domain_family(email)
                    unavailable_reason = _domain_unavailable_reason(email)
                    if unavailable_reason and not (
                        managed_family and family == managed_family
                    ):
                        print(
                            f"[*] tempmail.lol 跳过不可用域名: "
                            f"{_extract_email_domain(email)} reason={unavailable_reason}"
                        )
                        continue
                    active_family_window = []
                    if attempt <= 12 and primary_families:
                        active_family_window = primary_families
                    elif attempt <= max(20, TEMPMAIL_LOL_MAX_CREATE_ATTEMPTS // 2) and preferred_families:
                        active_family_window = preferred_families
                    if (
                        active_family_window
                        and family not in active_family_window
                    ):
                        print(
                            f"[*] tempmail.lol 优先域名窗口跳过: "
                            f"{_extract_email_domain(email)} preferred={','.join(active_family_window)}"
                        )
                        continue
                    if _should_skip_low_score_domain(email) and not (
                        managed_family and family == managed_family
                    ):
                        print(
                            f"[*] tempmail.lol 跳过低分域名: "
                            f"{_extract_email_domain(email)} score={_domain_score(email)}"
                        )
                        continue
                    print(f"[*] tempmail.lol 邮箱: {email}")
                    if _should_temporarily_avoid_domain(email):
                        print(
                            f"[*] tempmail.lol 暂避高压域名: "
                            f"{_extract_email_domain(email)} score={_domain_score(email)}"
                        )
                        continue
                    return email, f"tempmail_lol:{token}"
            print(f"[*] tempmail.lol 返回 {resp.status_code} (attempt {attempt}/{TEMPMAIL_LOL_MAX_CREATE_ATTEMPTS})")
            if resp.status_code == 429:
                time.sleep(random.uniform(0.8, 2.2))
    except Exception as e:
        print(f"[*] tempmail.lol 不可用: {e}")
    return "", ""


def _should_prefer_direct_success(email_or_domain: str) -> bool:
    family = _domain_family(email_or_domain)
    if not family:
        return False
    return family in set(_fallback_login_families(limit=2))


def _try_onesecmail(proxies: Any) -> tuple:
    """尝试用 1secmail 创建邮箱（免费无认证）"""
    try:
        # 获取可用域名
        dom_resp = requests.get(
            f"{ONESECMAIL_BASE}?action=getDomainList",
            proxies=proxies, impersonate="chrome", timeout=15,
        )
        if dom_resp.status_code != 200:
            print(f"[*] 1secmail 获取域名失败: {dom_resp.status_code}")
            return "", ""
        domains = dom_resp.json()
        domains = _filter_blacklisted_domains(domains)
        if not domains:
            print("[*] 1secmail 无可用域名")
            return "", ""
        domain = _pick_domain(domains)
        login = f"u{secrets.token_hex(5)}"
        email = f"{login}@{domain}"
        # 1secmail 不需要创建，直接用
        print(f"[*] 1secmail 邮箱: {email}")
        return email, f"onesecmail:{login}:{domain}"
    except Exception as e:
        print(f"[*] 1secmail 不可用: {e}")
        return "", ""


def _try_mailtm(proxies: Any) -> tuple:
    """回退：mail.gw"""
    try:
        domains = _mailtm_domains(proxies)
        if not domains:
            print("[Error] Mail.tm 没有可用域名")
            return "", ""
        domain = _pick_domain(domains)
        for _ in range(5):
            local = f"oc{secrets.token_hex(5)}"
            email = f"{local}@{domain}"
            password = secrets.token_urlsafe(18)
            create_resp = requests.post(
                f"{MAILTM_BASE}/accounts",
                headers=_mailtm_headers(use_json=True),
                json={"address": email, "password": password},
                proxies=proxies, impersonate="chrome", timeout=15,
            )
            if create_resp.status_code not in (200, 201):
                continue
            token_resp = requests.post(
                f"{MAILTM_BASE}/token",
                headers=_mailtm_headers(use_json=True),
                json={"address": email, "password": password},
                proxies=proxies, impersonate="chrome", timeout=15,
            )
            if token_resp.status_code == 200:
                token = str(token_resp.json().get("token") or "").strip()
                if token:
                    return email, token
        print("[Error] Mail.tm 邮箱创建失败")
        return "", ""
    except Exception as e:
        print(f"[Error] 请求 Mail.tm API 出错: {e}")
        return "", ""


def _try_alpha_infini(proxies: Any) -> tuple:
    local = "oc" + "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(10))
    domain = random.choice(_alpha_infini_domain_pool)
    email = f"{local}@{domain}"
    token = json.dumps(
        {
            "provider": AERO_ALPHA_PROVIDER,
            "email": email,
            "api_base": "https://mail.infini-ai.eu.cc",
            "domain": "infini-ai.eu.cc",
            "subdomain": domain,
            "password": secrets.token_urlsafe(18),
            "created_at": time.time(),
        },
        ensure_ascii=False,
    )
    print(f"[*] alpha infini 邮箱: {email}")
    return email, f"alpha_infini:{token}"


def _self_hosted_messages_domains() -> List[str]:
    domains = [
        _extract_email_domain(domain)
        for domain in SELF_HOSTED_MESSAGES_DOMAINS
        if _extract_email_domain(domain)
    ]
    filtered = _filter_blacklisted_domains(domains)
    return filtered or domains


def _try_self_hosted_messages_api(proxies: Any = None) -> tuple:
    del proxies
    try:
        domains = _self_hosted_messages_domains()
        if not domains:
            raise RuntimeError("SELF_HOSTED_MESSAGES_DOMAINS 为空")
        selected_domain = _pick_domain(domains) or random.choice(domains)
        local = "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
        local_ = "".join(random.choices(string.ascii_lowercase + string.digits, k=5))
        email = f"{local}@{local_}.{selected_domain}"
        print(f"[*] messages-api 邮箱: {email}")
        return email, f"self_hosted_messages_api:{email}"
    except Exception as e:
        print(f"[*] messages-api 不可用: {e}")
        return "", ""


def _get_email_and_token_impl(proxies: Any = None) -> tuple:
    """从已启用的邮箱源中随机选一个，失败后依次尝试其余，最后兜底 mail.gw"""
    if MAIL_PROVIDER_MODE == "self_hosted_messages_api":
        for round_idx in range(1, DEFAULT_EMAIL_SOURCE_ROUNDS + 1):
            print(
                f"[*] 邮箱源轮次 {round_idx}/{DEFAULT_EMAIL_SOURCE_ROUNDS}: "
                "self_hosted_messages_api"
            )
            email, token = _try_self_hosted_messages_api(proxies)
            if email and token:
                return email, token
        return "", ""

    if _alpha_enabled:
        return _try_alpha_infini(proxies)

    enabled = []
    if MAIL_SOURCES.get("dropmail") and not _legacy_mail_mode:
        enabled.append("dropmail")
    if MAIL_SOURCES.get("skymail") and not _legacy_mail_mode:
        enabled.append("skymail")
    if MAIL_SOURCES.get("tempmail_lol"):
        enabled.append("tempmail_lol")
    if MAIL_SOURCES.get("onesecmail"):
        enabled.append("onesecmail")
    if MAIL_SOURCES.get("duckmail"):
        enabled.append("duckmail")
    if MAIL_SOURCES.get("mailtm"):
        enabled.append("mailtm")

    if not enabled:
        enabled = ["tempmail_lol"] if _legacy_mail_mode else ["dropmail"]  # 至少保留一个

    for round_idx in range(1, DEFAULT_EMAIL_SOURCE_ROUNDS + 1):
        round_sources = enabled[:]
        if _legacy_mail_mode:
            preferred_order = ["tempmail_lol", "onesecmail", "duckmail", "mailtm"]
            round_sources = [item for item in preferred_order if item in round_sources]
        elif not _legacy_mail_mode and (_skymail_preferred or "dropmail" in round_sources):
            priority: List[str] = []
            if _skymail_preferred and "skymail" in round_sources:
                round_sources.remove("skymail")
                priority.append("skymail")
            if "dropmail" in round_sources:
                round_sources.remove("dropmail")
                priority.append("dropmail")
            random.shuffle(round_sources)
            if "skymail" in round_sources and "skymail" not in priority:
                round_sources.remove("skymail")
                priority.append("skymail")
            round_sources = priority + round_sources
        else:
            random.shuffle(round_sources)
        print(
            f"[*] 邮箱源轮次 {round_idx}/{DEFAULT_EMAIL_SOURCE_ROUNDS}: "
            f"{' -> '.join(round_sources)}"
        )

        for source in round_sources:
            if source == "dropmail":
                email, token = _try_dropmail(proxies)
            elif source == "skymail":
                email, token = _try_skymail(proxies)
            elif source == "duckmail":
                email, token = _try_duckmail(proxies, DUCKMAIL_KEY)
            elif source == "tempmail_lol":
                email, token = _try_tempmail_lol(proxies)
            elif source == "onesecmail":
                email, token = _try_onesecmail(proxies)
            elif source == "mailtm":
                email, token = _try_mailtm(proxies)
            else:
                continue
            if email and token:
                family = _domain_family(email)
                unavailable_reason = _domain_unavailable_reason(email)
                if unavailable_reason and not (
                    _experiment2_enabled and family == _experiment2_force_family
                ):
                    print(
                        f"[*] 跳过不可用邮箱域名: "
                        f"{_extract_email_domain(email)} reason={unavailable_reason}"
                    )
                    continue
                if _should_skip_low_score_domain(email) and not (
                    _experiment2_enabled and family == _experiment2_force_family
                ):
                    print(
                        f"[*] 跳过低分邮箱域名: "
                        f"{_extract_email_domain(email)} score={_domain_score(email)}"
                    )
                    continue
                return email, token

    # 所有启用源都失败，且 mailtm 未启用时兜底
    if not MAIL_SOURCES.get("mailtm"):
        print("[*] 启用源均失败，兜底 mail.gw")
        return _try_mailtm(proxies)

    return "", ""


def get_email_and_token(proxies: Any = None) -> tuple:
    with _stage_slot("mailbox"):
        return _get_email_and_token_impl(proxies)


def _mail_message_seen_key(message: Any) -> str:
    if not isinstance(message, dict):
        return ""

    for key in ("id", "messageId", "@id"):
        value = str(message.get(key) or "").strip()
        if value:
            return f"id:{value}"

    fallback_parts = []
    for key in (
        "createdAt",
        "created_at",
        "receivedAt",
        "received_at",
        "date",
        "timestamp",
        "from",
        "subject",
        "intro",
        "text",
        "body",
        "html",
    ):
        value = message.get(key)
        if isinstance(value, list):
            value = "\n".join(str(item) for item in value if item is not None)
        elif isinstance(value, dict):
            value = json.dumps(value, ensure_ascii=False, sort_keys=True)
        else:
            value = str(value or "")
        value = value.strip()
        if value:
            fallback_parts.append(value)

    if not fallback_parts:
        return ""

    raw = "\n".join(fallback_parts)
    digest = hashlib.sha1(raw.encode("utf-8", "ignore")).hexdigest()
    return f"fp:{digest}"


def _parse_mail_timestamp(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if number > 10_000_000_000:
            return number / 1000.0
        return number if number > 0 else None

    text = str(value).strip()
    if not text:
        return None

    try:
        numeric = float(text)
        if numeric > 10_000_000_000:
            return numeric / 1000.0
        if numeric > 0:
            return numeric
    except ValueError:
        pass

    candidates = [text]
    if text.endswith("Z"):
        candidates.append(text[:-1] + "+00:00")
    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.timestamp()
        except ValueError:
            continue

    try:
        return parsedate_to_datetime(text).timestamp()
    except Exception:
        return None


def _self_hosted_messages_sort_key(message: Dict[str, Any]) -> Tuple[float, int]:
    received_ts = (
        _parse_mail_timestamp(message.get("received_at"))
        or _parse_mail_timestamp(message.get("receivedAt"))
        or _parse_mail_timestamp(message.get("created_at"))
        or _parse_mail_timestamp(message.get("createdAt"))
        or _parse_mail_timestamp(message.get("date"))
        or _parse_mail_timestamp(message.get("timestamp"))
        or 0.0
    )
    try:
        message_id = int(str(message.get("id") or "0").strip() or "0")
    except Exception:
        message_id = 0
    return received_ts, message_id


def _flatten_mail_content(mail_obj: Dict[str, Any]) -> str:
    parts: List[str] = []
    for key in ("subject", "body", "text", "html", "intro"):
        value = mail_obj.get(key)
        if isinstance(value, list):
            parts.extend(str(item or "") for item in value)
        elif isinstance(value, dict):
            parts.append(json.dumps(value, ensure_ascii=False))
        elif value:
            parts.append(str(value))

    sender = mail_obj.get("from")
    if isinstance(sender, dict):
        parts.append(str(sender.get("name") or ""))
        parts.append(str(sender.get("address") or ""))
    elif isinstance(sender, list):
        parts.extend(str(item or "") for item in sender)
    elif sender:
        parts.append(str(sender))

    recipients = mail_obj.get("to")
    if isinstance(recipients, list):
        for item in recipients:
            if isinstance(item, dict):
                parts.append(str(item.get("name") or ""))
                parts.append(str(item.get("address") or ""))
            elif item:
                parts.append(str(item))
    elif recipients:
        parts.append(str(recipients))

    return " ".join(part for part in parts if part).strip()


def _extract_mail_verification_code(content: str) -> str:
    if not content:
        return ""
    matched = re.search(
        r"background-color:\s*#F3F3F3[^>]*>[\s\S]*?(\d{6})[\s\S]*?</p>",
        content,
        re.I,
    )
    if matched:
        return str(matched.group(1) or "").strip()
    matched = re.search(r"Subject:.*?(\d{6})", content, re.I | re.S)
    if matched and matched.group(1) != "177010":
        return str(matched.group(1) or "").strip()
    for pattern in (r">\s*(\d{6})\s*<", r"(?<![#&])\b(\d{6})\b"):
        for code in re.findall(pattern, content, re.I | re.S):
            code = str(code or "").strip()
            if code and code != "177010":
                return code
    return ""


def _self_hosted_messages_fetch_messages(email: str, proxies: Any = None) -> List[Dict[str, Any]]:
    if not email:
        return []
    try:
        resp = requests.get(
            SELF_HOSTED_MESSAGES_API_URL,
            params={"recipient": email},
            impersonate="chrome",
            timeout=15,
        )
        if resp.status_code != 200:
            return []
        payload = resp.json()
        messages = payload.get("messages") if isinstance(payload, dict) else []
        if not isinstance(messages, list):
            return []
        cleaned = [item for item in messages if isinstance(item, dict)]
        return sorted(cleaned, key=_self_hosted_messages_sort_key, reverse=True)
    except Exception:
        return []


def _poll_hydra_otp(base_url: str, token: str, regex: str, proxies: Any = None, seen_msg_ids: set = None) -> str:
    """通用 hydra 格式邮箱轮询 OTP（适用于 mail.gw / DuckMail）"""
    if seen_msg_ids is None:
        seen_msg_ids = set()
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    for _ in range(40):
        print(".", end="", flush=True)
        try:
            resp = requests.get(
                f"{base_url}/messages",
                headers=headers,
                proxies=proxies,
                impersonate="chrome",
                timeout=15,
            )
            if resp.status_code != 200:
                _sleep_poll_delay()
                continue

            data = resp.json()
            messages = []
            if isinstance(data, list):
                messages = data
            elif isinstance(data, dict):
                messages = data.get("hydra:member") or data.get("messages") or []

            for msg in messages:
                if not isinstance(msg, dict):
                    continue
                msg_id = str(msg.get("id") or "").strip()
                if not msg_id or msg_id in seen_msg_ids:
                    continue
                seen_msg_ids.add(msg_id)

                read_resp = requests.get(
                    f"{base_url}/messages/{msg_id}",
                    headers=headers,
                    proxies=proxies,
                    impersonate="chrome",
                    timeout=15,
                )
                if read_resp.status_code != 200:
                    continue

                mail_data = read_resp.json()
                sender = str(
                    ((mail_data.get("from") or {}).get("address") or "")
                ).lower()
                subject = str(mail_data.get("subject") or "")
                intro = str(mail_data.get("intro") or "")
                text = str(mail_data.get("text") or "")
                html = mail_data.get("html") or ""
                if isinstance(html, list):
                    html = "\n".join(str(x) for x in html)
                content = "\n".join([subject, intro, text, str(html)])

                if "openai" not in sender and "openai" not in content.lower():
                    continue

                m = re.search(regex, content)
                if m:
                    print(" 抓到啦! 验证码:", m.group(1))
                    return m.group(1)
        except Exception:
            pass

        _sleep_poll_delay()

    print(" 超时，未收到验证码")
    return ""


def _dropmail_seen_key(message: Dict[str, Any]) -> str:
    if not isinstance(message, dict):
        return ""
    download_url = str(message.get("downloadUrl") or "").strip()
    if download_url:
        return f"dropmail:{download_url}"
    synthetic = {
        "from": message.get("fromAddr"),
        "subject": message.get("headerSubject"),
        "text": message.get("text"),
        "html": message.get("html"),
    }
    return _mail_message_seen_key(synthetic)


def _dropmail_extract_content(message: Dict[str, Any]) -> str:
    if not isinstance(message, dict):
        return ""
    return "\n".join(
        [
            str(message.get("fromAddr") or ""),
            str(message.get("headerSubject") or ""),
            str(message.get("text") or ""),
            str(message.get("html") or ""),
        ]
    )


def _get_oai_code_impl(token: str, email: str, proxies: Any = None, seen_msg_ids: set = None) -> str:
    """轮询获取 OpenAI 验证码（支持 onesecmail / duckmail / tempmail.lol / mail.gw）"""
    if seen_msg_ids is None:
        seen_msg_ids = set()
    regex = r"(?<!\d)(\d{6})(?!\d)"
    print(f"[*] 正在等待邮箱 {email} 的验证码...", end="", flush=True)

    if token.startswith("self_hosted_messages_api:"):
        mailbox_email = token[len("self_hosted_messages_api:"):].strip() or email
        for _ in range(40):
            print(".", end="", flush=True)
            try:
                messages = _self_hosted_messages_fetch_messages(mailbox_email, proxies)
                for msg in messages[:20]:
                    msg_key = _mail_message_seen_key(msg)
                    if msg_key and msg_key in seen_msg_ids:
                        continue
                    if msg_key:
                        seen_msg_ids.add(msg_key)
                    content = _flatten_mail_content(msg)
                    if "openai" not in content.lower() and "chatgpt" not in content.lower():
                        continue
                    code = _extract_mail_verification_code(content)
                    if code:
                        print(" 抓到啦! 验证码:", code)
                        return code
                    matched = re.search(regex, content)
                    if matched:
                        print(" 抓到啦! 验证码:", matched.group(1))
                        return matched.group(1)
            except Exception:
                pass
            _sleep_poll_delay()
        print(" 超时，未收到验证码")
        return ""

    if token.startswith("onesecmail:"):
        parts = token[len("onesecmail:"):].split(":", 1)
        login, domain = parts[0], parts[1]
        for _ in range(40):
            print(".", end="", flush=True)
            try:
                resp = requests.get(
                    f"{ONESECMAIL_BASE}?action=getMessages&login={login}&domain={domain}",
                    proxies=proxies, impersonate="chrome", timeout=15,
                )
                if resp.status_code != 200:
                    _sleep_poll_delay(); continue
                for msg in resp.json():
                    msg_id = str(msg.get("id", ""))
                    if msg_id in seen_msg_ids:
                        continue
                    seen_msg_ids.add(msg_id)
                    # 读取完整邮件
                    rd = requests.get(
                        f"{ONESECMAIL_BASE}?action=readMessage&login={login}&domain={domain}&id={msg_id}",
                        proxies=proxies, impersonate="chrome", timeout=15,
                    )
                    if rd.status_code != 200:
                        continue
                    md = rd.json()
                    sender = str(md.get("from", "")).lower()
                    subject = str(md.get("subject", ""))
                    body = str(md.get("textBody", ""))
                    html = str(md.get("htmlBody", ""))
                    content = "\n".join([sender, subject, body, html])
                    if "openai" not in content.lower():
                        continue
                    m = re.search(regex, content)
                    if m:
                        print(" 抓到啦! 验证码:", m.group(1))
                        return m.group(1)
            except Exception:
                pass
            _sleep_poll_delay()
        print(" 超时，未收到验证码")
        return ""

    if token.startswith("dropmail:"):
        api_token, session_id = _dropmail_parse_token(token)
        for _ in range(40):
            print(".", end="", flush=True)
            try:
                messages = _dropmail_list_messages(api_token, session_id, proxies)
                for msg in messages:
                    if not isinstance(msg, dict):
                        continue
                    msg_key = _dropmail_seen_key(msg)
                    if msg_key and msg_key in seen_msg_ids:
                        continue
                    if msg_key:
                        seen_msg_ids.add(msg_key)
                    content = _dropmail_extract_content(msg)
                    if "openai" not in content.lower():
                        continue
                    m = re.search(regex, content)
                    if m:
                        print(" 抓到啦! 验证码:", m.group(1))
                        return m.group(1)
            except Exception:
                pass
            _sleep_poll_delay()
        print(" 超时，未收到验证码")
        return ""

    if token.startswith("skymail:"):
        mailbox_email = token[len("skymail:"):].strip()
        for _ in range(40):
            print(".", end="", flush=True)
            try:
                messages = sorted(
                    _skymail_fetch_emails(mailbox_email, proxies),
                    key=_skymail_message_sort_key,
                    reverse=True,
                )
                for msg in messages:
                    if not isinstance(msg, dict):
                        continue
                    msg_key = _skymail_seen_key(msg)
                    if msg_key and msg_key in seen_msg_ids:
                        continue
                    if msg_key:
                        seen_msg_ids.add(msg_key)
                    content = _skymail_message_content(msg)
                    if "openai" not in content.lower():
                        continue
                    m = re.search(regex, content)
                    if m:
                        code = str(m.group(1) or "").strip()
                        if _skymail_code_used(mailbox_email, code):
                            continue
                        _skymail_remember_code(mailbox_email, code)
                        print(" 抓到啦! 验证码:", code)
                        return code
            except Exception:
                pass
            _sleep_poll_delay()
        print(" 超时，未收到验证码")
        return ""

    if token.startswith("alpha_infini:"):
        print(" alpha-infini 暂未实现验证码轮询")
        return ""

    if token.startswith("duckmail:"):
        return _poll_hydra_otp(DUCKMAIL_BASE, token[len("duckmail:"):], regex, proxies, seen_msg_ids)

    if token.startswith("tempmail_lol:"):
        # tempmail.lol 模式
        real_token = token[len("tempmail_lol:"):]
        for _ in range(40):
            print(".", end="", flush=True)
            try:
                resp = requests.get(
                    f"{TEMPMAIL_LOL_BASE}/inbox?token={real_token}",
                    proxies=proxies,
                    impersonate="chrome",
                    timeout=15,
                )
                if resp.status_code != 200:
                    _sleep_poll_delay()
                    continue
                data = resp.json()
                for msg in data.get("emails", []):
                    msg_key = _mail_message_seen_key(msg)
                    if msg_key and msg_key in seen_msg_ids:
                        continue
                    if msg_key:
                        seen_msg_ids.add(msg_key)
                    sender = str(msg.get("from") or "").lower()
                    subject = str(msg.get("subject") or "")
                    body = str(msg.get("body") or msg.get("text") or "")
                    html = str(msg.get("html") or "")
                    content = "\n".join([sender, subject, body, html])
                    if "openai" not in content.lower():
                        continue
                    m = re.search(regex, content)
                    if m:
                        print(" 抓到啦! 验证码:", m.group(1))
                        return m.group(1)
            except Exception:
                pass
            _sleep_poll_delay()
        print(" 超时，未收到验证码")
        return ""

    # mail.gw / mail.tm 模式（复用 hydra 轮询）
    return _poll_hydra_otp(MAILTM_BASE, token, regex, proxies, seen_msg_ids)


def get_oai_code(token: str, email: str, proxies: Any = None, seen_msg_ids: set = None) -> str:
    with _stage_slot("otp"):
        return _get_oai_code_impl(token, email, proxies, seen_msg_ids)


def _fetch_login_email_otp(
    *,
    session: Any,
    dev_token: str,
    email: str,
    proxies: Any,
    get_sentinel,
    build_headers,
    blocked_codes: Optional[set] = None,
) -> str:
    seen_msg_ids = set()
    ignored = {str(code).strip() for code in (blocked_codes or set()) if str(code).strip()}
    otp_code = get_oai_code(dev_token, email, proxies, seen_msg_ids=seen_msg_ids)
    if otp_code in ignored:
        print("[*] login email OTP ignored a blocked code from mailbox")
        otp_code = ""
    if otp_code:
        return otp_code
    try:
        _request_with_retries(
            lambda: session.post(
                "https://auth.openai.com/api/accounts/email-otp/resend",
                headers=build_headers(
                    "https://auth.openai.com/email-verification",
                    get_sentinel(SENTINEL_FLOW_EMAIL_OTP),
                ),
                data="{}",
                timeout=15,
            ),
            label="login-email-otp-resend-missing",
        )
    except Exception:
        pass
    time.sleep(random.uniform(4.0, 7.0))
    otp_code = get_oai_code(dev_token, email, proxies, seen_msg_ids=seen_msg_ids)
    if otp_code in ignored:
        print("[*] login email OTP ignored a blocked code after resend")
        return ""
    return otp_code


def _get_oai_verify_impl(token: str, email: str, proxies: Any = None) -> str:
    """轮询邮箱获取 OpenAI 验证邮件，返回验证链接或验证码（支持所有邮箱源）"""
    code_regex = r"(?<!\d)(\d{6})(?!\d)"
    link_regex = r'https?://[^\s"\'<>]+(?:verify|confirm|activation|email-verification)[^\s"\'<>]*'

    def _extract(content: str) -> str:
        link_match = re.search(link_regex, content)
        if link_match:
            print(f" 找到验证链接!")
            return link_match.group(0)
        code_match = re.search(code_regex, content)
        if code_match:
            print(f" 找到验证码: {code_match.group(1)}")
            return code_match.group(1)
        return ""

    print(f"[*] 正在等待邮箱 {email} 的验证邮件...", end="", flush=True)
    seen_ids: set[str] = set()

    if token.startswith("self_hosted_messages_api:"):
        mailbox_email = token[len("self_hosted_messages_api:"):].strip() or email
        for _ in range(40):
            print(".", end="", flush=True)
            try:
                messages = _self_hosted_messages_fetch_messages(mailbox_email, proxies)
                for msg in messages[:20]:
                    msg_key = _mail_message_seen_key(msg)
                    if msg_key and msg_key in seen_ids:
                        continue
                    if msg_key:
                        seen_ids.add(msg_key)
                    content = _flatten_mail_content(msg)
                    if "openai" not in content.lower() and "chatgpt" not in content.lower():
                        continue
                    result = _extract(content)
                    if result:
                        return result
                    print(" 收到 OpenAI 邮件但未提取到链接/验证码")
            except Exception:
                pass
            _sleep_poll_delay()
        print(" 超时")
        return ""

    if token.startswith("onesecmail:"):
        parts = token[len("onesecmail:"):].split(":", 1)
        login, domain = parts[0], parts[1]
        for _ in range(40):
            print(".", end="", flush=True)
            try:
                resp = requests.get(
                    f"{ONESECMAIL_BASE}?action=getMessages&login={login}&domain={domain}",
                    proxies=proxies, impersonate="chrome", timeout=15,
                )
                if resp.status_code != 200:
                    _sleep_poll_delay(); continue
                for msg in resp.json():
                    msg_id = str(msg.get("id", ""))
                    if msg_id in seen_ids: continue
                    seen_ids.add(msg_id)
                    rd = requests.get(
                        f"{ONESECMAIL_BASE}?action=readMessage&login={login}&domain={domain}&id={msg_id}",
                        proxies=proxies, impersonate="chrome", timeout=15,
                    )
                    if rd.status_code != 200: continue
                    md = rd.json()
                    sender = str(md.get("from", "")).lower()
                    subject = str(md.get("subject", ""))
                    body = str(md.get("textBody", ""))
                    html = str(md.get("htmlBody", ""))
                    content = "\n".join([sender, subject, body, html])
                    if "openai" not in content.lower(): continue
                    r = _extract(content)
                    if r: return r
                    print(f" 收到 OpenAI 邮件但未提取到链接/验证码")
            except Exception: pass
            _sleep_poll_delay()
        print(" 超时"); return ""

    if token.startswith("dropmail:"):
        api_token, session_id = _dropmail_parse_token(token)
        for _ in range(40):
            print(".", end="", flush=True)
            try:
                messages = _dropmail_list_messages(api_token, session_id, proxies)
                for msg in messages:
                    if not isinstance(msg, dict):
                        continue
                    msg_key = _dropmail_seen_key(msg)
                    if msg_key and msg_key in seen_ids:
                        continue
                    if msg_key:
                        seen_ids.add(msg_key)
                    content = _dropmail_extract_content(msg)
                    if "openai" not in content.lower():
                        continue
                    r = _extract(content)
                    if r:
                        return r
            except Exception:
                pass
            _sleep_poll_delay()
        print(" 超时"); return ""

    if token.startswith("alpha_infini:"):
        print(" 超时"); return ""

    if token.startswith("duckmail:"):
        real_token = token[len("duckmail:"):]
        base_url = DUCKMAIL_BASE
        headers = {"Authorization": f"Bearer {real_token}", "Accept": "application/json"}
        for _ in range(40):
            print(".", end="", flush=True)
            try:
                resp = requests.get(f"{base_url}/messages", headers=headers, proxies=proxies, impersonate="chrome", timeout=15)
                if resp.status_code != 200:
                    _sleep_poll_delay(); continue
                data = resp.json()
                if isinstance(data, list):
                    messages = data
                elif isinstance(data, dict):
                    messages = data.get("hydra:member") or data.get("messages") or []
                else:
                    messages = []
                for msg in messages:
                    if not isinstance(msg, dict): continue
                    msg_id = str(msg.get("id") or "").strip()
                    if not msg_id or msg_id in seen_ids: continue
                    seen_ids.add(msg_id)
                    rd = requests.get(f"{base_url}/messages/{msg_id}", headers=headers, proxies=proxies, impersonate="chrome", timeout=15)
                    if rd.status_code != 200: continue
                    md = rd.json()
                    sender = str(((md.get("from") or {}).get("address") or "")).lower()
                    subject = str(md.get("subject") or "")
                    text = str(md.get("text") or "")
                    html = md.get("html") or ""
                    if isinstance(html, list): html = "\n".join(str(x) for x in html)
                    content = "\n".join([subject, text, str(html)])
                    if "openai" not in sender and "openai" not in content.lower(): continue
                    r = _extract(content)
                    if r: return r
                    print(f" 收到 OpenAI 邮件但未提取到链接/验证码")
            except Exception: pass
            _sleep_poll_delay()
        print(" 超时"); return ""

    if token.startswith("tempmail_lol:"):
        real_token = token[len("tempmail_lol:"):]
        for _ in range(40):
            print(".", end="", flush=True)
            try:
                resp = requests.get(f"{TEMPMAIL_LOL_BASE}/inbox?token={real_token}", proxies=proxies, impersonate="chrome", timeout=15)
                if resp.status_code != 200:
                    _sleep_poll_delay(); continue
                for msg in resp.json().get("emails", []):
                    msg_key = _mail_message_seen_key(msg)
                    if msg_key and msg_key in seen_ids: continue
                    if msg_key: seen_ids.add(msg_key)
                    sender = str(msg.get("from") or "").lower()
                    subject = str(msg.get("subject") or "")
                    body = str(msg.get("body") or msg.get("text") or "")
                    html = str(msg.get("html") or "")
                    content = "\n".join([sender, subject, body, html])
                    if "openai" not in content.lower(): continue
                    r = _extract(content)
                    if r: return r
                    print(f" 收到 OpenAI 邮件但未提取到链接/验证码")
            except Exception: pass
            _sleep_poll_delay()
        print(" 超时"); return ""

    # mail.gw 模式
    for _ in range(40):
        print(".", end="", flush=True)
        try:
            resp = requests.get(f"{MAILTM_BASE}/messages", headers=_mailtm_headers(token=token), proxies=proxies, impersonate="chrome", timeout=15)
            if resp.status_code != 200:
                _sleep_poll_delay(); continue
            data = resp.json()
            if isinstance(data, list):
                messages = data
            elif isinstance(data, dict):
                messages = data.get("hydra:member") or data.get("messages") or []
            else:
                messages = []
            for msg in messages:
                if not isinstance(msg, dict): continue
                msg_id = str(msg.get("id") or "").strip()
                if not msg_id or msg_id in seen_ids: continue
                seen_ids.add(msg_id)
                rd = requests.get(f"{MAILTM_BASE}/messages/{msg_id}", headers=_mailtm_headers(token=token), proxies=proxies, impersonate="chrome", timeout=15)
                if rd.status_code != 200: continue
                md = rd.json()
                sender = str(((md.get("from") or {}).get("address") or "")).lower()
                subject = str(md.get("subject") or "")
                intro = str(md.get("intro") or "")
                text = str(md.get("text") or "")
                html = md.get("html") or ""
                if isinstance(html, list): html = "\n".join(str(x) for x in html)
                content = "\n".join([subject, intro, text, str(html)])
                if "openai" not in sender and "openai" not in content.lower(): continue
                r = _extract(content)
                if r: return r
                print(f" 收到 OpenAI 邮件但未提取到链接/验证码")
        except Exception: pass
        _sleep_poll_delay()
    print(" 超时"); return ""


# ==========================================
# OAuth 授权与辅助函数
# ==========================================

AUTH_URL = "https://auth.openai.com/oauth/authorize"
TOKEN_URL = "https://auth.openai.com/oauth/token"
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"

DEFAULT_REDIRECT_URI = f"http://localhost:1455/auth/callback"
DEFAULT_SCOPE = "openid email profile offline_access"


def _b64url_no_pad(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _sha256_b64url_no_pad(s: str) -> str:
    return _b64url_no_pad(hashlib.sha256(s.encode("ascii")).digest())


def _random_state(nbytes: int = 16) -> str:
    return secrets.token_urlsafe(nbytes)


def _pkce_verifier() -> str:
    return secrets.token_urlsafe(64)


def _parse_callback_url(callback_url: str) -> Dict[str, Any]:
    candidate = callback_url.strip()
    if not candidate:
        return {"code": "", "state": "", "error": "", "error_description": ""}

    if "://" not in candidate:
        if candidate.startswith("?"):
            candidate = f"http://localhost{candidate}"
        elif any(ch in candidate for ch in "/?#") or ":" in candidate:
            candidate = f"http://{candidate}"
        elif "=" in candidate:
            candidate = f"http://localhost/?{candidate}"

    parsed = urllib.parse.urlparse(candidate)
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    fragment = urllib.parse.parse_qs(parsed.fragment, keep_blank_values=True)

    for key, values in fragment.items():
        if key not in query or not query[key] or not (query[key][0] or "").strip():
            query[key] = values

    def get1(k: str) -> str:
        v = query.get(k, [""])
        return (v[0] or "").strip()

    code = get1("code")
    state = get1("state")
    error = get1("error")
    error_description = get1("error_description")

    if code and not state and "#" in code:
        code, state = code.split("#", 1)

    if not error and error_description:
        error, error_description = error_description, ""

    return {
        "code": code,
        "state": state,
        "error": error,
        "error_description": error_description,
    }


def _jwt_claims_no_verify(id_token: str) -> Dict[str, Any]:
    if not id_token or id_token.count(".") < 2:
        return {}
    payload_b64 = id_token.split(".")[1]
    pad = "=" * ((4 - (len(payload_b64) % 4)) % 4)
    try:
        payload = base64.urlsafe_b64decode((payload_b64 + pad).encode("ascii"))
        return json.loads(payload.decode("utf-8"))
    except Exception:
        return {}


def _decode_jwt_segment(seg: str) -> Dict[str, Any]:
    raw = (seg or "").strip()
    if not raw:
        return {}
    pad = "=" * ((4 - (len(raw) % 4)) % 4)
    try:
        decoded = base64.urlsafe_b64decode((raw + pad).encode("ascii"))
        return json.loads(decoded.decode("utf-8"))
    except Exception:
        return {}


def _to_int(v: Any) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _post_form(
    url: str, data: Dict[str, str], timeout: int = 30, proxies: Any = None
) -> Dict[str, Any]:
    resp = requests.post(
        url,
        data=data,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        proxies=proxies,
        impersonate="chrome",
        timeout=timeout,
    )
    if resp.status_code != 200:
        raise RuntimeError(
            f"token exchange failed: {resp.status_code}: {resp.text}"
        )
    return resp.json()


@dataclass(frozen=True)
class OAuthStart:
    auth_url: str
    state: str
    code_verifier: str
    redirect_uri: str
    client_id: str = CLIENT_ID


def generate_oauth_url(
    *,
    redirect_uri: str = DEFAULT_REDIRECT_URI,
    scope: str = DEFAULT_SCOPE,
    prompt: Optional[str] = "login",
) -> OAuthStart:
    state = _random_state()
    code_verifier = _pkce_verifier()
    code_challenge = _sha256_b64url_no_pad(code_verifier)

    params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": scope,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "id_token_add_organizations": "true",
        "codex_cli_simplified_flow": "true",
    }
    if prompt is not None:
        params["prompt"] = prompt
    auth_url = f"{AUTH_URL}?{urllib.parse.urlencode(params)}"
    return OAuthStart(
        auth_url=auth_url,
        state=state,
        code_verifier=code_verifier,
        redirect_uri=redirect_uri,
        client_id=CLIENT_ID,
    )


def submit_callback_url(
    *,
    callback_url: str,
    expected_state: str,
    code_verifier: str,
    redirect_uri: str = DEFAULT_REDIRECT_URI,
    client_id: str = CLIENT_ID,
    proxies: Any = None,
) -> str:
    cb = _parse_callback_url(callback_url)
    if cb["error"]:
        desc = cb["error_description"]
        raise RuntimeError(f"oauth error: {cb['error']}: {desc}".strip())

    if not cb["code"]:
        raise ValueError("callback url missing ?code=")
    if not cb["state"]:
        raise ValueError("callback url missing ?state=")
    if cb["state"] != expected_state:
        raise ValueError("state mismatch")

    token_payload = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "code": cb["code"],
        "redirect_uri": redirect_uri,
    }
    if code_verifier:
        token_payload["code_verifier"] = code_verifier

    token_resp = _post_form(
        TOKEN_URL,
        token_payload,
        proxies=proxies,
    )

    access_token = (token_resp.get("access_token") or "").strip()
    refresh_token = (token_resp.get("refresh_token") or "").strip()
    id_token = (token_resp.get("id_token") or "").strip()
    expires_in = _to_int(token_resp.get("expires_in"))

    claims = _jwt_claims_no_verify(id_token)
    email = str(claims.get("email") or "").strip()
    auth_claims = claims.get("https://api.openai.com/auth") or {}
    account_id = str(auth_claims.get("chatgpt_account_id") or "").strip()

    now = int(time.time())
    expired_rfc3339 = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + max(expires_in, 0))
    )
    now_rfc3339 = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))

    config = {
        "id_token": id_token,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "account_id": account_id,
        "last_refresh": now_rfc3339,
        "email": email,
        "type": "codex",
        "expired": expired_rfc3339,
    }

    return json.dumps(config, ensure_ascii=False, separators=(",", ":"))


def _follow_redirect_chain_for_callback(
    *,
    session: Any,
    start_url: str,
    oauth: OAuthStart,
    proxies: Any = None,
    referer: str = "",
    user_agent: str = "",
    sec_ch_ua: str = "",
    max_hops: int = 12,
    timeout: int = 15,
    label: str = "callback-chain",
) -> Optional[str]:
    current_url = (start_url or "").strip()
    if not current_url:
        return None

    current_referer = referer.strip()
    for _ in range(max_hops):
        if "code=" in current_url and "state=" in current_url:
            if "chatgpt.com/api/auth/callback/openai" in current_url:
                callback_json = _chatgpt_experiment_finish_session(
                    session=session,
                    callback_url=current_url,
                    proxies=proxies,
                    user_agent=user_agent,
                    sec_ch_ua=sec_ch_ua,
                    label=label,
                )
                if callback_json:
                    return callback_json
            return submit_callback_url(
                callback_url=current_url,
                code_verifier=oauth.code_verifier,
                redirect_uri=oauth.redirect_uri,
                client_id=oauth.client_id,
                expected_state=oauth.state,
                proxies=proxies,
            )

        headers = {"referer": current_referer} if current_referer else None
        resp = _request_with_retries(
            lambda: session.get(
                current_url,
                headers=headers,
                allow_redirects=False,
                timeout=timeout,
            ),
            label=label,
            attempts=2,
        )
        location = resp.headers.get("Location") or ""
        if resp.status_code not in [301, 302, 303, 307, 308]:
            return None
        if not location:
            return None

        next_url = urllib.parse.urljoin(current_url, location)
        current_referer = current_url
        current_url = next_url

    return None


def _page_type_to_path(page_type: str) -> str:
    mapping = {
        "about_you": "/about-you",
        "contact_verification": "/contact-verification",
        "create_account_password": "/create-account/password",
        "create_account_start": "/create-account",
        "email_otp_verification": "/email-verification",
        "login_password": "/log-in/password",
        "login_start": "/log-in",
        "login_or_signup_start": "/log-in-or-create-account",
        "sign_in_with_chatgpt_codex_consent": "/sign-in-with-chatgpt/codex/consent",
        "sign_in_with_chatgpt_codex_org": "/sign-in-with-chatgpt/codex/organization",
        "workspace": "/workspace",
    }
    return mapping.get(str(page_type or "").strip(), "")


def _page_type_to_url(page_type: str) -> str:
    path = _page_type_to_path(page_type)
    if not path:
        return ""
    return urllib.parse.urljoin("https://auth.openai.com", path)


def _extract_page_type(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    page = data.get("page")
    if isinstance(page, dict):
        return str(page.get("type") or "").strip()
    return ""


def _log_page_transition(prefix: str, data: Any) -> None:
    if not isinstance(data, dict):
        return
    page_type = _extract_page_type(data) or "<none>"
    continue_url = str(data.get("continue_url") or "").strip() or "<none>"
    print(f"[*] {prefix} page={page_type} continue_url={continue_url}")


def _extract_orgs(data: Any) -> List[Dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    payload = data.get("data")
    if not isinstance(payload, dict):
        return []
    orgs = payload.get("orgs")
    if not isinstance(orgs, list):
        return []
    return [org for org in orgs if isinstance(org, dict)]


def _extract_client_auth_session_from_cookie(session: Any) -> Dict[str, Any]:
    cookie_val = ""
    try:
        cookie_val = str(session.cookies.get("oai-client-auth-session") or "").strip()
    except Exception:
        cookie_val = ""
    if not cookie_val:
        return {}

    parts = cookie_val.split(".")
    fallback: Dict[str, Any] = {}
    for seg in parts:
        decoded = _decode_jwt_segment(seg)
        if isinstance(decoded, dict) and decoded:
            # Prefer the richer segment that actually carries workspace/org state.
            if any(key in decoded for key in ("workspaces", "orgs")):
                return decoded
            if not fallback and any(key in decoded for key in ("email", "originator")):
                fallback = decoded
    return fallback


def _extract_minimized_auth_session_from_cookie(session: Any) -> Dict[str, Any]:
    cookie_val = _read_cookie_value(session, "auth-session-minimized")
    if not cookie_val:
        return {}
    decoded = _decode_jwt_payload(cookie_val)
    return decoded if isinstance(decoded, dict) else {}


def _extract_auth_session_metadata(session: Any) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    minimized = _extract_minimized_auth_session_from_cookie(session)
    if minimized:
        merged.update(minimized)
    cookie_session = _extract_client_auth_session_from_cookie(session)
    if cookie_session:
        merged.update(cookie_session)
    return merged


def _read_cookie_value(
    session: Any,
    name: str,
    preferred_domains: Optional[List[str]] = None,
) -> str:
    preferred = [str(item).lower() for item in (preferred_domains or []) if str(item).strip()]
    try:
        return str(session.cookies.get(name) or "").strip()
    except Exception:
        pass

    try:
        matches = []
        for cookie in session.cookies.jar:
            if str(getattr(cookie, "name", "") or "") != name:
                continue
            domain = str(getattr(cookie, "domain", "") or "").lower()
            value = str(getattr(cookie, "value", "") or "").strip()
            if not value:
                continue
            priority = len(preferred) + 1
            for index, candidate in enumerate(preferred):
                if candidate and candidate in domain:
                    priority = index
                    break
            matches.append((priority, len(domain), value))
        if not matches:
            return ""
        matches.sort(key=lambda item: (item[0], item[1]))
        return matches[0][2]
    except Exception:
        return ""


def _fetch_client_auth_session_dump(session: Any) -> Dict[str, Any]:
    try:
        minimized_checksum = _read_cookie_value(session, AUTH_SESSION_MINIMIZED_COOKIE)
        if minimized_checksum:
            print(f"[*] minimized session checksum present: {minimized_checksum[:24]}...")
        resp = _request_with_retries(
            lambda: session.get(
                "https://auth.openai.com/api/accounts/client_auth_session_dump",
                headers={"Accept": "application/json"},
                timeout=15,
            ),
            label="client-auth-session-dump",
        )
        if resp.status_code != 200:
            return {}
        data = resp.json() if resp.text.strip() else {}
        session_data = data.get("client_auth_session") if isinstance(data, dict) else {}
        if isinstance(session_data, dict) and session_data.get("workspaces"):
            print(f"[*] client_auth_session_dump workspaces: {len(session_data.get('workspaces') or [])}")
        return session_data if isinstance(session_data, dict) else {}
    except Exception:
        return {}


def _extract_chatgpt_bootstrap(html: str) -> Dict[str, Any]:
    text = str(html or "")
    m = re.search(
        r'<script[^>]+id="client-bootstrap"[^>]*>(.*?)</script>',
        text,
        re.S,
    )
    if not m:
        return {}
    try:
        return json.loads(m.group(1))
    except Exception:
        return {}


def _chatgpt_experiment_warm(
    session: Any,
    *,
    user_agent: str,
    sec_ch_ua: str,
    label: str,
) -> Dict[str, Any]:
    if not _experiment_enabled:
        return {}
    headers = {
        "user-agent": user_agent,
        "sec-ch-ua": sec_ch_ua,
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
    }
    summary: Dict[str, Any] = {}
    try:
        _normalize_chatgpt_callback_cookie(session)
        root_resp = _request_with_retries(
            lambda: session.get(
                "https://chatgpt.com/",
                headers=headers,
                timeout=15,
            ),
            label=f"{label}-chatgpt-root",
            attempts=2,
        )
        root_bootstrap = _extract_chatgpt_bootstrap(root_resp.text)
        if root_bootstrap:
            summary["root_auth_status"] = str(root_bootstrap.get("authStatus") or "").strip()
            summary["root_session_id"] = str(root_bootstrap.get("sessionId") or "").strip()
            summary["root_cluster"] = str(root_bootstrap.get("cluster") or "").strip()

        login_resp = _request_with_retries(
            lambda: session.get(
                "https://chatgpt.com/auth/login",
                headers=headers,
                timeout=15,
            ),
            label=f"{label}-chatgpt-login",
            attempts=2,
        )
        bootstrap = _extract_chatgpt_bootstrap(login_resp.text)
        if bootstrap:
            summary["auth_status"] = str(bootstrap.get("authStatus") or "").strip()
            summary["session_id"] = str(bootstrap.get("sessionId") or "").strip()
            summary["cluster"] = str(bootstrap.get("cluster") or "").strip()

        session_resp = _request_with_retries(
            lambda: session.get(
                "https://chatgpt.com/api/auth/session",
                headers={"accept": "application/json", **headers},
                timeout=15,
            ),
            label=f"{label}-chatgpt-session",
            attempts=2,
        )
        summary["session_status"] = int(session_resp.status_code)
        summary["csrf_cookie"] = bool(
            _read_cookie_value(session, "__Host-next-auth.csrf-token")
        )
        summary["callback_cookie"] = bool(
            _read_cookie_value(session, "__Secure-next-auth.callback-url")
        )
        summary["oai_did"] = _read_cookie_value(
            session,
            "oai-did",
            preferred_domains=["chatgpt.com", "openai.com"],
        )
        print(
            "[*] chatgpt experiment warm: "
            f"root_auth={summary.get('root_auth_status') or '<none>'} "
            f"login_auth={summary.get('auth_status') or '<none>'} "
            f"session_status={summary.get('session_status')} "
            f"csrf={summary.get('csrf_cookie')} "
            f"callback={summary.get('callback_cookie')} "
            f"did={'yes' if summary.get('oai_did') else 'no'}"
        )
    except Exception as e:
        print(f"[Warn] chatgpt experiment warm failed: {e}")
    return summary


def _normalize_chatgpt_callback_cookie(session: Any) -> None:
    target = "https://chatgpt.com/"
    try:
        session.cookies.set(
            "__Secure-next-auth.callback-url",
            urllib.parse.quote(target, safe=":/"),
            domain="chatgpt.com",
            path="/",
        )
    except Exception:
        pass


def _chatgpt_experiment_probe_callback(
    *,
    session: Any,
    oauth: OAuthStart,
    proxies: Any,
    referer: str,
    label: str,
    user_agent: str = "",
    sec_ch_ua: str = "",
    email: str = "",
    password: str = "",
    dev_token: str = "",
    impersonate: str = "",
) -> Optional[str]:
    if not _experiment_enabled:
        return None
    for candidate in [
        "https://chatgpt.com/auth/login",
        "https://chatgpt.com/",
    ]:
        callback_json = _follow_redirect_chain_for_callback(
            session=session,
            start_url=candidate,
            oauth=oauth,
            proxies=proxies,
            referer=referer,
            user_agent=user_agent,
            sec_ch_ua=sec_ch_ua,
            max_hops=6,
            label=label,
        )
        if callback_json:
            if (
                callback_json
                and _is_experiment_token_payload(_token_payload_or_empty(callback_json))
                and email
                and password
                and dev_token
            ):
                try:
                    formal_json = _login_for_token(
                        email,
                        password,
                        dev_token,
                        proxies,
                        impersonate or "chrome",
                        user_agent,
                        sec_ch_ua,
                        force_standard_oauth=True,
                    )
                    if formal_json:
                        print(f"[*] chatgpt experiment probe promoted: {candidate}")
                        return formal_json
                except Exception as e:
                    print(f"[Warn] chatgpt experiment probe promote failed: {e}")
            print(f"[*] chatgpt experiment callback hit: {candidate}")
            return callback_json
    return None


def _chatgpt_experiment_finish_session(
    *,
    session: Any,
    callback_url: str,
    proxies: Any = None,
    user_agent: str = "",
    sec_ch_ua: str = "",
    label: str = "",
) -> Optional[str]:
    if not _experiment_enabled:
        return None
    target = str(callback_url or "").strip()
    if not target:
        return None
    try:
        resp = _request_with_retries(
            lambda: session.get(
                target,
                allow_redirects=True,
                timeout=20,
            ),
            label="chatgpt-callback",
            attempts=2,
        )
        print(f"[*] chatgpt callback final: {resp.status_code} {resp.url}")
    except Exception as e:
        print(f"[Warn] chatgpt callback failed: {e}")

    try:
        session_resp = _request_with_retries(
            lambda: session.get(
                "https://chatgpt.com/api/auth/session",
                headers={"accept": "application/json"},
                timeout=20,
            ),
            label="chatgpt-auth-session",
            attempts=2,
        )
        if session_resp.status_code != 200:
            return None
        data = session_resp.json() if session_resp.text.strip() else {}
        access_token = str(data.get("accessToken") or "").strip()
        session_token = str(data.get("sessionToken") or "").strip()
        expires = str(data.get("expires") or "").strip()
        user = data.get("user") or {}
        account = data.get("account") or {}
        email = str((user or {}).get("email") or "").strip()
        account_id = str((account or {}).get("id") or "").strip()
        if not access_token or not email:
            return None

        config = {
            "id_token": "",
            "access_token": access_token,
            "refresh_token": session_token,
            "session_token": session_token,
            "account_id": account_id,
            "last_refresh": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "email": email,
            "type": "chatgpt_experiment",
            "expired": expires or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 3600)),
        }
        print("[*] chatgpt experiment session materialized")
        return json.dumps(config, ensure_ascii=False, separators=(",", ":"))
    except Exception as e:
        print(f"[Warn] chatgpt auth session finalize failed: {e}")
        return None


def _chatgpt_experiment_try_code_exchange(
    *,
    session: Any,
    callback_url: str,
    proxies: Any,
) -> Optional[str]:
    parsed = urllib.parse.urlparse(str(callback_url or "").strip())
    query = urllib.parse.parse_qs(parsed.query)
    code = str((query.get("code") or [""])[0] or "").strip()
    if not code:
        return None

    attempts = [
        {
            "grant_type": "authorization_code",
            "client_id": "app_X8zY6vW2pQ9tR3dE7nK1jL5gH",
            "code": code,
            "redirect_uri": "https://chatgpt.com/api/auth/callback/openai",
        },
        {
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "code": code,
            "redirect_uri": DEFAULT_REDIRECT_URI,
        },
        {
            "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
            "client_id": CLIENT_ID,
            "subject_token_type": "urn:ietf:params:oauth:token-type:authorization_code",
            "subject_token": code,
            "scope": DEFAULT_SCOPE,
        },
    ]

    for payload in attempts:
        try:
            resp = session.post(
                TOKEN_URL,
                data=payload,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
                timeout=20,
            )
            print(
                "[*] chatgpt code exchange probe: "
                f"grant={payload.get('grant_type')} "
                f"client_id={payload.get('client_id')} "
                f"status={resp.status_code}"
            )
            if resp.status_code != 200:
                continue
            data = resp.json() if resp.text.strip() else {}
            access_token = str(data.get("access_token") or "").strip()
            refresh_token = str(data.get("refresh_token") or "").strip()
            id_token = str(data.get("id_token") or "").strip()
            if not access_token or not refresh_token:
                continue
            claims = _jwt_claims_no_verify(id_token)
            auth_claims = claims.get("https://api.openai.com/auth") or {}
            account_id = str(auth_claims.get("chatgpt_account_id") or "").strip()
            email = str(claims.get("email") or "").strip()
            expires_in = _to_int(data.get("expires_in"))
            now = int(time.time())
            config = {
                "id_token": id_token,
                "access_token": access_token,
                "refresh_token": refresh_token,
                "account_id": account_id,
                "last_refresh": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
                "email": email,
                "type": "codex",
                "expired": time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ",
                    time.gmtime(now + max(expires_in, 0)),
                ),
            }
            print("[*] chatgpt code exchange produced formal oauth token")
            return json.dumps(config, ensure_ascii=False, separators=(",", ":"))
        except Exception as e:
            print(f"[Warn] chatgpt code exchange probe failed: {e}")
    return None


def _chatgpt_experiment_try_passwordless_formal_token(
    *,
    session: Any,
    email: str,
    dev_token: str,
    proxies: Any,
    user_agent: str,
    sec_ch_ua: str,
) -> Optional[str]:
    login_body = json.dumps(
        {"username": {"value": email, "kind": "email"}, "screen_hint": "login"}
    )
    did = _read_cookie_value(
        session,
        "oai-did",
        preferred_domains=["auth.openai.com", "openai.com", "chatgpt.com"],
    )

    def _sentinel(flow: str = SENTINEL_FLOW_SIGNUP_EMAIL) -> str:
        sdk_token = _fetch_sentinel_sdk_token(
            flow=flow,
            user_agent=user_agent,
            proxy_url=_extract_proxy_url_from_proxies(proxies),
        )
        if sdk_token:
            return sdk_token
        rj = _fetch_sentinel_payload(
            did=did,
            flow=flow,
            user_agent=user_agent,
            sec_ch_ua=sec_ch_ua,
            proxies=proxies,
            impersonate="chrome",
            label="experiment-passwordless",
        )
        c_token = rj.get("token", "")
        turnstile = rj.get("turnstile")
        t_val = turnstile.get("dx", "") if isinstance(turnstile, dict) else ""
        p_val = _build_sentinel_pow_token(rj, user_agent) or ""
        return json.dumps({"p": p_val, "t": t_val, "c": c_token, "id": did, "flow": flow})

    def _headers(referer: str, sentinel: str) -> Dict[str, str]:
        return {
            "referer": referer,
            "accept": "application/json",
            "content-type": "application/json",
            "openai-sentinel-token": sentinel,
            "user-agent": user_agent,
            "sec-ch-ua": sec_ch_ua,
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
        }

    try:
        login_resp = _request_with_retries(
            lambda: session.post(
                "https://auth.openai.com/api/accounts/authorize/continue",
                headers=_headers(
                    "https://auth.openai.com/sign-in",
                    _sentinel(SENTINEL_FLOW_SIGNUP_EMAIL),
                ),
                data=login_body,
                timeout=20,
            ),
            label="experiment-passwordless-login",
            attempts=2,
        )
        if login_resp.status_code != 200:
            return None
        data = login_resp.json() if login_resp.text.strip() else {}
        page_type = _extract_page_type(data)
        continue_url = str(data.get("continue_url") or "").strip()
        print(
            "[*] experiment passwordless login page: "
            f"{page_type or '<none>'} {continue_url or '<none>'}"
        )
        if "email" not in page_type.lower() or "otp" not in page_type.lower():
            return None
        if continue_url:
            session.get(
                continue_url,
                headers={"referer": "https://auth.openai.com/sign-in"},
                allow_redirects=True,
                timeout=20,
            )

        seen_msg_ids = set()
        otp_code = get_oai_code(dev_token, email, proxies, seen_msg_ids=seen_msg_ids)
        if not otp_code:
            try:
                _request_with_retries(
                    lambda: session.post(
                        "https://auth.openai.com/api/accounts/email-otp/resend",
                        headers=_headers(
                            "https://auth.openai.com/email-verification",
                            _sentinel(SENTINEL_FLOW_EMAIL_OTP),
                        ),
                        data="{}",
                        timeout=20,
                    ),
                    label="experiment-passwordless-resend",
                    attempts=2,
                )
            except Exception:
                pass
            time.sleep(random.uniform(4.0, 7.0))
            otp_code = get_oai_code(dev_token, email, proxies, seen_msg_ids=seen_msg_ids)
        if not otp_code:
            return None

        otp_resp = _request_with_retries(
            lambda: session.post(
                "https://auth.openai.com/api/accounts/email-otp/validate",
                headers=_headers(
                    "https://auth.openai.com/email-verification",
                    _sentinel(SENTINEL_FLOW_EMAIL_OTP),
                ),
                data=json.dumps({"code": otp_code}),
                timeout=20,
            ),
            label="experiment-passwordless-validate",
            attempts=2,
        )
        if otp_resp.status_code != 200:
            return None
        otp_data = otp_resp.json() if otp_resp.text.strip() else {}
        otp_continue = str(otp_data.get("continue_url") or "").strip()
        otp_page_type = _extract_page_type(otp_data)
        print(
            "[*] experiment passwordless otp result: "
            f"{otp_page_type or '<none>'} {otp_continue or '<none>'}"
        )
        if otp_continue and "code=" in otp_continue and "state=" in otp_continue:
            return submit_callback_url(
                callback_url=otp_continue,
                code_verifier="",
                redirect_uri=DEFAULT_REDIRECT_URI,
                client_id=CLIENT_ID,
                expected_state=_parse_callback_url(otp_continue).get("state", ""),
                proxies=proxies,
            )
    except Exception as e:
        print(f"[Warn] experiment passwordless formalization failed: {e}")
    return None


def _chatgpt_experiment_promote_session(
    *,
    session: Any,
    proxies: Any,
    user_agent: str,
    sec_ch_ua: str,
    label: str,
) -> Optional[str]:
    if not _experiment_enabled:
        return None
    try:
        oauth = generate_oauth_url(prompt=None)
        headers = {
            "user-agent": user_agent,
            "sec-ch-ua": sec_ch_ua,
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "referer": "https://chatgpt.com/",
        }
        entry = _request_with_retries(
            lambda: session.get(
                oauth.auth_url,
                headers=headers,
                allow_redirects=False,
                timeout=20,
            ),
            label=f"{label}-oauth-promote-entry",
            attempts=2,
        )
        current_url = oauth.auth_url
        location = entry.headers.get("Location") or ""
        if entry.status_code in [301, 302, 303, 307, 308] and location:
            current_url = urllib.parse.urljoin(current_url, location)
        callback_json = _follow_redirect_chain_for_callback(
            session=session,
            start_url=current_url,
            oauth=oauth,
            proxies=proxies,
            referer="https://chatgpt.com/",
            user_agent=user_agent,
            sec_ch_ua=sec_ch_ua,
            max_hops=12,
            label=f"{label}-oauth-promote-chain",
        )
        if callback_json:
            print("[*] chatgpt experiment promoted into codex oauth token")
            return callback_json

        landing = _request_with_retries(
            lambda: session.get(
                oauth.auth_url,
                headers=headers,
                allow_redirects=True,
                timeout=20,
            ),
            label=f"{label}-oauth-promote-landing",
            attempts=2,
        )
        print(f"[*] chatgpt experiment promote landing: {landing.status_code} {landing.url}")
        if "code=" in landing.url and "state=" in landing.url:
            callback_json = submit_callback_url(
                callback_url=landing.url,
                code_verifier=oauth.code_verifier,
                redirect_uri=oauth.redirect_uri,
                client_id=oauth.client_id,
                expected_state=oauth.state,
                proxies=proxies,
            )
            if callback_json:
                print("[*] chatgpt experiment promoted from landing url")
                return callback_json
    except Exception as e:
        print(f"[Warn] chatgpt experiment promote failed: {e}")
    return None


def _chatgpt_experiment_prime_fresh_oauth_state(
    *,
    session: Any,
    user_agent: str,
    sec_ch_ua: str,
    label: str,
) -> Optional[OAuthStart]:
    if not _experiment_enabled:
        return None
    try:
        oauth = _generate_chatgpt_experiment_oauth_start(
            session,
            user_agent=user_agent,
            sec_ch_ua=sec_ch_ua,
            label=f"{label}-fresh",
        )
        if not oauth:
            return None

        current_url = oauth.auth_url
        current_referer = "https://chatgpt.com/auth/login"
        for hop in range(3):
            resp = _request_with_retries(
                lambda: session.get(
                    current_url,
                    headers={"referer": current_referer},
                    allow_redirects=False,
                    timeout=20,
                ),
                label=f"{label}-fresh-oauth-hop-{hop + 1}",
                attempts=2,
            )
            location = resp.headers.get("Location") or ""
            print(
                "[*] experiment fresh oauth hop: "
                f"{resp.status_code} {resp.url}"
            )
            if resp.status_code not in [301, 302, 303, 307, 308] or not location:
                break
            next_url = urllib.parse.urljoin(current_url, location)
            if "code=" in next_url and "state=" in next_url:
                print("[*] experiment fresh oauth reached callback redirect")
                break
            current_referer = current_url
            current_url = next_url

        print(
            "[*] experiment fresh oauth primed: "
            f"state={oauth.state[:12]} "
            f"login_session={'yes' if _read_cookie_value(session, 'login_session', preferred_domains=['auth.openai.com']) else 'no'}"
        )
        return oauth
    except Exception as e:
        print(f"[Warn] experiment fresh oauth prime failed: {e}")
        return None


def _chatgpt_experiment_passwordless_login_to_formal(
    *,
    session: Any,
    email: str,
    dev_token: str,
    proxies: Any,
    user_agent: str,
    sec_ch_ua: str,
    label: str,
    did: str = "",
    seen_msg_ids: Optional[set] = None,
    initial_otp_code: str = "",
    expected_chatgpt_state: str = "",
) -> Optional[str]:
    if not _experiment_enabled:
        return None

    seen = seen_msg_ids if seen_msg_ids is not None else set()
    ignored_codes = {str(initial_otp_code or "").strip()} - {""}

    def _sentinel(flow: str = SENTINEL_FLOW_SIGNUP_EMAIL) -> str:
        sdk_token = _fetch_sentinel_sdk_token(
            flow=flow,
            user_agent=user_agent,
            proxy_url=_extract_proxy_url_from_proxies(proxies),
        )
        if sdk_token:
            return sdk_token
        rj = _fetch_sentinel_payload(
            did=did,
            flow=flow,
            user_agent=user_agent,
            sec_ch_ua=sec_ch_ua,
            proxies=proxies,
            impersonate="chrome",
            label=f"{label}-sentinel",
        )
        c_token = rj.get("token", "")
        turnstile = rj.get("turnstile")
        t_val = turnstile.get("dx", "") if isinstance(turnstile, dict) else ""
        p_val = _build_sentinel_pow_token(rj, user_agent) or ""
        return json.dumps({"p": p_val, "t": t_val, "c": c_token, "id": did, "flow": flow})

    def _headers(referer: str, sentinel: str) -> dict:
        return {
            "referer": referer,
            "accept": "application/json",
            "content-type": "application/json",
            "openai-sentinel-token": sentinel,
            "user-agent": user_agent,
            "sec-ch-ua": sec_ch_ua,
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
        }

    def _fresh_mailbox_recovery(disallow_codes: Optional[set] = None) -> str:
        blocked = {str(code).strip() for code in (disallow_codes or set()) if str(code).strip()}
        for round_idx in range(2):
            recovery_seen: set = set()
            candidate = get_oai_code(dev_token, email, proxies, seen_msg_ids=recovery_seen)
            if candidate and candidate not in blocked:
                print("[*] experiment passwordless recovered OTP via fresh mailbox scan")
                return candidate
            if candidate:
                print("[*] experiment passwordless ignored stale OTP during fresh mailbox scan")
            try:
                _request_with_retries(
                    lambda: session.post(
                        "https://auth.openai.com/api/accounts/email-otp/resend",
                        headers=_headers(
                            "https://auth.openai.com/email-verification",
                            _sentinel(SENTINEL_FLOW_EMAIL_OTP),
                        ),
                        data="{}",
                        timeout=15,
                    ),
                    label=f"{label}-passwordless-recovery-resend-{round_idx + 1}",
                )
            except Exception:
                pass
            time.sleep(random.uniform(4.0, 7.0))
        return ""

    try:
        login_resp = _request_with_retries(
            lambda: session.post(
                "https://auth.openai.com/api/accounts/authorize/continue",
                headers=_headers("https://auth.openai.com/sign-in", _sentinel(SENTINEL_FLOW_SIGNUP_EMAIL)),
                data=json.dumps({"username": {"value": email, "kind": "email"}, "screen_hint": "login"}),
                timeout=20,
            ),
            label=f"{label}-passwordless-login-start",
        )
        print(f"[*] experiment passwordless login start: {login_resp.status_code}")
        if login_resp.status_code != 200:
            return None
        login_data = login_resp.json() if login_resp.text.strip() else {}
        _log_page_transition("experiment-passwordless-login", login_data)
        page_type = _extract_page_type(login_data)
        continue_url = str(login_data.get("continue_url") or "").strip()
        if continue_url:
            session.get(
                continue_url,
                headers={"referer": "https://auth.openai.com/sign-in"},
                allow_redirects=True,
                timeout=20,
            )
        if "email" not in page_type.lower() or "otp" not in page_type.lower():
            return None

        if ignored_codes:
            print("[*] experiment passwordless waits for a fresh OTP; signup OTP is skipped")
        otp_code = get_oai_code(dev_token, email, proxies, seen_msg_ids=seen)
        if otp_code in ignored_codes:
            print("[*] experiment passwordless ignored reused signup OTP")
            otp_code = ""
        if not otp_code:
            try:
                _request_with_retries(
                    lambda: session.post(
                        "https://auth.openai.com/api/accounts/email-otp/resend",
                        headers=_headers(
                            "https://auth.openai.com/email-verification",
                            _sentinel(SENTINEL_FLOW_EMAIL_OTP),
                        ),
                        data="{}",
                        timeout=15,
                    ),
                    label=f"{label}-passwordless-resend",
                )
            except Exception:
                pass
            time.sleep(random.uniform(4.0, 7.0))
            otp_code = get_oai_code(dev_token, email, proxies, seen_msg_ids=seen)
            if otp_code in ignored_codes:
                print("[*] experiment passwordless ignored reused signup OTP after resend")
                otp_code = ""
        if not otp_code:
            otp_code = _fresh_mailbox_recovery(ignored_codes)
        if not otp_code:
            return None

        otp_resp = _request_with_retries(
            lambda: session.post(
                "https://auth.openai.com/api/accounts/email-otp/validate",
                headers=_headers(
                    "https://auth.openai.com/email-verification",
                    _sentinel(SENTINEL_FLOW_EMAIL_OTP),
                ),
                data=json.dumps({"code": otp_code}),
                timeout=20,
            ),
            label=f"{label}-passwordless-validate",
        )
        print(f"[*] experiment passwordless otp validate: {otp_resp.status_code}")
        if otp_resp.status_code != 200:
            otp_body = otp_resp.text[:400]
            print(f"[Warn] experiment passwordless otp body: {otp_body}")
            if otp_resp.status_code == 401 and "wrong_email_otp_code" in otp_body:
                ignored_codes.add(str(otp_code).strip())
                otp_code = _fresh_mailbox_recovery(ignored_codes)
                if otp_code:
                    otp_resp = _request_with_retries(
                        lambda: session.post(
                            "https://auth.openai.com/api/accounts/email-otp/validate",
                            headers=_headers(
                                "https://auth.openai.com/email-verification",
                                _sentinel(SENTINEL_FLOW_EMAIL_OTP),
                            ),
                            data=json.dumps({"code": otp_code}),
                            timeout=20,
                        ),
                        label=f"{label}-passwordless-validate-retry",
                    )
                    print(
                        "[*] experiment passwordless otp validate retry: "
                        f"{otp_resp.status_code}"
                    )
            if otp_resp.status_code != 200:
                return None
        otp_data = otp_resp.json() if otp_resp.text.strip() else {}
        _log_page_transition("experiment-passwordless-otp", otp_data)
        otp_continue = str(otp_data.get("continue_url") or "").strip()
        if expected_chatgpt_state and otp_continue and "state=" in otp_continue:
            actual_state = _parse_callback_url(otp_continue).get("state", "")
            print(
                "[*] experiment passwordless callback state: "
                f"expected={expected_chatgpt_state} actual={actual_state or '<none>'}"
            )
        return json.dumps(otp_data, ensure_ascii=False, separators=(",", ":"))
    except Exception as e:
        print(f"[Warn] experiment passwordless login failed: {e}")
    return None


def _chatgpt_experiment_same_session_login_to_formal(
    *,
    session: Any,
    email: str,
    password: str,
    dev_token: str,
    proxies: Any,
    user_agent: str,
    sec_ch_ua: str,
    label: str,
    fresh_oauth: Optional[OAuthStart] = None,
) -> Optional[str]:
    if not _experiment_enabled:
        return None

    fresh_oauth = fresh_oauth or _generate_chatgpt_experiment_oauth_start(
        session,
        user_agent=user_agent,
        sec_ch_ua=sec_ch_ua,
        label=f"{label}-fresh",
    )
    if not fresh_oauth:
        return None

    raw_did = _read_cookie_value(
        session,
        "oai-did",
        preferred_domains=["auth.openai.com", "openai.com", "chatgpt.com"],
    )

    def _sentinel(flow: str = SENTINEL_FLOW_SIGNUP_EMAIL) -> str:
        sdk_token = _fetch_sentinel_sdk_token(
            flow=flow,
            user_agent=user_agent,
            proxy_url=_extract_proxy_url_from_proxies(proxies),
        )
        if sdk_token:
            return sdk_token
        rj = _fetch_sentinel_payload(
            did=raw_did,
            flow=flow,
            user_agent=user_agent,
            sec_ch_ua=sec_ch_ua,
            proxies=proxies,
            impersonate="chrome",
            label=f"{label}-same-session-sentinel",
        )
        c_token = rj.get("token", "")
        turnstile = rj.get("turnstile")
        t_val = turnstile.get("dx", "") if isinstance(turnstile, dict) else ""
        p_val = _build_sentinel_pow_token(rj, user_agent) or ""
        return json.dumps({"p": p_val, "t": t_val, "c": c_token, "id": raw_did, "flow": flow})

    def _headers(referer: str, sentinel: str) -> dict:
        return {
            "referer": referer,
            "accept": "application/json",
            "content-type": "application/json",
            "openai-sentinel-token": sentinel,
            "user-agent": user_agent,
            "sec-ch-ua": sec_ch_ua,
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
        }

    try:
        if fresh_oauth:
            print(
                "[*] experiment same-session reuses fresh oauth state: "
                f"{fresh_oauth.state[:12]}"
            )

        login_resp = _request_with_retries(
            lambda: session.post(
                "https://auth.openai.com/api/accounts/authorize/continue",
                headers=_headers(
                    "https://auth.openai.com/sign-in",
                    _sentinel(SENTINEL_FLOW_SIGNUP_EMAIL),
                ),
                data=json.dumps({"username": {"value": email, "kind": "email"}, "screen_hint": "login"}),
                timeout=20,
            ),
            label=f"{label}-same-session-login-start",
        )
        print(f"[*] experiment same-session login start: {login_resp.status_code}")
        if login_resp.status_code != 200:
            return None
        login_data = login_resp.json() if login_resp.text.strip() else {}
        _log_page_transition("experiment-same-session-login", login_data)
        login_continue = str(login_data.get("continue_url") or "").strip()
        if login_continue:
            session.get(
                login_continue,
                headers={"referer": "https://auth.openai.com/sign-in"},
                allow_redirects=True,
                timeout=20,
            )

        pwd_resp = _request_with_retries(
            lambda: session.post(
                "https://auth.openai.com/api/accounts/password/verify",
                headers=_headers(
                    "https://auth.openai.com/log-in/password",
                    _sentinel(SENTINEL_FLOW_PASSWORD_VERIFY),
                ),
                data=json.dumps({"password": password}),
                timeout=20,
            ),
            label=f"{label}-same-session-password-verify",
        )
        print(f"[*] experiment same-session password verify: {pwd_resp.status_code}")
        if pwd_resp.status_code != 200:
            print(f"[Warn] experiment same-session password body: {pwd_resp.text[:400]}")
            return None
        pwd_data = pwd_resp.json() if pwd_resp.text.strip() else {}
        _log_page_transition("experiment-same-session-password", pwd_data)
        pwd_continue = str(pwd_data.get("continue_url") or "").strip()
        if pwd_continue:
            session.get(
                pwd_continue,
                headers={"referer": "https://auth.openai.com/log-in/password"},
                allow_redirects=True,
                timeout=20,
            )

        pwd_page_type = _extract_page_type(pwd_data)
        if "email" not in pwd_page_type.lower() or "otp" not in pwd_page_type.lower():
            return None

        otp_code = _fetch_login_email_otp(
            session=session,
            dev_token=dev_token,
            email=email,
            proxies=proxies,
            get_sentinel=_sentinel,
            build_headers=_headers,
        )
        if not otp_code:
            return None

        otp_resp = _request_with_retries(
            lambda: session.post(
                "https://auth.openai.com/api/accounts/email-otp/validate",
                headers=_headers(
                    "https://auth.openai.com/email-verification",
                    _sentinel(SENTINEL_FLOW_EMAIL_OTP),
                ),
                data=json.dumps({"code": otp_code}),
                timeout=20,
            ),
            label=f"{label}-same-session-login-otp",
        )
        print(f"[*] experiment same-session login otp validate: {otp_resp.status_code}")
        if otp_resp.status_code != 200:
            otp_body = otp_resp.text[:400]
            print(f"[Warn] experiment same-session login otp body: {otp_body}")
            if otp_resp.status_code == 401 and "wrong_email_otp_code" in otp_body:
                retry_code = _fetch_login_email_otp(
                    session=session,
                    dev_token=dev_token,
                    email=email,
                    proxies=proxies,
                    get_sentinel=_sentinel,
                    build_headers=_headers,
                    blocked_codes={otp_code},
                )
                if retry_code:
                    otp_resp = _request_with_retries(
                        lambda: session.post(
                            "https://auth.openai.com/api/accounts/email-otp/validate",
                            headers=_headers(
                                "https://auth.openai.com/email-verification",
                                _sentinel(SENTINEL_FLOW_EMAIL_OTP),
                            ),
                            data=json.dumps({"code": retry_code}),
                            timeout=20,
                        ),
                        label=f"{label}-same-session-login-otp-retry",
                    )
                    print(
                        "[*] experiment same-session login otp retry validate: "
                        f"{otp_resp.status_code}"
                    )
            if otp_resp.status_code != 200:
                return None
        otp_data = otp_resp.json() if otp_resp.text.strip() else {}
        _log_page_transition("experiment-same-session-login-otp", otp_data)
        return json.dumps(otp_data, ensure_ascii=False, separators=(",", ":"))
    except Exception as e:
        print(f"[Warn] experiment same-session login failed: {e}")
        return None


def _chatgpt_experiment_finalize_to_formal_token(
    *,
    session: Any,
    callback_url: str,
    email: str,
    password: str,
    dev_token: str,
    proxies: Any,
    impersonate: str,
    user_agent: str,
    sec_ch_ua: str,
    label: str,
    seen_msg_ids: Optional[set] = None,
    signup_otp_code: str = "",
) -> Optional[str]:
    exchanged = _chatgpt_experiment_try_code_exchange(
        session=session,
        callback_url=callback_url,
        proxies=proxies,
    )
    if exchanged:
        return exchanged

    experiment_json = _chatgpt_experiment_finish_session(
        session=session,
        callback_url=callback_url,
        proxies=proxies,
        user_agent=user_agent,
        sec_ch_ua=sec_ch_ua,
        label=label,
    )
    if not experiment_json:
        return None

    raw_did = _read_cookie_value(
        session,
        "oai-did",
        preferred_domains=["auth.openai.com", "openai.com", "chatgpt.com"],
    )

    fresh_oauth = _chatgpt_experiment_prime_fresh_oauth_state(
        session=session,
        user_agent=user_agent,
        sec_ch_ua=sec_ch_ua,
        label=label,
    )

    same_session_probe = _chatgpt_experiment_same_session_login_to_formal(
        session=session,
        email=email,
        password=password,
        dev_token=dev_token,
        proxies=proxies,
        user_agent=user_agent,
        sec_ch_ua=sec_ch_ua,
        label=label,
        fresh_oauth=fresh_oauth,
    )
    if same_session_probe:
        print("[*] experiment same-session branch produced follow-up payload")
        same_payload = _token_payload_or_empty(same_session_probe)
        same_continue = str(same_payload.get("continue_url") or "").strip()
        if same_continue and "error=" not in same_continue and "code=" in same_continue and "state=" in same_continue:
            exchanged = _chatgpt_experiment_try_code_exchange(
                session=session,
                callback_url=same_continue,
                proxies=proxies,
            )
            if exchanged:
                return exchanged
            promoted = _chatgpt_experiment_promote_session(
                session=session,
                proxies=proxies,
                user_agent=user_agent,
                sec_ch_ua=sec_ch_ua,
                label=f"{label}-same-session-hot-promote",
            )
            if promoted:
                print("[*] experiment same-session callback promoted before callback consumption")
                return promoted
            refreshed = _chatgpt_experiment_finish_session(
                session=session,
                callback_url=same_continue,
                proxies=proxies,
                user_agent=user_agent,
                sec_ch_ua=sec_ch_ua,
                label=f"{label}-same-session-refresh",
            )
            if refreshed:
                experiment_json = refreshed
            promoted = _chatgpt_experiment_promote_session(
                session=session,
                proxies=proxies,
                user_agent=user_agent,
                sec_ch_ua=sec_ch_ua,
                label=f"{label}-same-session-promote",
            )
            if promoted:
                return promoted

    passwordless_probe = _chatgpt_experiment_passwordless_login_to_formal(
        session=session,
        email=email,
        dev_token=dev_token,
        proxies=proxies,
        user_agent=user_agent,
        sec_ch_ua=sec_ch_ua,
        label=label,
        did=raw_did,
        seen_msg_ids=seen_msg_ids,
        initial_otp_code=signup_otp_code,
        expected_chatgpt_state=fresh_oauth.state if fresh_oauth else "",
    )
    if passwordless_probe:
        print("[*] experiment passwordless branch produced follow-up payload")
        pw_payload = _token_payload_or_empty(passwordless_probe)
        pw_continue = str(pw_payload.get("continue_url") or "").strip()
        if pw_continue and "error=" not in pw_continue and "code=" in pw_continue and "state=" in pw_continue:
            exchanged = _chatgpt_experiment_try_code_exchange(
                session=session,
                callback_url=pw_continue,
                proxies=proxies,
            )
            if exchanged:
                return exchanged
            promoted = _chatgpt_experiment_promote_session(
                session=session,
                proxies=proxies,
                user_agent=user_agent,
                sec_ch_ua=sec_ch_ua,
                label=f"{label}-passwordless-hot-promote",
            )
            if promoted:
                print("[*] experiment passwordless callback promoted before callback consumption")
                return promoted
            refreshed_experiment = _chatgpt_experiment_finish_session(
                session=session,
                callback_url=pw_continue,
                proxies=proxies,
                user_agent=user_agent,
                sec_ch_ua=sec_ch_ua,
                label=f"{label}-passwordless-refresh",
            )
            if refreshed_experiment:
                experiment_json = refreshed_experiment
                promoted = _chatgpt_experiment_promote_session(
                    session=session,
                    proxies=proxies,
                    user_agent=user_agent,
                    sec_ch_ua=sec_ch_ua,
                    label=f"{label}-passwordless-promote",
                )
                if promoted:
                    print("[*] experiment passwordless callback promoted via fresh oauth session")
                    return promoted

    try:
        formal_json = _login_for_token(
            email,
            password,
            dev_token,
            proxies,
            impersonate,
            user_agent,
            sec_ch_ua,
            force_standard_oauth=True,
        )
        if formal_json:
            print("[*] experiment session promoted via standard oauth login")
            return formal_json
    except Exception as e:
        print(f"[Warn] experiment formal token conversion failed: {e}")

    return experiment_json


def _chatgpt_experiment_signin_openai(
    session: Any,
    *,
    user_agent: str,
    sec_ch_ua: str,
    label: str,
) -> Dict[str, Any]:
    if not _experiment_enabled:
        return {}
    headers = {
        "user-agent": user_agent,
        "sec-ch-ua": sec_ch_ua,
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "origin": "https://chatgpt.com",
        "referer": "https://chatgpt.com/auth/login",
        "accept": "application/json, text/plain, */*",
        "content-type": "application/x-www-form-urlencoded",
    }
    summary: Dict[str, Any] = {}
    try:
        _normalize_chatgpt_callback_cookie(session)
        csrf_resp = _request_with_retries(
            lambda: session.get(
                "https://chatgpt.com/api/auth/csrf",
                headers={"accept": "application/json", **headers},
                timeout=15,
            ),
            label=f"{label}-chatgpt-csrf",
            attempts=2,
        )
        csrf_data = csrf_resp.json() if csrf_resp.text.strip() else {}
        csrf_token = str(csrf_data.get("csrfToken") or "").strip()
        summary["csrf_token"] = bool(csrf_token)

        providers_resp = _request_with_retries(
            lambda: session.get(
                "https://chatgpt.com/api/auth/providers",
                headers={"accept": "application/json", **headers},
                timeout=15,
            ),
            label=f"{label}-chatgpt-providers",
            attempts=2,
        )
        providers_data = providers_resp.json() if providers_resp.text.strip() else {}
        openai_provider = providers_data.get("openai") if isinstance(providers_data, dict) else {}
        signin_url = str((openai_provider or {}).get("signinUrl") or "").strip()
        callback_url = str((openai_provider or {}).get("callbackUrl") or "").strip()
        summary["provider_signin_url"] = signin_url
        summary["provider_callback_url"] = callback_url

        if csrf_token and signin_url:
            payload = urllib.parse.urlencode(
                {
                    "csrfToken": csrf_token,
                    "callbackUrl": "https://chatgpt.com/",
                    "json": "true",
                }
            )
            signin_resp = _request_with_retries(
                lambda: session.post(
                    signin_url,
                    headers=headers,
                    data=payload,
                    timeout=15,
                ),
                label=f"{label}-chatgpt-signin-openai",
                attempts=2,
            )
            signin_data = signin_resp.json() if signin_resp.text.strip() else {}
            authorize_url = str(signin_data.get("url") or "").strip()
            summary["authorize_url"] = authorize_url
            if authorize_url:
                parsed = urllib.parse.urlparse(authorize_url)
                query = urllib.parse.parse_qs(parsed.query)
                summary["authorize_client_id"] = str((query.get("client_id") or [""])[0] or "").strip()
                summary["authorize_redirect_uri"] = str((query.get("redirect_uri") or [""])[0] or "").strip()
                summary["authorize_state"] = str((query.get("state") or [""])[0] or "").strip()

        print(
            "[*] chatgpt experiment signin: "
            f"csrf={summary.get('csrf_token')} "
            f"signin={'yes' if summary.get('provider_signin_url') else 'no'} "
            f"callback={'yes' if summary.get('provider_callback_url') else 'no'} "
            f"authorize={'yes' if summary.get('authorize_url') else 'no'}"
        )
    except Exception as e:
        print(f"[Warn] chatgpt experiment signin failed: {e}")
    return summary


def _generate_chatgpt_experiment_oauth_start(
    session: Any,
    *,
    user_agent: str,
    sec_ch_ua: str,
    label: str,
) -> Optional[OAuthStart]:
    if not _experiment_enabled:
        return None

    headers = {
        "user-agent": user_agent,
        "sec-ch-ua": sec_ch_ua,
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "accept": "application/json",
        "content-type": "application/x-www-form-urlencoded",
        "origin": "https://chatgpt.com",
        "referer": "https://chatgpt.com/auth/login",
    }
    try:
        csrf_resp = _request_with_retries(
            lambda: session.get(
                "https://chatgpt.com/api/auth/csrf",
                headers={"accept": "application/json", **headers},
                timeout=15,
            ),
            label=f"{label}-chatgpt-csrf",
            attempts=2,
        )
        csrf_data = csrf_resp.json() if csrf_resp.text.strip() else {}
        csrf_token = str(csrf_data.get("csrfToken") or "").strip()
        callback_url = _read_cookie_value(
            session,
            "__Secure-next-auth.callback-url",
            preferred_domains=["chatgpt.com"],
        ) or "https://chatgpt.com"
        if not csrf_token:
            return None

        signin_resp = _request_with_retries(
            lambda: session.post(
                "https://chatgpt.com/api/auth/signin/openai",
                headers=headers,
                data=urllib.parse.urlencode(
                    {
                        "csrfToken": csrf_token,
                        "callbackUrl": callback_url,
                        "json": "true",
                    }
                ),
                timeout=15,
            ),
            label=f"{label}-chatgpt-signin-openai",
            attempts=2,
        )
        signin_data = signin_resp.json() if signin_resp.text.strip() else {}
        auth_url = str(signin_data.get("url") or "").strip()
        if not auth_url:
            return None

        parsed = urllib.parse.urlparse(auth_url)
        query = urllib.parse.parse_qs(parsed.query)
        state = str((query.get("state") or [""])[0] or "").strip()
        redirect_uri = str((query.get("redirect_uri") or [""])[0] or "").strip()
        client_id = str((query.get("client_id") or [""])[0] or "").strip()
        if not state or not redirect_uri or not client_id:
            return None

        print(
            "[*] chatgpt experiment oauth start: "
            f"client_id={client_id} redirect_uri={redirect_uri}"
        )
        return OAuthStart(
            auth_url=auth_url,
            state=state,
            code_verifier="",
            redirect_uri=redirect_uri,
            client_id=client_id,
        )
    except Exception as e:
        print(f"[Warn] chatgpt experiment oauth start failed: {e}")
        try:
            fallback = _chatgpt_experiment_signin_openai(
                session,
                user_agent=user_agent,
                sec_ch_ua=sec_ch_ua,
                label=f"{label}-fallback",
            )
            auth_url = str(fallback.get("authorize_url") or "").strip()
            state = str(fallback.get("authorize_state") or "").strip()
            redirect_uri = str(fallback.get("authorize_redirect_uri") or "").strip()
            client_id = str(fallback.get("authorize_client_id") or "").strip()
            if auth_url and state and redirect_uri and client_id:
                print(
                    "[*] chatgpt experiment oauth fallback start: "
                    f"client_id={client_id} redirect_uri={redirect_uri}"
                )
                return OAuthStart(
                    auth_url=auth_url,
                    state=state,
                    code_verifier="",
                    redirect_uri=redirect_uri,
                    client_id=client_id,
                )
        except Exception as inner:
            print(f"[Warn] chatgpt experiment oauth fallback failed: {inner}")
        return None


def _decode_jwt_payload(token: str) -> Dict[str, Any]:
    raw = str(token or "").strip()
    if raw.count(".") < 2:
        return {}
    return _decode_jwt_segment(raw.split(".")[1])


def _select_first_org_project(
    *,
    session: Any,
    orgs: List[Dict[str, Any]],
    oauth: OAuthStart,
    proxies: Any,
    referer: str,
) -> Optional[str]:
    if not orgs:
        return None

    first_org = orgs[0]
    org_id = str(first_org.get("id") or "").strip()
    projects = first_org.get("projects") or []
    first_project = projects[0] if isinstance(projects, list) and projects else {}
    project_id = str((first_project or {}).get("id") or "").strip()
    if not org_id or not project_id:
        return None

    print(f"[*] 自动选择 organization: {org_id} project: {project_id}")
    resp = _request_with_retries(
        lambda: session.post(
            "https://auth.openai.com/api/accounts/organization/select",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            data=json.dumps({"org_id": org_id, "project_id": project_id}),
            timeout=15,
        ),
        label="select-organization",
    )
    data = resp.json() if resp.text.strip() else {}
    continue_url = str((data.get("continue_url") or "")).strip()
    if continue_url:
        return _follow_redirect_chain_for_callback(
            session=session,
            start_url=continue_url,
            oauth=oauth,
            proxies=proxies,
            referer=referer,
            user_agent="",
            sec_ch_ua="",
            max_hops=10,
            label="organization-select-chain",
        )

    page_type = _extract_page_type(data)
    page_url = _page_type_to_url(page_type)
    if page_url:
        return _follow_redirect_chain_for_callback(
            session=session,
            start_url=page_url,
            oauth=oauth,
            proxies=proxies,
            referer=referer,
            user_agent="",
            sec_ch_ua="",
            max_hops=10,
            label="organization-page-chain",
        )
    return None


# ==========================================
# Chrome 指纹配置
# ==========================================

_CHROME_PROFILES = [
    {
        "major": 131, "impersonate": "chrome131",
        "build": 6778, "patch_range": (69, 205),
        "sec_ch_ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    },
    {
        "major": 133, "impersonate": "chrome133a",
        "build": 6943, "patch_range": (33, 153),
        "sec_ch_ua": '"Not(A:Brand";v="99", "Google Chrome";v="133", "Chromium";v="133"',
    },
    {
        "major": 136, "impersonate": "chrome136",
        "build": 7103, "patch_range": (48, 175),
        "sec_ch_ua": '"Chromium";v="136", "Google Chrome";v="136", "Not.A/Brand";v="99"',
    },
    {
        "major": 142, "impersonate": "chrome142",
        "build": 7540, "patch_range": (30, 150),
        "sec_ch_ua": '"Chromium";v="142", "Google Chrome";v="142", "Not_A Brand";v="99"',
    },
]


def _experiment2_domains() -> List[str]:
    if not _experiment2_enabled:
        return []
    if _experiment2_fresh_cloudvxz and _experiment2_fresh_pool:
        domains = [str(item).strip().lower() for item in _experiment2_fresh_pool if str(item).strip()]
        return _dedupe_keep_order(domains)
    domains = [str(item).strip().lower() for item in _experiment2_domain_pool if str(item).strip()]
    return _dedupe_keep_order(domains)


def _beta_domains() -> List[str]:
    if not _beta_enabled:
        return []
    domains = [str(item).strip().lower() for item in _beta_domain_pool if str(item).strip()]
    return _dedupe_keep_order(domains)


def _beta2_domains() -> List[str]:
    if not _beta2_enabled:
        return []
    source_pool = _beta2_low_domain_pool if _low_mode else _beta2_domain_pool
    domains = [str(item).strip().lower() for item in source_pool if str(item).strip()]
    return _dedupe_keep_order(domains)


def _managed_target_family() -> str:
    if _beta2_enabled:
        return "cloudvxz.com"
    if _beta_enabled:
        return "cloudvxz.com"
    if _experiment2_enabled:
        return _experiment2_force_family
    return ""


def _managed_target_domains() -> List[str]:
    beta2_domains = _beta2_domains()
    if beta2_domains:
        return beta2_domains
    beta_domains = _beta_domains()
    if beta_domains:
        return beta_domains
    return _experiment2_domains()


def _experiment2_profile_config() -> Dict[str, str]:
    profiles = {
        "chrome133a_mac": {
            "impersonate": "chrome133a",
            "user_agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/133.0.6943.98 Safari/537.36"
            ),
            "sec_ch_ua": '"Not(A:Brand";v="99", "Google Chrome";v="133", "Chromium";v="133"',
            "accept_language": "en-US,en;q=0.9,ja;q=0.7",
        },
        "chrome146_current": {
            "impersonate": "chrome",
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/146.0.7680.165 Safari/537.36"
            ),
            "sec_ch_ua": '"Google Chrome";v="146", "Chromium";v="146", "Not_A Brand";v="99"',
            "accept_language": "en-US,en;q=0.9",
        },
        "chrome131_win": {
            "impersonate": "chrome131",
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.6778.162 Safari/537.36"
            ),
            "sec_ch_ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
            "accept_language": "en-GB,en;q=0.9",
        },
        "firefox133_win": {
            "impersonate": "firefox133",
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) "
                "Gecko/20100101 Firefox/133.0"
            ),
            "sec_ch_ua": "",
            "accept_language": "en-US,en;q=0.9,es;q=0.8",
        },
    }
    return profiles.get(_experiment2_profile_name, profiles["chrome133a_mac"])


def _runtime_accept_language(impersonate: str, user_agent: str) -> str:
    if _experiment2_enabled:
        if _experiment2_accept_language:
            return _experiment2_accept_language
        return _experiment2_profile_config()["accept_language"]
    lowered = str(user_agent or "").lower()
    if "firefox" in lowered:
        return "en-US,en;q=0.9,es;q=0.8"
    return "en-US,en;q=0.9"


def _detect_local_browser_profile() -> Optional[tuple]:
    global _local_browser_profile_cache
    with _local_browser_profile_lock:
        if _local_browser_profile_cache is not None:
            return _local_browser_profile_cache

        browser_path = _find_sentinel_browser_executable()
        if not browser_path:
            return None

        try:
            ps_path = browser_path.replace("'", "''")
            ps_script = f"(Get-Item -LiteralPath '{ps_path}').VersionInfo.ProductVersion"
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_script],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                check=False,
            )
            version = (result.stdout or "").strip()
            if result.returncode != 0 or not version:
                return None
            major = int(version.split(".", 1)[0])
            sec_ch_ua = (
                f'"Google Chrome";v="{major}", '
                f'"Chromium";v="{major}", '
                f'"Not_A Brand";v="99"'
            )
            _local_browser_profile_cache = ("chrome", version, sec_ch_ua)
            return _local_browser_profile_cache
        except Exception:
            return None


def _random_chrome_profile():
    if _experiment2_enabled:
        profile = _experiment2_profile_config()
        return (
            profile["impersonate"],
            profile["user_agent"],
            profile["sec_ch_ua"],
        )
    detected = _detect_local_browser_profile()
    if detected:
        impersonate, full_ver, sec_ch_ua = detected
        ua = (
            f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            f"AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{full_ver} Safari/537.36"
        )
        return impersonate, ua, sec_ch_ua

    profile = random.choice(_CHROME_PROFILES)
    major = profile["major"]
    build = profile["build"]
    patch = random.randint(*profile["patch_range"])
    full_ver = f"{major}.0.{build}.{patch}"
    ua = (
        f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        f"AppleWebKit/537.36 (KHTML, like Gecko) "
        f"Chrome/{full_ver} Safari/537.36"
    )
    return profile["impersonate"], ua, profile["sec_ch_ua"]


def _record_experiment2_branch(
    *,
    email: str,
    did: str,
    page: str,
    continue_url: str,
    result: str,
) -> None:
    if not _experiment2_enabled:
        return
    domain = _extract_email_domain(email)
    run_ctx = _current_run_context()
    if run_ctx is not None:
        run_ctx["branch_count"] = int(run_ctx.get("branch_count") or 0) + 1
        run_ctx["email"] = email
        run_ctx["domain"] = domain
        run_ctx["did"] = did
        run_ctx["last_branch_page"] = page
        run_ctx["last_branch_continue_url"] = continue_url
        run_ctx["last_branch_result"] = result
        _append_run_context_value("branch_results", result)
        _append_run_context_value("branch_domains", domain)
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "run_id": run_ctx.get("run_id") if run_ctx else None,
        "worker_slot": run_ctx.get("worker_slot") if run_ctx else None,
        "attempt": run_ctx.get("attempts") if run_ctx else None,
        "email": email,
        "domain": domain,
        "did": did,
        "page": page,
        "continue_url": continue_url,
        "result": result,
        "profile": _experiment2_profile_name,
        "family": _experiment2_force_family,
        "accept_language": _runtime_accept_language("", ""),
        "beta_enabled": _beta_enabled,
        "beta2_enabled": _beta2_enabled,
        "fresh_cloudvxz": _experiment2_fresh_cloudvxz,
        "low_mode": _low_mode,
        "browser_mode": _browser_mode,
    }
    _append_jsonl_line(EXPERIMENT_CREATE_ACCOUNT_BRANCH_FILE, payload, lock=_experiment_branch_lock)


def _record_experiment2_run_result(
    *,
    status: str,
    reason: str = "",
    token_saved: bool = False,
    error: str = "",
) -> None:
    if not (_experiment2_enabled or _beta_enabled or _beta2_enabled):
        return
    run_ctx = _current_run_context() or {}
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "run_id": run_ctx.get("run_id"),
        "worker_slot": run_ctx.get("worker_slot"),
        "started_at": run_ctx.get("started_at"),
        "attempts": run_ctx.get("attempts") or 0,
        "status": status,
        "reason": reason,
        "token_saved": bool(token_saved),
        "error": error,
        "email": run_ctx.get("email") or "",
        "domain": run_ctx.get("domain") or "",
        "did": run_ctx.get("did") or "",
        "branch_count": int(run_ctx.get("branch_count") or 0),
        "branch_results": _dedupe_keep_order([
            str(item).strip() for item in (run_ctx.get("branch_results") or []) if str(item).strip()
        ]),
        "branch_domains": _dedupe_keep_order([
            str(item).strip() for item in (run_ctx.get("branch_domains") or []) if str(item).strip()
        ]),
        "last_branch_result": run_ctx.get("last_branch_result") or "",
        "last_branch_page": run_ctx.get("last_branch_page") or "",
        "last_branch_continue_url": run_ctx.get("last_branch_continue_url") or "",
        "profile": _experiment2_profile_name,
        "family": _experiment2_force_family,
        "accept_language": _runtime_accept_language("", ""),
        "managed_domains": _managed_target_domains(),
        "beta_enabled": _beta_enabled,
        "beta2_enabled": _beta2_enabled,
        "fresh_cloudvxz": _experiment2_fresh_cloudvxz,
        "low_mode": _low_mode,
    }
    _append_jsonl_line(EXPERIMENT2_RUN_RESULT_FILE, payload, lock=_experiment_branch_lock)


def _experiment2_domain_scores(domains: List[str]) -> Dict[str, int]:
    candidates = [str(item).strip().lower() for item in domains if str(item).strip()]
    if not candidates:
        return {}
    allowed = set(candidates)
    scores: Dict[str, int] = {domain: 0 for domain in candidates}

    try:
        if os.path.exists(EXPERIMENT2_RUN_RESULT_FILE):
            run_rows: Dict[str, List[Dict[str, Any]]] = {domain: [] for domain in candidates}
            with open(EXPERIMENT2_RUN_RESULT_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        item = json.loads(line)
                    except Exception:
                        continue
                    domain = str(item.get("domain") or "").strip().lower()
                    if domain not in allowed:
                        continue
                    item_low_mode = bool(item.get("low_mode"))
                    if item_low_mode != _low_mode:
                        continue
                    if isinstance(run_rows.get(domain), list):
                        run_rows[domain].append(item)

            for domain, items in run_rows.items():
                for item in items:
                    status = str(item.get("status") or "").strip().lower()
                    reason = str(item.get("reason") or "").strip().lower()
                    branch = str(item.get("last_branch_result") or "").strip().lower()
                    if status == "success" or reason == "token_saved":
                        scores[domain] += 42
                    elif reason == "phone_gate" or branch == "phone_gate":
                        scores[domain] -= 9 if _low_mode else 5
                    elif reason == "signup_http_403":
                        scores[domain] -= 18 if _low_mode else 10
                    elif reason == "invalid_auth_step":
                        scores[domain] -= 14 if _low_mode else 8
                    elif reason.startswith("otp_timeout"):
                        scores[domain] -= 6
                    elif reason == "no_token":
                        scores[domain] -= 4
                    else:
                        scores[domain] -= 3
                recent_items = items[-4:]
                for item in recent_items:
                    status = str(item.get("status") or "").strip().lower()
                    reason = str(item.get("reason") or "").strip().lower()
                    if status == "success" or reason == "token_saved":
                        scores[domain] += 12 if _low_mode else 6
                    elif reason == "phone_gate":
                        scores[domain] -= 3 if _low_mode else 1

        if os.path.exists(EXPERIMENT_CREATE_ACCOUNT_BRANCH_FILE):
            with open(EXPERIMENT_CREATE_ACCOUNT_BRANCH_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        item = json.loads(line)
                    except Exception:
                        continue
                    domain = str(item.get("domain") or "").strip().lower()
                    if domain not in allowed:
                        continue
                    if "low_mode" in item and bool(item.get("low_mode")) != _low_mode:
                        continue
                    result = str(item.get("result") or "").strip().lower()
                    if result == "consent_path":
                        scores[domain] += 10 if _low_mode else 14
                    elif result == "phone_gate":
                        scores[domain] -= 3 if _low_mode else 4
                    elif result == "no_email":
                        scores[domain] -= 2
                    else:
                        scores[domain] -= 1
    except Exception:
        return scores

    return scores


def _pick_experiment2_domain(domains: List[str]) -> str:
    ranked = [str(item).strip().lower() for item in domains if str(item).strip()]
    if not ranked:
        return ""
    scores = _experiment2_domain_scores(ranked)
    ranked.sort(key=lambda domain: scores.get(domain, 0), reverse=True)
    if _low_mode and ranked:
        best = scores.get(ranked[0], 0)
        cutoff = best - 12
        narrowed = [domain for domain in ranked if scores.get(domain, 0) >= cutoff]
        if narrowed:
            ranked = narrowed
    floor = min(scores.get(domain, 0) for domain in ranked)
    weights: List[float] = []
    for index, domain in enumerate(ranked):
        weight = max(1.0, float(scores.get(domain, 0) - floor + 3))
        if _low_mode:
            weight /= 1.0 + index * 0.24
            if scores.get(domain, 0) < 0:
                weight *= 0.45
        else:
            weight /= 1.0 + index * 0.08
        weights.append(weight)
    return random.choices(ranked, weights=weights, k=1)[0]


# ==========================================
# V2RayN 本地代理准备
# ==========================================


def _prepare_v2rayn_proxy(proxy: Optional[str]) -> Optional[str]:
    raw_proxy = "" if proxy is None else str(proxy).strip()
    auto_mode = not raw_proxy or raw_proxy.lower() == "auto"
    candidates = _candidate_proxy_urls(proxy)
    if not candidates:
        print("[V2RayN] proxy disabled; using direct connection")
        return None

    first_success = None
    for candidate in candidates:
        try:
            trace = _probe_proxy_trace(candidate)
            loc = trace.get("loc") or "UNKNOWN"
            ip = trace.get("ip") or "UNKNOWN"
            print(f"[V2RayN] probe {candidate} -> loc={loc}, ip={ip}")
            if first_success is None:
                first_success = candidate
            if loc not in _BLOCKED_PROXY_LOCS:
                print(f"[V2RayN] using local proxy: {candidate}")
                return candidate
        except Exception as e:
            print(f"[V2RayN] probe failed {candidate}: {e}")

    if first_success:
        print("[V2RayN] 10808 is reachable but exit loc is still CN/HK; switch node in v2rayN")
        return first_success

    if auto_mode:
        print("[V2RayN] auto scan found no reachable local proxy; using direct connection")
        return None

    fallback = _normalize_proxy_url(proxy)
    if fallback:
        print(f"[V2RayN] all probes failed; fallback to configured proxy: {fallback}")
        return fallback
    print("[V2RayN] no proxy available; using direct connection")
    return None


def _prompt_proxy_value(default_proxy: str) -> str:
    default_display = "auto" if default_proxy else "direct"
    try:
        user_input = input(
            f"代理端口/地址（回车使用 {default_display}，可填 7890 / 10808 / 127.0.0.1:7890 / socks5h://127.0.0.1:10808 / direct）: "
        ).strip()
    except EOFError:
        return default_proxy
    if not user_input:
        return default_proxy
    lowered = user_input.lower()
    if lowered in _PROXY_DIRECT_VALUES:
        return "direct"
    return user_input


# ==========================================
# 密码登录获取 token（跳过手机验证后使用）
# ==========================================


def _login_for_token(
    email: str,
    password: str,
    dev_token: str,
    proxies: Any,
    impersonate: str,
    user_agent: str,
    sec_ch_ua: str,
    force_standard_oauth: bool = False,
) -> Optional[str]:
    """用已注册的邮箱和密码，通过登录流程获取 token"""
    print(f"[*] 开始用密码登录: {email}")
    time.sleep(random.uniform(1.0, 2.5))

    s = requests.Session(proxies=proxies, impersonate=impersonate)

    try:
        # 1. 发起新的 OAuth 登录流程
        if _experiment_enabled and not force_standard_oauth:
            _chatgpt_experiment_warm(
                s,
                user_agent=user_agent,
                sec_ch_ua=sec_ch_ua,
                label="login",
            )
        oauth = (
            None
            if force_standard_oauth
            else _generate_chatgpt_experiment_oauth_start(
                s,
                user_agent=user_agent,
                sec_ch_ua=sec_ch_ua,
                label="login",
            )
        ) or generate_oauth_url(prompt=None if force_standard_oauth else "login")
        s.get(oauth.auth_url, timeout=15)
        did = _read_cookie_value(
            s,
            "oai-did",
            preferred_domains=["auth.openai.com", "openai.com", "chatgpt.com"],
        )

        def _sentinel(flow: str = SENTINEL_FLOW_SIGNUP_EMAIL) -> str:
            sdk_token = _fetch_sentinel_sdk_token(
                flow=flow,
                user_agent=user_agent,
                proxy_url=_extract_proxy_url_from_proxies(proxies),
            )
            if sdk_token:
                return sdk_token
            rj = _fetch_sentinel_payload(
                did=did,
                flow=flow,
                user_agent=user_agent,
                sec_ch_ua=sec_ch_ua,
                proxies=proxies,
                impersonate=impersonate,
                label="login-sentinel",
            )
            return _build_sentinel_fallback_token(
                did=did,
                flow=flow,
                user_agent=user_agent,
                req_json=rj,
            )

        def _headers(referer: str, sentinel: str) -> dict:
            return {
                "referer": referer,
                "accept": "application/json",
                "content-type": "application/json",
                "openai-sentinel-token": sentinel,
                "user-agent": user_agent,
                "sec-ch-ua": sec_ch_ua,
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
            }

        # 2. 提交邮箱（登录模式）
        sentinel = _sentinel(SENTINEL_FLOW_SIGNUP_EMAIL)
        login_body = json.dumps(
            {"username": {"value": email, "kind": "email"}, "screen_hint": "login"}
        )
        login_resp = _request_with_retries(
            lambda: s.post(
                "https://auth.openai.com/api/accounts/authorize/continue",
                headers=_headers("https://auth.openai.com/sign-in", sentinel),
                data=login_body,
            ),
            label="login-email",
        )
        print(f"[*] 登录提交邮箱状态: {login_resp.status_code}")
        if login_resp.status_code != 200:
            print(f"[Error] 登录提交邮箱失败: {login_resp.text[:200]}")
            return None

        login_data = login_resp.json() if login_resp.text.strip() else {}
        _log_page_transition("login-email", login_data)
        cont_url = login_data.get("continue_url", "")
        login_page_type = _extract_page_type(login_data)
        if cont_url:
            s.get(cont_url, headers={"referer": "https://auth.openai.com/sign-in"}, allow_redirects=True)
        elif login_page_type:
            page_url = _page_type_to_url(login_page_type)
            if page_url:
                s.get(page_url, headers={"referer": "https://auth.openai.com/sign-in"}, allow_redirects=True)

        # 3. 提交密码
        time.sleep(random.uniform(0.5, 1.5))
        sentinel = _sentinel(flow=SENTINEL_FLOW_PASSWORD_VERIFY)
        pwd_resp = _request_with_retries(
            lambda: s.post(
                "https://auth.openai.com/api/accounts/password/verify",
                headers=_headers("https://auth.openai.com/log-in/password", sentinel),
                data=json.dumps({"password": password}),
                timeout=15,
            ),
            label="login-password",
        )
        print(f"[*] 登录提交密码状态: {pwd_resp.status_code}")

        if pwd_resp.status_code != 200:
            print(f"[Error] 登录密码验证失败: {pwd_resp.text[:200]}")
            print(f"[Info] 邮箱: {email} 密码: {password} (可手动登录)")
            return None

        pwd_data = pwd_resp.json() if pwd_resp.text.strip() else {}
        _log_page_transition("login-password", pwd_data)
        pwd_continue = pwd_data.get("continue_url", "")
        pwd_page_type = (pwd_data.get("page") or {}).get("type", "") if isinstance(pwd_data.get("page"), dict) else ""
        pwd_page_url = _page_type_to_url(pwd_page_type)

        # 4a. 如果需要邮箱 OTP 验证
        if "email" in pwd_page_type.lower() and "otp" in pwd_page_type.lower():
            print("[*] 登录需要邮箱 OTP 验证...")
            if pwd_continue:
                s.get(pwd_continue, headers={"referer": "https://auth.openai.com/log-in/password"}, allow_redirects=True)
            elif pwd_page_url:
                s.get(pwd_page_url, headers={"referer": "https://auth.openai.com/log-in/password"}, allow_redirects=True)
            otp_code = _fetch_login_email_otp(
                session=s,
                dev_token=dev_token,
                email=email,
                proxies=proxies,
                get_sentinel=_sentinel,
                build_headers=_headers,
            )
            if not otp_code:
                print("[Error] 登录 OTP 未收到验证码")
                print(f"[Info] 邮箱: {email} 密码: {password} (可手动登录)")
                return None
            sentinel = _sentinel(flow=SENTINEL_FLOW_EMAIL_OTP)
            otp_resp = _request_with_retries(
                lambda: s.post(
                    "https://auth.openai.com/api/accounts/email-otp/validate",
                    headers=_headers("https://auth.openai.com/email-verification", sentinel),
                    data=json.dumps({"code": otp_code}),
                    timeout=15,
                ),
                label="login-email-otp",
            )
            print(f"[*] 登录 OTP 验证状态: {otp_resp.status_code}")
            if otp_resp.status_code != 200:
                otp_body = otp_resp.text[:400]
                if otp_resp.status_code == 401 and "wrong_email_otp_code" in otp_body:
                    if dev_token.startswith("skymail:"):
                        _skymail_remember_code(email, otp_code)
                    retry_code = _fetch_login_email_otp(
                        session=s,
                        dev_token=dev_token,
                        email=email,
                        proxies=proxies,
                        get_sentinel=_sentinel,
                        build_headers=_headers,
                        blocked_codes={otp_code},
                    )
                    if retry_code:
                        sentinel = _sentinel(flow=SENTINEL_FLOW_EMAIL_OTP)
                        otp_resp = _request_with_retries(
                            lambda: s.post(
                                "https://auth.openai.com/api/accounts/email-otp/validate",
                                headers=_headers("https://auth.openai.com/email-verification", sentinel),
                                data=json.dumps({"code": retry_code}),
                                timeout=15,
                            ),
                            label="login-email-otp-retry",
                        )
                        print(f"[*] 登录 OTP 重试验证状态: {otp_resp.status_code}")
                if otp_resp.status_code != 200:
                    print(f"[Error] 登录 OTP 验证失败: {otp_resp.text[:200]}")
                    print(f"[Info] 邮箱: {email} 密码: {password} (可手动登录)")
                    return None
            otp_data = otp_resp.json() if otp_resp.text.strip() else {}
            _log_page_transition("login-email-otp", otp_data)
            otp_continue = otp_data.get("continue_url", "")
            otp_page_type = _extract_page_type(otp_data)
            otp_page_url = _page_type_to_url(otp_page_type)
            if otp_continue:
                s.get(otp_continue, headers={"referer": "https://auth.openai.com/email-verification"}, allow_redirects=False)
                pwd_continue = otp_continue
            elif otp_page_url:
                s.get(otp_page_url, headers={"referer": "https://auth.openai.com/email-verification"}, allow_redirects=True)
            pwd_data = otp_data
            pwd_page_type = otp_page_type
            if "phone" in otp_page_type.lower() or "phone" in otp_continue.lower():
                experiment_callback = _chatgpt_experiment_probe_callback(
                    session=s,
                    oauth=oauth,
                    proxies=proxies,
                    referer="https://chatgpt.com/auth/login",
                    label="login-chatgpt-probe",
                    user_agent=user_agent,
                    sec_ch_ua=sec_ch_ua,
                    email=email,
                    password=password,
                    dev_token=dev_token,
                    impersonate=impersonate,
                )
                if experiment_callback:
                    return experiment_callback
                if _experiment_enabled:
                    print("[*] login fallback reached add_phone; stop this recovery path")
                    return None
                print("[*] login fallback reached add_phone; continue legacy workspace recovery")

        # 4b. 跟随重定向链获取 OAuth callback
        if pwd_continue:
            callback_json = _follow_redirect_chain_for_callback(
                session=s,
                start_url=pwd_continue,
                oauth=oauth,
                proxies=proxies,
                referer="https://auth.openai.com/log-in/password",
                max_hops=15,
                label="login-redirect-chain",
            )
            if callback_json:
                print("[*] 登录流程获取到 OAuth callback!")
                return callback_json
        elif pwd_page_url:
            callback_json = _follow_redirect_chain_for_callback(
                session=s,
                start_url=pwd_page_url,
                oauth=oauth,
                proxies=proxies,
                referer="https://auth.openai.com/log-in/password",
                max_hops=15,
                label="login-page-type-chain",
            )
            if callback_json:
                print(f"[*] 登录流程通过 page.type 获取到 OAuth callback: {pwd_page_type}")
                return callback_json

        # 5. 如果重定向没直接拿到 callback，尝试从 cookie / API 提取 workspace 继续
        workspaces = []
        session_state = _extract_auth_session_metadata(s)
        session_orgs = session_state.get("orgs") if isinstance(session_state.get("orgs"), list) else []
        if session_state.get("workspaces"):
            workspaces = session_state["workspaces"]

        if not workspaces:
            dump_state = _fetch_client_auth_session_dump(s)
            if dump_state.get("workspaces"):
                workspaces = dump_state["workspaces"]
            if not session_orgs and isinstance(dump_state.get("orgs"), list):
                session_orgs = dump_state.get("orgs") or []

        if not workspaces:
            print("[*] 登录流程 cookie 中无 workspace，尝试通过 API 获取...")
            try:
                sentinel = _sentinel(SENTINEL_FLOW_WORKSPACE)
                ws_resp = _request_with_retries(
                    lambda: s.get(
                        "https://auth.openai.com/api/accounts/workspaces",
                        headers=_headers("https://auth.openai.com/", sentinel),
                        timeout=15,
                    ),
                    label="login-fetch-workspaces",
                )
                if ws_resp.status_code == 200:
                    ws_data = ws_resp.json() if ws_resp.text.strip() else {}
                    if isinstance(ws_data, list):
                        workspaces = ws_data
                    elif isinstance(ws_data, dict):
                        workspaces = ws_data.get("workspaces") or ws_data.get("data") or []
                    print(f"[*] 登录流程 API 返回 workspace 数量: {len(workspaces)}")
            except Exception as e:
                print(f"[Warn] 登录流程获取 workspace API 失败: {e}")

        if not workspaces and session_orgs:
            org_callback = _select_first_org_project(
                session=s,
                orgs=session_orgs,
                oauth=oauth,
                proxies=proxies,
                referer="https://auth.openai.com/sign-in-with-chatgpt/codex/organization",
            )
            if org_callback:
                print("[*] ?餃?瘚??? session org select ?瑕???OAuth callback!")
                return org_callback

        if not workspaces and pwd_continue:
            print("[*] 登录流程尝试直接跳过 workspace 选择...")
            callback_json = _follow_redirect_chain_for_callback(
                session=s,
                start_url=pwd_continue,
                oauth=oauth,
                proxies=proxies,
                referer="https://auth.openai.com/log-in/password",
                max_hops=10,
                label="login-skip-workspace",
            )
            if callback_json:
                print("[*] 登录流程直接获取到 OAuth callback!")
                return callback_json

        if not workspaces:
            print("[*] 登录流程探测 codex consent/workspace 页面...")
            candidate_pages = []
            for candidate in candidate_pages:
                callback_json = _follow_redirect_chain_for_callback(
                    session=s,
                    start_url=candidate,
                    oauth=oauth,
                    proxies=proxies,
                    referer="https://auth.openai.com/log-in",
                    max_hops=10,
                    label="login-route-probe",
                )
                if callback_json:
                    print(f"[*] 登录流程通过页面探测拿到 OAuth callback: {candidate}")
                    return callback_json

            dump_state = _fetch_client_auth_session_dump(s)
            if dump_state.get("workspaces"):
                workspaces = dump_state["workspaces"]

        if workspaces:
            workspace_id = str((workspaces[0] or {}).get("id") or "").strip() if workspaces else ""
            if workspace_id:
                print(f"[*] 登录成功，workspace_id={workspace_id}")
                sentinel = _sentinel(SENTINEL_FLOW_CODEX_CONSENT)
                sel_resp = _request_with_retries(
                    lambda: s.post(
                        "https://auth.openai.com/api/accounts/workspace/select",
                        headers=_headers(
                            "https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
                            sentinel,
                        ),
                        data=json.dumps({"workspace_id": workspace_id}),
                    ),
                    label="login-select-workspace",
                )
                if sel_resp.status_code == 200:
                    sel_data = sel_resp.json() if sel_resp.text.strip() else {}
                    org_callback = _select_first_org_project(
                        session=s,
                        orgs=_extract_orgs(sel_data),
                        oauth=oauth,
                        proxies=proxies,
                        referer="https://auth.openai.com/sign-in-with-chatgpt/codex/organization",
                    )
                    if org_callback:
                        print("[*] 登录流程通过 organization select 获取到 OAuth callback!")
                        return org_callback
                    sel_continue = str((sel_data.get("continue_url") or "")).strip()
                    if sel_continue:
                        callback_json = _follow_redirect_chain_for_callback(
                            session=s,
                            start_url=sel_continue,
                            oauth=oauth,
                            proxies=proxies,
                            referer="https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
                            max_hops=10,
                            label="login-workspace-select-chain",
                        )
                        if callback_json:
                            print("[*] 登录流程获取到 OAuth callback!")
                            return callback_json

        print("[Error] 登录流程未能获取到 token")
        return None

    except Exception as e:
        print(f"[Error] 登录流程异常: {e}")
        return None


# ==========================================
# 核心注册逻辑
# ==========================================


def run(
    proxy: Optional[str],
    blacklist_retry_left: int = MAX_BLACKLIST_RETRY_PER_WORKER,
) -> Optional[str]:

    proxy = None if proxy is None else _normalize_proxy_url(proxy)
    proxies = _build_proxies(proxy)
    print(f"[Run] build={SCRIPT_BUILD} proxy={proxy or 'direct'}")

    _impersonate, _user_agent, _sec_ch_ua = _random_chrome_profile()
    _accept_language = _runtime_accept_language(_impersonate, _user_agent)
    s = requests.Session(proxies=proxies, impersonate=_impersonate)
    try:
        s.headers.update({"Accept-Language": _accept_language})
    except Exception:
        pass
    if _experiment2_enabled:
        print(
            "[*] experiment2 runtime: "
            f"profile={_experiment2_profile_name} family={_experiment2_force_family} "
            f"lang={_accept_language}"
        )

    try:
        trace = _request_with_retries(
            lambda: s.get(_PROXY_TRACE_URL, timeout=10),
            label="proxy-trace",
        )
        trace = trace.text
        loc_re = re.search(r"^loc=(.+)$", trace, re.MULTILINE)
        loc = loc_re.group(1) if loc_re else None
        print(f"[Net] trace loc={loc}")
        if loc == "CN" or loc == "HK":
            raise RuntimeError("proxy exit location is not supported")
    except Exception as e:
        print(f"[Error] network check failed: {e}")
        return None

    email, dev_token = get_email_and_token(proxies)
    if not email or not dev_token:
        return None
    _update_run_context(
        email=email,
        domain=_extract_email_domain(email),
    )
    print(f"[*] 成功获取临时邮箱: {email}")

    if _worker_count_hint > 1:
        auth_jitter = random.uniform(0.6, min(6.0, 1.3 * _worker_count_hint))
        print(f"[*] auth start jitter {auth_jitter:.1f}s")
        time.sleep(auth_jitter)

    try:
        if _experiment_enabled:
            _chatgpt_experiment_warm(
                s,
                user_agent=_user_agent,
                sec_ch_ua=_sec_ch_ua,
                label="signup",
            )
        oauth = _generate_chatgpt_experiment_oauth_start(
            s,
            user_agent=_user_agent,
            sec_ch_ua=_sec_ch_ua,
            label="signup",
        ) or generate_oauth_url()
        url = oauth.auth_url
        resp = _request_with_retries(
            lambda: s.get(url, timeout=15),
            label="oauth-entry",
        )
        did = _read_cookie_value(
            s,
            "oai-did",
            preferred_domains=["auth.openai.com", "openai.com", "chatgpt.com"],
        )
        print(f"[*] Device ID: {did}")
        _update_run_context(did=did)

        def _get_sentinel(flow: str = SENTINEL_FLOW_SIGNUP_EMAIL) -> str:
            """获取一个新的 sentinel token 组合字符串"""
            sdk_token = _fetch_sentinel_sdk_token(
                flow=flow,
                user_agent=_user_agent,
                proxy_url=_extract_proxy_url_from_proxies(proxies),
            )
            if sdk_token:
                return sdk_token
            rj = _fetch_sentinel_payload(
                did=did,
                flow=flow,
                user_agent=_user_agent,
                sec_ch_ua=_sec_ch_ua,
                proxies=proxies,
                impersonate=_impersonate,
                label="signup-sentinel",
            )
            return _build_sentinel_fallback_token(
                did=did,
                flow=flow,
                user_agent=_user_agent,
                req_json=rj,
            )

        def _auth_headers(referer: str, sentinel: str) -> dict:
            return {
                "referer": referer,
                "accept": "application/json",
                "content-type": "application/json",
                "openai-sentinel-token": sentinel,
                "user-agent": _user_agent,
                "sec-ch-ua": _sec_ch_ua,
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
            }

        # --- 1. 提交注册邮箱 ---
        time.sleep(random.uniform(0.8, 2.0))
        signup_body = json.dumps(
            {"username": {"value": email, "kind": "email"}, "screen_hint": "signup"}
        )
        sentinel = _get_sentinel(SENTINEL_FLOW_SIGNUP_EMAIL)
        signup_resp = _request_with_retries(
            lambda: s.post(
                "https://auth.openai.com/api/accounts/authorize/continue",
                headers=_auth_headers("https://auth.openai.com/create-account", sentinel),
                data=signup_body,
            ),
            label="signup-email",
        )
        _raise_if_blacklistable_email_error(signup_resp, email, stage="signup_email")
        print(f"[*] 提交注册邮箱状态: {signup_resp.status_code}")
        if signup_resp.status_code != 200:
            _update_run_context(
                last_branch_result=_response_error_reason(
                    signup_resp,
                    fallback=f"signup_http_{signup_resp.status_code}",
                ),
                last_branch_page="authorize_continue",
                last_branch_continue_url="https://auth.openai.com/api/accounts/authorize/continue",
            )
            print(f"[Error] 提交邮箱失败: {signup_resp.text}")
            return None

        signup_data = signup_resp.json() if signup_resp.text.strip() else {}
        continue_url = signup_data.get("continue_url", "")

        # GET continue_url 推进服务器状态到密码页
        if continue_url:
            s.get(
                continue_url,
                headers={
                    "referer": "https://auth.openai.com/create-account",
                    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                },
                allow_redirects=True,
            )

        # --- 2. 设置密码 ---
        # 端点: /api/accounts/user/register (不是 authorize/continue!)
        # Sentinel flow: create_account_password
        time.sleep(random.uniform(0.5, 1.5))
        password = secrets.token_urlsafe(18)
        sentinel = _get_sentinel(flow=SENTINEL_FLOW_CREATE_PASSWORD)
        pwd_body = json.dumps({"password": password, "username": email})
        pwd_resp = _request_with_retries(
            lambda: s.post(
                "https://auth.openai.com/api/accounts/user/register",
                headers=_auth_headers(
                    "https://auth.openai.com/create-account/password", sentinel
                ),
                data=pwd_body,
            ),
            label="signup-password",
        )
        _raise_if_blacklistable_email_error(pwd_resp, email, stage="create_password")
        print(f"[*] 设置密码状态: {pwd_resp.status_code}")
        if pwd_resp.status_code != 200:
            print(f"[Error] 设置密码失败: {pwd_resp.text}")
            return None

        pwd_data = pwd_resp.json() if pwd_resp.text.strip() else {}
        pwd_page_type = (pwd_data.get("page") or {}).get("type", "")
        pwd_continue = pwd_data.get("continue_url", "")

        # --- 3. 邮箱验证（如需要）---
        if "email" in pwd_page_type.lower() or "verify" in pwd_page_type.lower() or "otp" in pwd_page_type.lower():
            if pwd_continue:
                s.get(pwd_continue, headers={"referer": "https://auth.openai.com/create-account/password"}, allow_redirects=True)
            _otp_seen = set()  # 跨重试共享的已见消息 ID
            otp_code = get_oai_code(dev_token, email, proxies, seen_msg_ids=_otp_seen)
            if otp_code:
                time.sleep(random.uniform(0.5, 1.2))
                sentinel = _get_sentinel(SENTINEL_FLOW_EMAIL_OTP)
                otp_body = json.dumps({"code": otp_code})
                otp_resp = _request_with_retries(
                    lambda: s.post(
                        "https://auth.openai.com/api/accounts/email-otp/validate",
                        headers=_auth_headers(
                            "https://auth.openai.com/email-verification", sentinel
                        ),
                        data=otp_body,
                    ),
                    label="email-otp-validate",
                )
                print(f"[*] 邮箱验证状态: {otp_resp.status_code}")
                if otp_resp.status_code != 200:
                    print(f"[Warn] OTP 验证失败，尝试重发: {otp_resp.text[:120]}")
                    # 重发 OTP
                    try:
                        _request_with_retries(
                            lambda: s.post(
                                "https://auth.openai.com/api/accounts/email-otp/resend",
                                headers=_auth_headers(
                                    "https://auth.openai.com/email-verification",
                                    _get_sentinel(SENTINEL_FLOW_EMAIL_OTP),
                                ),
                                data="{}",
                            ),
                            label="email-otp-resend",
                        )
                    except Exception:
                        pass
                    time.sleep(random.uniform(4.0, 7.0))
                    otp_code2 = get_oai_code(dev_token, email, proxies, seen_msg_ids=_otp_seen)
                    if not otp_code2:
                        _update_run_context(
                            last_branch_result="otp_timeout_after_resend",
                            last_branch_page="email_otp_verification",
                            last_branch_continue_url="https://auth.openai.com/email-verification",
                        )
                        print("[Error] 重发后仍未收到验证码")
                        return None
                    sentinel = _get_sentinel(SENTINEL_FLOW_EMAIL_OTP)
                    otp_resp = _request_with_retries(
                        lambda: s.post(
                            "https://auth.openai.com/api/accounts/email-otp/validate",
                            headers=_auth_headers(
                                "https://auth.openai.com/email-verification", sentinel
                            ),
                            data=json.dumps({"code": otp_code2}),
                        ),
                        label="email-otp-validate-retry",
                    )
                    print(f"[*] 重试邮箱验证状态: {otp_resp.status_code}")
                    if otp_resp.status_code != 200:
                        _update_run_context(
                            last_branch_result=_response_error_reason(
                                otp_resp,
                                fallback=f"otp_validate_http_{otp_resp.status_code}",
                            ),
                            last_branch_page="email_otp_verification",
                            last_branch_continue_url="https://auth.openai.com/api/accounts/email-otp/validate",
                        )
                        print(f"[Error] 重试邮箱验证失败: {otp_resp.text}")
                        return None
                # 跟踪 OTP 验证后的 continue_url
                otp_data = otp_resp.json() if otp_resp.text.strip() else {}
                otp_continue = otp_data.get("continue_url", "")
                if otp_continue:
                    s.get(otp_continue, headers={"referer": "https://auth.openai.com/email-verification"}, allow_redirects=True)
            else:
                _update_run_context(
                    last_branch_result="otp_timeout",
                    last_branch_page="email_otp_verification",
                    last_branch_continue_url="https://auth.openai.com/email-verification",
                )
                print("[Error] 需要邮箱验证但未收到验证码")
                return None
        else:
            print("[*] 无需邮箱验证，直接继续")

        # 如果密码步骤返回了 continue_url，先 GET 推进状态
        if pwd_continue and "email" not in pwd_page_type.lower():
            s.get(pwd_continue, headers={"referer": "https://auth.openai.com/create-account/password"}, allow_redirects=True)

        # --- 4. 创建账户（姓名、生日）---
        sentinel = _get_sentinel(SENTINEL_FLOW_ABOUT_YOU)
        # 用随机真实姓名和随机生日
        first_names = ["James", "Mary", "John", "Emma", "Robert", "Sarah", "David", "Laura", "Michael", "Anna"]
        last_names = ["Smith", "Brown", "Wilson", "Taylor", "Clark", "Hall", "Lewis", "Young", "King", "Green"]
        rand_name = f"{random.choice(first_names)} {random.choice(last_names)}"
        rand_year = random.randint(1990, 2004)
        rand_month = random.randint(1, 12)
        rand_day = random.randint(1, 28)
        rand_bday = f"{rand_year}-{rand_month:02d}-{rand_day:02d}"
        create_account_body = json.dumps({"name": rand_name, "birthdate": rand_bday})
        create_account_resp = _request_with_retries(
            lambda: s.post(
                "https://auth.openai.com/api/accounts/create_account",
                headers=_auth_headers("https://auth.openai.com/about-you", sentinel),
                data=create_account_body,
            ),
            label="create-account",
        )
        _raise_if_blacklistable_email_error(create_account_resp, email, stage="create_account")
        create_account_status = create_account_resp.status_code

        if create_account_status != 200:
            print(f"[Error] 账户创建失败: {create_account_resp.text[:200]}")
            return None

        ca_data = create_account_resp.json() if create_account_resp.text.strip() else {}
        ca_continue = ca_data.get("continue_url", "")
        ca_page_type = (ca_data.get("page") or {}).get("type", "") if isinstance(ca_data.get("page"), dict) else ""
        phone_required = "phone" in ca_page_type.lower() or "phone" in ca_continue.lower()
        _record_experiment2_branch(
            email=email,
            did=did,
            page=ca_page_type,
            continue_url=ca_continue,
            result="consent_path" if "consent" in ca_page_type.lower() or "consent" in ca_continue.lower() else ("phone_gate" if phone_required else "other"),
        )
        if phone_required and not _experiment_enabled:
            if _experiment2_enabled:
                print("[*] experiment2 stops at add_phone to keep managed branch data clean")
                return None
            print("[*] add_phone hit during signup; fallback to standard password login recovery")
            return _login_for_token(
                email, password, dev_token, proxies, _impersonate, _user_agent, _sec_ch_ua
            )

        def _fallback_login_for_token(reason: str) -> Optional[str]:
            if _experiment2_enabled:
                print(f"[*] experiment2 skips fallback: {reason}")
                return None
            if phone_required and not _experiment_enabled:
                print(f"[*] fallback to password login for token after add_phone: {reason}")
                return _login_for_token(
                    email, password, dev_token, proxies, _impersonate, _user_agent, _sec_ch_ua
                )
            if _experiment_enabled and phone_required:
                print(f"[*] experiment mode skips legacy fallback after add_phone: {reason}")
                return None
            if phone_required and reason in {"missing workspaces", "missing workspace id", "final callback missing"}:
                if reason in {"missing workspace id", "final callback missing"} and not _should_prefer_direct_success(email):
                    print(f"[*] skip password login fallback after add_phone: {reason}")
                    return None
                if not _should_prefer_direct_success(email):
                    print(f"[*] skip password login fallback after add_phone: {reason}")
                    return None
            print(f"[*] fallback to password login for token: {reason}")
            return _login_for_token(
                email, password, dev_token, proxies, _impersonate, _user_agent, _sec_ch_ua
            )

        # --- 处理手机号验证（add_phone）---
        def _enqueue_async_account_creation() -> Optional[str]:
            payload = {
                "username": {"kind": "email", "value": email},
                "name": rand_name,
                "birthdate": rand_bday,
                "account_creation_app": "chat",
            }
            try:
                _normalize_chatgpt_callback_cookie(s)
                resp = _request_with_retries(
                    lambda: s.post(
                        "https://auth.openai.com/api/accounts/enqueue_async_account_creation",
                        headers={
                            "referer": "https://auth.openai.com/create-account-later",
                            "accept": "application/json",
                            "content-type": "application/json",
                            "user-agent": _user_agent,
                            "sec-ch-ua": _sec_ch_ua,
                            "sec-ch-ua-mobile": "?0",
                            "sec-ch-ua-platform": '"Windows"',
                        },
                        data=json.dumps(payload),
                        timeout=15,
                    ),
                    label="enqueue-async-account",
                )
                print(f"[*] enqueue async account status: {resp.status_code}")
                if resp.status_code not in (200, 201, 202):
                    print(f"[Warn] enqueue async account failed: {resp.text[:200]}")
                    return None
                data = resp.json() if resp.text.strip() else {}
                _log_page_transition("create-account-later", data)
                continue_url = str((data.get("continue_url") or "")).strip()
                if continue_url:
                    callback_json = _follow_redirect_chain_for_callback(
                        session=s,
                        start_url=continue_url,
                        oauth=oauth,
                        proxies=proxies,
                        referer="https://auth.openai.com/create-account-later",
                        max_hops=10,
                        label="async-account-chain",
                    )
                    if callback_json:
                        return callback_json
                page_url = _page_type_to_url(_extract_page_type(data))
                if page_url:
                    callback_json = _follow_redirect_chain_for_callback(
                        session=s,
                        start_url=page_url,
                        oauth=oauth,
                        proxies=proxies,
                        referer="https://auth.openai.com/create-account-later",
                        max_hops=10,
                        label="async-account-page-chain",
                    )
                    if callback_json:
                        return callback_json
                wait_time = random.uniform(5.0, 8.0)
                print(f"[*] async account queued; wait {wait_time:.1f}s before re-check")
                time.sleep(wait_time)
            except Exception as e:
                print(f"[Warn] enqueue async account exception: {e}")
            return None

        if phone_required:
            print("[*] OpenAI 要求手机号验证，先尝试复用当前 session 继续获取 token...")
            print(f"[*] phone page type={ca_page_type or '<none>'} continue_url={ca_continue or '<none>'}")
            _record_domain_outcome(email, "phone_required")
            experiment_callback = _chatgpt_experiment_probe_callback(
                session=s,
                oauth=oauth,
                proxies=proxies,
                referer="https://chatgpt.com/auth/login",
                label="signup-chatgpt-probe",
                user_agent=_user_agent,
                sec_ch_ua=_sec_ch_ua,
                email=email,
                password=password,
                dev_token=dev_token,
                impersonate=_impersonate,
            )
            if experiment_callback:
                return experiment_callback
            if ca_continue:
                try:
                    s.get(
                        ca_continue,
                        headers={"referer": "https://auth.openai.com/about-you"},
                        allow_redirects=True,
                        timeout=15,
                    )
                except Exception as e:
                    print(f"[Warn] 无法预热 phone continue_url: {e}")

        # 如果有 continue_url，手动跟重定向，捕获 OAuth callback
        if ca_continue and "phone" not in ca_continue.lower():
            current_url = ca_continue
            if "code=" in current_url and "state=" in current_url:
                if "chatgpt.com/api/auth/callback/openai" in current_url:
                    callback_json = _chatgpt_experiment_finalize_to_formal_token(
                        session=s,
                        callback_url=current_url,
                        email=email,
                        password=password,
                        dev_token=dev_token,
                        proxies=proxies,
                        impersonate=_impersonate,
                        user_agent=_user_agent,
                        sec_ch_ua=_sec_ch_ua,
                        label="signup-chatgpt-finish",
                        seen_msg_ids=_otp_seen,
                        signup_otp_code=otp_code,
                    )
                    if callback_json:
                        return callback_json
                else:
                    return submit_callback_url(
                        callback_url=current_url,
                        code_verifier=oauth.code_verifier,
                        redirect_uri=oauth.redirect_uri,
                        client_id=oauth.client_id,
                        expected_state=oauth.state,
                        proxies=proxies,
                    )
            for _redir in range(10):
                redir_resp = s.get(current_url, headers={"referer": "https://auth.openai.com/about-you"}, allow_redirects=False, timeout=15)
                location = redir_resp.headers.get("Location") or ""
                if redir_resp.status_code not in [301, 302, 303, 307, 308]:
                    break
                if not location:
                    break
                next_url = urllib.parse.urljoin(current_url, location)
                if "code=" in next_url and "state=" in next_url:
                    print("[*] 从 create_account 重定向链中直接获取到 OAuth callback")
                    if "chatgpt.com/api/auth/callback/openai" in next_url:
                        callback_json = _chatgpt_experiment_finalize_to_formal_token(
                            session=s,
                            callback_url=next_url,
                            email=email,
                            password=password,
                            dev_token=dev_token,
                            proxies=proxies,
                            impersonate=_impersonate,
                            user_agent=_user_agent,
                            sec_ch_ua=_sec_ch_ua,
                            label="signup-chatgpt-finish",
                            seen_msg_ids=_otp_seen,
                            signup_otp_code=otp_code,
                        )
                        if callback_json:
                            return callback_json
                    else:
                        return submit_callback_url(
                            callback_url=next_url,
                            code_verifier=oauth.code_verifier,
                            redirect_uri=oauth.redirect_uri,
                            client_id=oauth.client_id,
                            expected_state=oauth.state,
                            proxies=proxies,
                        )
                current_url = next_url

        workspaces = []
        session_state = _extract_auth_session_metadata(s)
        session_orgs = session_state.get("orgs") if isinstance(session_state.get("orgs"), list) else []
        if session_state.get("workspaces"):
            workspaces = session_state["workspaces"]

        if not workspaces and not phone_required:
            dump_state = _fetch_client_auth_session_dump(s)
            if dump_state.get("workspaces"):
                workspaces = dump_state["workspaces"]
            if not session_orgs and isinstance(dump_state.get("orgs"), list):
                session_orgs = dump_state.get("orgs") or []

        # 如果 cookie 里没有 workspaces，通过 API 获取
        if not workspaces:
            print("[*] Cookie 中无 workspace，尝试通过 API 获取...")
            try:
                sentinel = _get_sentinel(SENTINEL_FLOW_WORKSPACE)
                ws_resp = _request_with_retries(
                    lambda: s.get(
                        "https://auth.openai.com/api/accounts/workspaces",
                        headers=_auth_headers("https://auth.openai.com/", sentinel),
                        timeout=15,
                    ),
                    label="fetch-workspaces",
                )
                if ws_resp.status_code == 200:
                    ws_data = ws_resp.json() if ws_resp.text.strip() else {}
                    # 可能是 {"workspaces": [...]} 或直接是列表
                    if isinstance(ws_data, list):
                        workspaces = ws_data
                    elif isinstance(ws_data, dict):
                        workspaces = ws_data.get("workspaces") or ws_data.get("data") or []
                    print(f"[*] API 返回 workspace 数量: {len(workspaces)}")
                else:
                    pass
            except Exception:
                pass

        if not workspaces and session_orgs:
            org_callback = _select_first_org_project(
                session=s,
                orgs=session_orgs,
                oauth=oauth,
                proxies=proxies,
                referer="https://auth.openai.com/sign-in-with-chatgpt/codex/organization",
            )
            if org_callback:
                print("[*] 瘜典?瘚??? session org select ?瑕???OAuth callback!")
                return org_callback

        if not workspaces and not phone_required:
            print("[*] 探测 codex consent/workspace 页面...")
            candidate_pages = []
            for candidate in candidate_pages:
                callback_json = _follow_redirect_chain_for_callback(
                    session=s,
                    start_url=candidate,
                    oauth=oauth,
                    proxies=proxies,
                    referer="https://auth.openai.com/about-you",
                    max_hops=10,
                    label="signup-route-probe",
                )
                if callback_json:
                    print(f"[*] 注册流程通过页面探测拿到 OAuth callback: {candidate}")
                    return callback_json

            dump_state = _fetch_client_auth_session_dump(s)
            if dump_state.get("workspaces"):
                workspaces = dump_state["workspaces"]

        if False and not workspaces:
            # 最后尝试：直接跳过 workspace 选择，走 continue_url 重定向链
            print("[*] 无法获取 workspace，尝试直接跳过 workspace 选择步骤...")
            # 有些新账号可能只有一个默认 workspace，不需要选择
            # 直接从 create_account 的 continue_url 继续走重定向
            if ca_continue:
                current_url = ca_continue
                for _ in range(6):
                    final_resp = s.get(current_url, allow_redirects=False, timeout=15)
                    location = final_resp.headers.get("Location") or ""
                    if final_resp.status_code not in [301, 302, 303, 307, 308]:
                        break
                    if not location:
                        break
                    next_url = urllib.parse.urljoin(current_url, location)
                    current_url = next_url
                    parsed = urllib.parse.urlparse(next_url)
                    qs = urllib.parse.parse_qs(parsed.query)
                    if "code" in qs and "state" in qs:
                        print("[*] 跳过 workspace 选择，直接获取到 OAuth callback")
                        return submit_callback_url(
                            callback_url=next_url,
                            code_verifier=oauth.code_verifier,
                            redirect_uri=oauth.redirect_uri,
                            expected_state=oauth.state,
                            proxies=proxies,
                        )
            print("[Error] 授权 Cookie 里没有 workspace 信息，且无法通过 API 或重定向获取")
            return _fallback_login_for_token("missing workspaces") if phone_required else None
        workspace_id = str((workspaces[0] or {}).get("id") or "").strip() if workspaces else ""
        if not workspace_id:
            print("[Error] 无法解析 workspace_id")
            return _fallback_login_for_token("missing workspace id") if phone_required else None

        sentinel = _get_sentinel(SENTINEL_FLOW_CODEX_CONSENT)
        select_body = json.dumps({"workspace_id": workspace_id})
        select_resp = _request_with_retries(
            lambda: s.post(
                "https://auth.openai.com/api/accounts/workspace/select",
                headers=_auth_headers(
                    "https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
                    sentinel,
                ),
                data=select_body,
            ),
            label="select-workspace",
        )

        if select_resp.status_code != 200:
            print(f"[Error] 选择 workspace 失败，状态码: {select_resp.status_code}")
            print(select_resp.text)
            return _fallback_login_for_token("workspace select failed") if phone_required else None

        select_data = select_resp.json() if select_resp.text.strip() else {}
        org_callback = _select_first_org_project(
            session=s,
            orgs=_extract_orgs(select_data),
            oauth=oauth,
            proxies=proxies,
            referer="https://auth.openai.com/sign-in-with-chatgpt/codex/organization",
        )
        if org_callback:
            print("[*] 注册流程通过 organization select 获取到 OAuth callback!")
            return org_callback

        continue_url = str((select_data.get("continue_url") or "")).strip()
        if not continue_url:
            print("[Error] workspace/select 响应里缺少 continue_url")
            return _fallback_login_for_token("workspace continue_url missing") if phone_required else None

        current_url = continue_url
        for _ in range(6):
            final_resp = s.get(current_url, allow_redirects=False, timeout=15)
            location = final_resp.headers.get("Location") or ""

            if final_resp.status_code not in [301, 302, 303, 307, 308]:
                break
            if not location:
                break

            next_url = urllib.parse.urljoin(current_url, location)
            if "code=" in next_url and "state=" in next_url:
                return submit_callback_url(
                    callback_url=next_url,
                    code_verifier=oauth.code_verifier,
                    redirect_uri=oauth.redirect_uri,
                    expected_state=oauth.state,
                    proxies=proxies,
                )
            current_url = next_url

        print("[Error] 未能在重定向链中捕获到最终 Callback URL")
        return _fallback_login_for_token("final callback missing") if phone_required else None

    except RetryNewEmail as e:
        retry_message = str(e)
        reason = retry_message.rsplit(":", 1)[-1].strip().lower()
        if reason:
            _update_run_context(
                last_branch_result=reason,
                last_branch_page="authorize_continue",
                last_branch_continue_url="https://auth.openai.com/api/accounts/authorize/continue",
            )
        print(f"[Retry] {e}")
        if blacklist_retry_left <= 0:
            print("[Error] exhausted blacklist retries in current worker")
            return None
        print(
            f"[Retry] requesting a new email now; "
            f"retries left={blacklist_retry_left}"
        )
        next_proxy = proxy if proxy is not None else "direct"
        return run(next_proxy, blacklist_retry_left=blacklist_retry_left - 1)
    except Exception as e:
        print(f"[Error] 运行时发生错误: {e}")
        return None


# ==========================================
# Sub2Api 自动推送
# ==========================================

_sub2api_token = ""
_sub2api_lock = threading.Lock()


def _sub2api_login() -> str:
    """登录 sub2api 获取 bearer token"""
    try:
        resp = requests.post(
            f"{SUB2API_URL}/api/v1/auth/login",
            json={"email": SUB2API_EMAIL, "password": SUB2API_PASSWORD},
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json().get("data", {}).get("access_token", "")
    except Exception as e:
        print(f"[Sub2Api] 登录失败: {e}")
    return ""


def get_oai_verify(token: str, email: str, proxies: Any = None) -> str:
    with _stage_slot("otp"):
        return _get_oai_verify_impl(token, email, proxies)


def push_to_sub2api(token_json_str: str) -> bool:
    """将注册好的 token 推送到 sub2api"""
    global _sub2api_token
    try:
        t = json.loads(token_json_str)
        email = t.get("email", "")
        access_token = t.get("access_token", "")
        refresh_token = t.get("refresh_token", "")
        account_id = t.get("account_id", "")

        if not refresh_token:
            print("[Sub2Api] 缺少 refresh_token，跳过推送")
            return False

        # 从 access_token 解析额外信息
        at_claims = _jwt_claims_no_verify(access_token)
        at_auth = at_claims.get("https://api.openai.com/auth") or {}
        exp = at_claims.get("exp", int(time.time()) + 863999)

        # 从 id_token 解析 organization_id
        id_token = t.get("id_token", "")
        it_claims = _jwt_claims_no_verify(id_token)
        it_auth = it_claims.get("https://api.openai.com/auth") or {}
        org_id = ""
        orgs = it_auth.get("organizations") or []
        if orgs:
            org_id = (orgs[0] or {}).get("id", "")

        payload = {
            "name": email,
            "notes": "",
            "platform": "openai",
            "type": "oauth",
            "credentials": {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_in": 863999,
                "expires_at": exp,
                "chatgpt_account_id": account_id or at_auth.get("chatgpt_account_id", ""),
                "chatgpt_user_id": at_auth.get("chatgpt_user_id", ""),
                "organization_id": org_id,
            },
            "extra": {"email": email},
            # "extra": {"email": email, "openai_passthrough": True},
            "group_ids": [2],
            "concurrency": 10,
            "priority": 1,
            "auto_pause_on_expired": True,
        }

        with _sub2api_lock:
            if not _sub2api_token:
                _sub2api_token = _sub2api_login()
            if not _sub2api_token:
                print("[Sub2Api] 无法获取 token，推送失败")
                return False
            current_token = _sub2api_token

        resp = requests.post(
            f"{SUB2API_URL}/api/v1/admin/accounts",
            json=payload,
            headers={
                "Authorization": f"Bearer {current_token}",
                "Content-Type": "application/json",
            },
            timeout=20,
        )

        # 401 重新登录重试
        if resp.status_code == 401:
            with _sub2api_lock:
                # 只在 token 未被其他线程刷新时才重新登录
                if _sub2api_token == current_token:
                    _sub2api_token = _sub2api_login()
                current_token = _sub2api_token
            if current_token:
                resp = requests.post(
                    f"{SUB2API_URL}/api/v1/admin/accounts",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {current_token}",
                        "Content-Type": "application/json",
                    },
                    timeout=20,
                )

        if resp.status_code in (200, 201):
            print(f"[Sub2Api] 推送成功!")
            return True
        else:
            print(f"[Sub2Api] 推送失败 ({resp.status_code}): {resp.text[:200]}")
            return False

    except Exception as e:
        print(f"[Sub2Api] 推送异常: {e}")
        return False


def main() -> None:
    global _worker_count_hint, _experiment_enabled, _experiment2_enabled, _beta_enabled, _beta2_enabled, _alpha_enabled, _skymail_preferred, _legacy_mail_mode, _dropmail_pool_mode, _no_blacklist_mode, _browser_mode, _low_mode
    global _experiment2_fresh_cloudvxz, _experiment2_fresh_count, _experiment2_fresh_lengths, _experiment2_fresh_pool
    global manage
    parser = argparse.ArgumentParser(description="OpenAI 自动注册脚本")
    parser.add_argument(
        "--cpa-base-url",
        default="",
        help=f"CPA 上传服务地址，默认 {DEFAULT_CPA_BASE_URL}",
    )
    parser.add_argument(
        "--cpa-token",
        default="",
        help="CPA 上传服务 Bearer Token；不传则使用环境变量或当前默认值",
    )
    parser.add_argument(
        "--proxy",
        default="",
        help="代理地址；未传时自动探测本地 127.0.0.1 候选端口，传 direct/off 可关闭",
    )
    parser.add_argument("--once", action="store_true", help="只运行一次")
    parser.add_argument("--sleep-min", type=int, default=5, help="循环模式最短等待秒数")
    parser.add_argument(
        "--sleep-max", type=int, default=30, help="循环模式最长等待秒数"
    )
    parser.add_argument(
        "--workers", type=int, default=50,
        help="并发线程数；默认 50，传 1 为串行",
    )
    parser.add_argument(
        "--auto-workers",
        action="store_true",
        help=f"按可用 CPU 自动计算线程数（{AUTO_WORKERS_PER_HCPU} threads / hcpu）",
    )
    parser.add_argument(
        "--mailbox-limit", type=int, default=0,
        help="邮箱申请阶段并发上限，0 表示不限制",
    )
    parser.add_argument(
        "--otp-limit", type=int, default=0,
        help="验证码轮询阶段并发上限，0 表示不限制",
    )
    parser.add_argument(
        "--register-limit", type=int, default=0,
        help="注册主流程阶段并发上限，0 表示不限制",
    )
    parser.add_argument(
        "--run-retries", type=int, default=DEFAULT_RUN_RETRIES,
        help="单个 worker 在一次失败后整轮补跑次数",
    )
    parser.add_argument(
        "--target-tokens", type=int, default=0,
        help="0 means unlimited; stop after minting this many new tokens in current run",
    )
    parser.add_argument(
        "--experiment",
        action="store_true",
        help="enable experimental chatgpt.com warm/probe branch",
    )
    parser.add_argument(
        "--experiment2",
        action="store_true",
        help="enable managed experiment branch (chrome146_current + cloudvxz subdomains + branch logging)",
    )
    parser.add_argument(
        "--experiment2-profile",
        default="chrome146_current",
        help="managed experiment profile: chrome133a_mac / chrome146_current / chrome131_win / firefox133_win",
    )
    parser.add_argument(
        "--experiment2-family",
        default="cloudvxz.com",
        help="managed experiment target family",
    )
    parser.add_argument(
        "--experiment2-domains",
        default="",
        help="comma-separated exact domains for managed experiment, e.g. x9.cloudvxz.com,q4.cloudvxz.com",
    )
    parser.add_argument(
        "--experiment2-fresh-cloudvxz",
        action="store_true",
        help="generate a fresh cloudvxz subdomain pool that avoids blocked and previously tested domains",
    )
    parser.add_argument(
        "--experiment2-fresh-count",
        type=int,
        default=8,
        help="number of generated fresh cloudvxz subdomains per process",
    )
    parser.add_argument(
        "--experiment2-fresh-lengths",
        default="2",
        help="comma-separated fresh cloudvxz label lengths, e.g. 2 or 2,3",
    )
    parser.add_argument(
        "--experiment2-accept-language",
        default="",
        help="override managed experiment Accept-Language",
    )
    parser.add_argument(
        "--beta",
        action="store_true",
        help="force focused cloudvxz beta pool: jc/m2/2fi subdomains",
    )
    parser.add_argument(
        "--beta2",
        action="store_true",
        help="force focused cloudvxz beta2 pool: normal=z6/oh, low=ek/si",
    )
    parser.add_argument(
        "--alpha",
        action="store_true",
        help="force infini-ai.eu.cc subdomain mailbox source",
    )
    parser.add_argument(
        "--skymail",
        action="store_true",
        help="prefer skymail/cloudmail mailbox source if skymail_config.json or config.json is configured",
    )
    parser.add_argument(
        "--dropmail-pool",
        default="primary",
        choices=["primary", "backup", "all"],
        help="select dropmail domain pool: primary / backup / all",
    )
    parser.add_argument(
        "--legacy",
        action="store_true",
        help="use the previous mailbox chain (tempmail-first behavior, disables dropmail priority)",
    )
    parser.add_argument(
        "--no-blacklist",
        action="store_true",
        help="disable blacklist/quarantine reads and writes for exploratory mailbox sources",
    )
    parser.add_argument(
        "--browser",
        action="store_true",
        help="enable browser-assisted mode (Playwright/Sentinel bridge + non-low behavior)",
    )
    parser.add_argument(
        "--low",
        action="store_true",
        help="compatibility alias for the default low/original mode",
    )
    args = parser.parse_args()
    cpa_base_url, cpa_token = _resolve_cpa_settings(args.cpa_base_url, args.cpa_token)
    manage = ZeaburAuthFileManager(cpa_base_url, cpa_token)
    proxy_arg_supplied = any(
        arg == "--proxy" or arg.startswith("--proxy=")
        for arg in sys.argv[1:]
    )
    if not proxy_arg_supplied:
        args.proxy = "auto"
    args.proxy = _prepare_v2rayn_proxy(args.proxy)

    sleep_min = max(1, args.sleep_min)
    sleep_max = max(sleep_min, args.sleep_max)
    auto_worker_cpu = None
    if args.auto_workers:
        workers, auto_worker_cpu = _compute_auto_workers()
        if args.workers != 50:
            print(
                f"[Warn] --auto-workers overrides --workers={args.workers}; "
                f"using workers={workers}"
            )
    else:
        workers = max(1, args.workers)
    _worker_count_hint = workers
    run_retries = max(0, args.run_retries)
    target_tokens = max(0, args.target_tokens)
    _experiment_enabled = bool(args.experiment)
    _experiment2_enabled = bool(args.experiment2)
    _beta_enabled = bool(args.beta)
    _beta2_enabled = bool(args.beta2)
    _alpha_enabled = bool(args.alpha)
    _skymail_preferred = bool(args.skymail)
    _legacy_mail_mode = bool(args.legacy)
    _dropmail_pool_mode = str(args.dropmail_pool or "primary").strip().lower()
    _no_blacklist_mode = bool(args.no_blacklist)
    _browser_mode = bool(args.browser)
    _low_mode = not _browser_mode
    if MAIL_PROVIDER_MODE == "self_hosted_messages_api":
        _alpha_enabled = False
        _skymail_preferred = False
        _legacy_mail_mode = False
    if args.browser and args.low:
        print("[Warn] --browser overrides --low; using browser-assisted mode")
    _experiment2_fresh_cloudvxz = bool(args.experiment2_fresh_cloudvxz)
    _experiment2_fresh_count = max(1, int(args.experiment2_fresh_count or 8))
    _experiment2_fresh_lengths = _parse_fresh_cloudvxz_lengths(args.experiment2_fresh_lengths)
    _experiment2_fresh_pool = []
    if MAIL_PROVIDER_MODE == "self_hosted_messages_api":
        for source_name in list(MAIL_SOURCES.keys()):
            MAIL_SOURCES[source_name] = (source_name == "self_hosted_messages_api")
    else:
        MAIL_SOURCES["skymail"] = _skymail_is_configured()
    if _experiment2_enabled:
        globals()["_experiment2_profile_name"] = str(args.experiment2_profile or "chrome146_current").strip()
        globals()["_experiment2_force_family"] = str(args.experiment2_family or "cloudvxz.com").strip().lower()
        globals()["_experiment2_accept_language"] = str(args.experiment2_accept_language or "").strip()
        if str(args.experiment2_domains or "").strip():
            globals()["_experiment2_domain_pool"] = [
                item.strip().lower()
                for item in str(args.experiment2_domains).split(",")
                if item.strip()
            ]
        elif _experiment2_fresh_cloudvxz and not _beta_enabled and not _beta2_enabled and _experiment2_force_family == "cloudvxz.com":
            globals()["_experiment2_fresh_pool"] = _generate_fresh_cloudvxz_domains(
                _experiment2_fresh_count,
                _experiment2_fresh_lengths,
            )
    mailbox_limit = _resolve_stage_limit(args.mailbox_limit)
    otp_limit = _resolve_stage_limit(args.otp_limit)
    register_limit = _resolve_stage_limit(args.register_limit)

    _set_stage_limit("mailbox", mailbox_limit)
    _set_stage_limit("otp", otp_limit)
    _set_stage_limit("register", register_limit)

    base_dir = os.path.dirname(os.path.abspath(__file__))
    repair_result = _repair_token_exports(base_dir)

    _print_lock = threading.Lock()
    _file_lock = threading.Lock()
    _stop_event = threading.Event()
    _success_count = 0
    _success_count_lock = threading.Lock()

    def _save_and_push(token_json: str) -> bool:
        nonlocal _success_count
        saved = _persist_token_artifacts(base_dir, token_json, _file_lock)
        with _print_lock:
            if saved["token_path"]:
                if saved.get("is_experiment"):
                    print(f"[*] saved experiment session json: {saved['token_path']}")
                elif saved.get("was_local_promotion"):
                    print(f"[*] saved promoted experiment token json: {saved['token_path']}")
                else:
                    print(f"[*] saved token json「˚˚˚˚˚˚˚˚˚˚˚˚˚˚˚˚˚˚˚˚˚˚˚˚˚˚˚」: {saved['token_path']}")
                    upload_status = manage.upload("",saved['token_path'])
                    if bool(upload_status):
                        print(f"上传成功✅✅✅✅✅✅✅✅✅✅✅✅✅✅✅✅✅✅✅✅✅✅✅✅")
            if saved["access_token"] and not saved.get("is_experiment"):
                print(f"[*] appended access token to: {saved['ak_path']}")
            if saved["refresh_token"] and not saved.get("is_experiment"):
                print(f"[*] appended refresh token to: {saved['rk_path']}")
        if saved.get("is_experiment"):
            return False
        current_success = 0
        if target_tokens > 0:
            with _success_count_lock:
                if _success_count >= target_tokens:
                    _stop_event.set()
                    return False
                _success_count += 1
                current_success = _success_count
        if saved.get("email"):
            _record_domain_outcome(saved["email"], "success")
        if target_tokens > 0:
            if current_success >= target_tokens:
                _stop_event.set()
            with _print_lock:
                print(f"[*] target progress: {current_success}/{target_tokens}")
                if current_success >= target_tokens:
                    print(f"[*] target tokens reached ({target_tokens}), stopping workers...")
        if SUB2API_ENABLED and not saved.get("was_local_promotion"):
            push_to_sub2api(saved.get("stored_token_json") or token_json)
        return True

    def _one_run(worker_slot: int, run_id: str) -> None:
        if _stop_event.is_set():
            return
        _begin_run_context(run_id=run_id, worker_slot=worker_slot)
        final_status = "failed"
        final_reason = "no_token"
        final_error = ""
        token_saved = False
        try:
            with _print_lock:
                print(
                    f"\n[{datetime.now().strftime('%H:%M:%S')}] "
                    f">>> worker {worker_slot} run {run_id} start <<<"
                )
            effective_run_retries = 0 if (_low_mode or _experiment2_enabled) else run_retries
            for attempt in range(1, effective_run_retries + 2):
                _update_run_context(attempts=attempt)
                if _stop_event.is_set():
                    final_status = "stopped"
                    final_reason = "stop_event_before_attempt"
                    return
                try:
                    with _stage_slot("register"):
                        token_json = run(args.proxy)
                    if token_json:
                        if _save_and_push(token_json):
                            final_status = "success"
                            final_reason = "token_saved"
                            token_saved = True
                            return
                        token_payload = _token_payload_or_empty(token_json)
                        if _is_experiment_token_payload(token_payload):
                            final_reason = "experiment_payload_only"
                        else:
                            final_reason = "persist_rejected"
                        token_json = None
                except Exception as e:
                    final_status = "exception"
                    final_reason = "uncaught_exception"
                    final_error = f"{type(e).__name__}: {e}"
                    with _print_lock:
                        print(f"[Error] worker {worker_slot} run {run_id} uncaught exception: {e}")
                    token_json = None

                if attempt >= effective_run_retries + 1:
                    if final_status != "exception":
                        final_status = "failed"
                        branch_reason = str((_current_run_context() or {}).get("last_branch_result") or "").strip()
                        if branch_reason:
                            final_reason = branch_reason
                    with _print_lock:
                        print(
                            f"[-] worker {worker_slot} run {run_id} failed after "
                            f"{attempt} attempt(s)"
                        )
                    return

                retry_wait = random.uniform(0.8, 2.4)
                with _print_lock:
                    print(
                        f"[Retry] worker {worker_slot} run {run_id} rerun "
                        f"{attempt}/{effective_run_retries + 1}; "
                        f"sleep {retry_wait:.1f}s before retry"
                    )
                time.sleep(retry_wait)
        finally:
            _record_experiment2_run_result(
                status=final_status,
                reason=final_reason,
                token_saved=token_saved,
                error=final_error,
            )
            _clear_run_context()

    run_count = 0
    _run_count_lock = threading.Lock()

    def _next_run_id(worker_slot: int) -> str:
        nonlocal run_count
        with _run_count_lock:
            run_count += 1
            return f"{_run_session_id}-w{worker_slot}-r{run_count}"

    def _worker_loop(worker_slot: int) -> None:
        if args.once:
            _one_run(worker_slot, _next_run_id(worker_slot))
            return

        while not _stop_event.is_set():
            _one_run(worker_slot, _next_run_id(worker_slot))
            if _stop_event.is_set():
                return
            wait_time = random.randint(sleep_min, sleep_max)
            with _print_lock:
                print(f"[*] worker {worker_slot} sleep {wait_time} seconds...")
            time.sleep(wait_time)

    print(f"[Build] {SCRIPT_BUILD}")
    print(f"[Info] Yasal's Seamless OpenAI Auto-Registrar Started for ZJH (workers={workers})")
    if auto_worker_cpu is not None:
        print(
            f"[Info] workers mode: auto "
            f"(effective_cpu={auto_worker_cpu:.2f}, "
            f"threads_per_hcpu={AUTO_WORKERS_PER_HCPU})"
        )
    else:
        print("[Info] workers mode: manual")
    print(f"[Info] cpa base url: {cpa_base_url}")
    print(
        f"[Info] stage limits: mailbox={mailbox_limit or 'unlimited'}, "
        f"otp={otp_limit or 'unlimited'}, register={register_limit or 'unlimited'}"
    )
    if MAIL_PROVIDER_MODE == "self_hosted_messages_api":
        print(f"[Info] mail provider: {MAIL_PROVIDER_MODE}")
        print(f"[Info] messages api: {SELF_HOSTED_MESSAGES_API_URL}")
        print(f"[Info] messages domains: {', '.join(SELF_HOSTED_MESSAGES_DOMAINS)}")
    else:
        print(
            "[Info] mailbox mode: "
            + ("legacy (tempmail-first)" if _legacy_mail_mode else "default (dropmail-first)")
        )
        print(f"[Info] dropmail pool: {_dropmail_pool_mode}")
    if repair_result.get("moved_invalid"):
        print(
            f"[Info] repaired invalid promoted tokens: moved={repair_result['moved_invalid']} "
            f"valid_remaining={repair_result['rebuilt']}"
        )
    print(f"[Info] run retries per worker: {run_retries}")
    print(f"[Info] target tokens this run: {target_tokens or 'unlimited'}")
    print(f"[Info] experiment: {'chatgpt' if _experiment_enabled else 'off'}")
    print(f"[Info] experiment2: {'managed' if _experiment2_enabled else 'off'}")
    print(f"[Info] alpha: {'infini-submail' if _alpha_enabled else 'off'}")
    print(f"[Info] beta: {'cloudvxz-top2' if _beta_enabled else 'off'}")
    if _beta2_enabled:
        beta2_label = "cloudvxz-low-ek-si" if _low_mode else "cloudvxz-fresh2-winners"
    else:
        beta2_label = "off"
    print(f"[Info] beta2: {beta2_label}")
    if MAIL_PROVIDER_MODE != "self_hosted_messages_api":
        print(
            f"[Info] skymail: "
            f"{'preferred' if _skymail_preferred else ('configured' if MAIL_SOURCES.get('skymail') else 'off')}"
        )
    print(f"[Info] browser mode: {'on' if _browser_mode else 'off'}")
    print(f"[Info] low mode: {'on' if _low_mode else 'off'}")
    print(f"[Info] no-blacklist: {'on' if _no_blacklist_mode else 'off'}")
    print(f"[Info] run session: {_run_session_id}")
    if _experiment2_enabled and _experiment2_fresh_cloudvxz and _experiment2_fresh_pool:
        print(
            f"[Info] fresh cloudvxz pool ({len(_experiment2_fresh_pool)}): "
            f"{', '.join(_experiment2_fresh_pool)}"
        )
    if _experiment2_enabled and not _low_mode:
        print("[Info] experiment2 top-level retries: forced single-pass for clean sampling")
    print(
        "[Info] sentinel flows: "
        f"signup={SENTINEL_FLOW_SIGNUP_EMAIL}, "
        f"password={SENTINEL_FLOW_CREATE_PASSWORD}, "
        f"otp={SENTINEL_FLOW_EMAIL_OTP}, "
        f"about_you={SENTINEL_FLOW_ABOUT_YOU}, "
        f"workspace={SENTINEL_FLOW_WORKSPACE}, "
        f"consent={SENTINEL_FLOW_CODEX_CONSENT}"
    )

    if workers == 1:
        _worker_loop(1)
        return

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_worker_loop, worker_slot) for worker_slot in range(1, workers + 1)]
        for f in as_completed(futures):
            f.result()


if __name__ == "__main__":
    main()
