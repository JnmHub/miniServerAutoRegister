#!/usr/bin/env bash
set -euo pipefail

REPO_OWNER="${REPO_OWNER:-JnmHub}"
REPO_NAME="${REPO_NAME:-miniServerAutoRegister}"
REPO_BRANCH="${REPO_BRANCH:-main}"
INSTALL_ROOT="${INSTALL_ROOT:-$HOME/.miniServerAutoRegister}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
SOURCE_DIR_OVERRIDE="${LOCAL_SOURCE_DIR:-}"
RUN_AFTER_INSTALL=1
USE_SYSTEMD=1
CPU_QUOTA="${CPU_QUOTA:-}"
MEMORY_MAX="${MEMORY_MAX:-}"
SERVICE_NAME="${SERVICE_NAME:-mini-server-auto-register}"
UV_INSTALL_FALLBACK_DIR="${UV_INSTALL_FALLBACK_DIR:-${INSTALL_ROOT}/.uv-bin}"
UV_PYTHON_INSTALL_FALLBACK_DIR="${UV_PYTHON_INSTALL_FALLBACK_DIR:-${INSTALL_ROOT}/.uv-python}"

print_usage() {
  cat <<'EOF'
Usage:
  bash install.sh [install-options] [-- app-options]

Install options:
  --install-dir DIR      安装目录，默认 ~/.miniServerAutoRegister
  --branch NAME          GitHub 分支，默认 main
  --repo-owner NAME      GitHub 仓库 owner，默认 JnmHub
  --repo-name NAME       GitHub 仓库名，默认 miniServerAutoRegister
  --python-bin BIN       Python 可执行文件，默认 python3
  --source-dir DIR       使用本地源码目录，跳过 GitHub 下载
  --use-systemd BOOL     是否启用 systemd 守护，默认 true
  --cpu-quota VALUE      systemd CPUQuota，例如 50%
  --memory-max VALUE     systemd MemoryMax，例如 512M、1G
  --service-name NAME    systemd 服务名，默认 mini-server-auto-register
  --no-run               安装完成后不立即启动
  -h, --help             显示帮助

App options:
  未识别的参数会原样透传给 auto_pool_maintainer.py。

Notes:
  安装脚本会在检测到 Python < 3.10 或缺少 venv 时自动尝试安装新版本 Python。
  如果系统包管理器无法提供 Python 3.10+，会回退到 uv 托管安装 Python 3.12。

Examples:
  curl -fsSL https://raw.githubusercontent.com/JnmHub/miniServerAutoRegister/main/install.sh | bash

  curl -fsSL https://raw.githubusercontent.com/JnmHub/miniServerAutoRegister/main/install.sh | \
    bash -s -- \
      --cpu-quota 80% \
      --memory-max 1G \
      --worker-count 50 \
      --cpa-base-url http://127.0.0.1:8317 \
      --cpa-token your-token \
      --account-password 'Passw0rd!' \
      --mail-mode self_hosted_messages_api \
      --mail-api http://127.0.0.1:8000/messages \
      --mail-domains a.com,b.com \
      --min-candidates 3000 \
      --loop-mode true \
      --clean-files false \
      --use-proxy true \
      --proxy-url http://127.0.0.1:7890
EOF
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "缺少命令: $1" >&2
    exit 1
  fi
}

run_as_root() {
  if [[ "$EUID" -eq 0 ]]; then
    "$@"
    return
  fi
  if command -v sudo >/dev/null 2>&1; then
    sudo "$@"
    return
  fi
  echo "需要 root 或 sudo 权限来安装系统依赖。" >&2
  exit 1
}

command_exists_in_path() {
  local candidate="$1"
  if [[ "$candidate" == */* ]]; then
    [[ -x "$candidate" ]]
    return
  fi
  command -v "$candidate" >/dev/null 2>&1
}

python_cmd_is_compatible() {
  local candidate="$1"
  command_exists_in_path "$candidate" || return 1
  "$candidate" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY
}

python_cmd_has_venv() {
  local candidate="$1"
  command_exists_in_path "$candidate" || return 1
  "$candidate" -m venv -h >/dev/null 2>&1
}

pick_compatible_python() {
  local candidate
  local seen="|"
  for candidate in "$PYTHON_BIN" python3.13 python3.12 python3.11 python3.10 python3 python; do
    [[ -n "$candidate" ]] || continue
    [[ "$seen" == *"|${candidate}|"* ]] && continue
    seen="${seen}${candidate}|"
    if python_cmd_is_compatible "$candidate"; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

apt_wait_for_unlock() {
  local waited=0
  local max_wait=600
  local lock_paths=(
    /var/lib/dpkg/lock-frontend
    /var/lib/dpkg/lock
    /var/lib/apt/lists/lock
    /var/cache/apt/archives/lock
  )

  while :; do
    local locked=0
    local lock_path=""
    for lock_path in "${lock_paths[@]}"; do
      if command -v fuser >/dev/null 2>&1 && fuser "$lock_path" >/dev/null 2>&1; then
        locked=1
        break
      fi
    done

    if [[ "$locked" -eq 0 ]]; then
      return 0
    fi

    if (( waited == 0 )); then
      echo "检测到 apt/dpkg 正在被其他进程占用，等待锁释放..." >&2
    fi

    if (( waited >= max_wait )); then
      echo "等待 apt/dpkg 锁超时（>${max_wait}s），请稍后重试。" >&2
      return 1
    fi

    sleep 5
    waited=$((waited + 5))
  done
}

apt_run() {
  local output_file=""
  local status=0
  local attempt=0

  while (( attempt < 120 )); do
    apt_wait_for_unlock || return 1
    output_file="$(mktemp)"

    if run_as_root env DEBIAN_FRONTEND=noninteractive "$@" >"$output_file" 2>&1; then
      cat "$output_file" >&2
      rm -f "$output_file"
      return 0
    fi

    status=$?
    cat "$output_file" >&2 || true

    if grep -Eqi "Could not get lock|Unable to acquire the dpkg frontend lock|Could not open lock file" "$output_file"; then
      rm -f "$output_file"
      attempt=$((attempt + 1))
      echo "apt/dpkg 仍被占用，5 秒后重试..." >&2
      sleep 5
      continue
    fi

    rm -f "$output_file"
    return "$status"
  done

  echo "等待 apt/dpkg 锁超时，请稍后重试。" >&2
  return 1
}

is_ubuntu_system() {
  [[ -f /etc/os-release ]] || return 1
  . /etc/os-release
  [[ "${ID:-}" == "ubuntu" ]]
}

ensure_deadsnakes_ppa() {
  apt_run apt-get update
  apt_run apt-get install -y software-properties-common ca-certificates gnupg
  if ! grep -Rhsq "deadsnakes/ppa" /etc/apt/sources.list /etc/apt/sources.list.d 2>/dev/null; then
    apt_wait_for_unlock
    run_as_root add-apt-repository -y ppa:deadsnakes/ppa >&2
  fi
  apt_run apt-get update
}

resolve_installed_python_path() {
  local version="$1"
  local cmd_name="python${version}"

  if command_exists_in_path "/usr/bin/${cmd_name}"; then
    printf '/usr/bin/%s\n' "$cmd_name"
    return 0
  fi
  if command_exists_in_path "$cmd_name"; then
    printf '%s\n' "$cmd_name"
    return 0
  fi
  return 1
}

apt_try_install_python_version() {
  local version="$1"
  local resolved=""

  if apt_run apt-get install -y "python${version}" "python${version}-venv"; then
    :
  elif apt_run apt-get install -y "python${version}-full"; then
    :
  elif apt_run apt-get install -y "python${version}" "python${version}-distutils" "python${version}-venv"; then
    :
  else
    return 1
  fi

  resolved="$(resolve_installed_python_path "$version" || true)"
  if [[ -z "$resolved" ]]; then
    return 1
  fi
  if ! python_cmd_is_compatible "$resolved"; then
    return 1
  fi
  if ! python_cmd_has_venv "$resolved"; then
    return 1
  fi
  printf '%s\n' "$resolved"
  return 0
}

install_python_with_apt() {
  local version
  local resolved_path=""
  apt_run apt-get update
  apt_run apt-get install -y ca-certificates curl tar

  for version in 3.13 3.12 3.11 3.10; do
    if resolved_path="$(apt_try_install_python_version "$version")"; then
      printf '%s\n' "$resolved_path"
      return 0
    fi
  done

  if is_ubuntu_system; then
    ensure_deadsnakes_ppa
    for version in 3.13 3.12 3.11 3.10; do
      if resolved_path="$(apt_try_install_python_version "$version")"; then
        printf '%s\n' "$resolved_path"
        return 0
      fi
    done
  fi

  return 1
}

install_python_with_dnf_family() {
  local pm="$1"
  local package_name
  for package_name in python3.12 python3.11 python3.10; do
    if run_as_root "$pm" install -y "$package_name" >/dev/null 2>&1; then
      if command -v "$package_name" >/dev/null 2>&1; then
        printf '%s\n' "$package_name"
        return 0
      fi
    fi
  done
  return 1
}

install_python_with_uv() {
  local uv_bin=""
  local resolved=""

  require_cmd curl
  mkdir -p "$UV_INSTALL_FALLBACK_DIR" "$UV_PYTHON_INSTALL_FALLBACK_DIR"

  echo "系统仓库安装 Python 失败，回退到 uv 托管安装 Python 3.12..." >&2
  curl -LsSf https://astral.sh/uv/install.sh | env UV_UNMANAGED_INSTALL="$UV_INSTALL_FALLBACK_DIR" sh >&2

  uv_bin="${UV_INSTALL_FALLBACK_DIR}/uv"
  if [[ ! -x "$uv_bin" ]]; then
    echo "uv 安装失败: 未找到 ${uv_bin}" >&2
    return 1
  fi

  UV_PYTHON_INSTALL_DIR="$UV_PYTHON_INSTALL_FALLBACK_DIR" \
    "$uv_bin" python install --install-dir "$UV_PYTHON_INSTALL_FALLBACK_DIR" 3.12 >&2

  resolved="$(
    UV_PYTHON_INSTALL_DIR="$UV_PYTHON_INSTALL_FALLBACK_DIR" \
      "$uv_bin" python find 3.12
  )"

  if [[ -z "$resolved" ]]; then
    echo "uv 已安装，但未找到已安装的 Python 3.12。" >&2
    return 1
  fi

  printf '%s\n' "$resolved"
}

download_repo_source() {
  local archive_path="${TMP_DIR}/repo.tar.gz"
  local extracted_dir=""
  local download_urls=(
    "https://github.com/${REPO_OWNER}/${REPO_NAME}/archive/refs/heads/${REPO_BRANCH}.tar.gz"
    "https://codeload.githubusercontent.com/${REPO_OWNER}/${REPO_NAME}/tar.gz/refs/heads/${REPO_BRANCH}"
  )
  local url=""

  require_cmd curl
  require_cmd tar

  for url in "${download_urls[@]}"; do
    echo "[1/7] 下载源码: ${url}"
    if curl -fL --retry 3 --retry-all-errors --connect-timeout 15 "$url" -o "$archive_path"; then
      rm -rf "${TMP_DIR:?}/${REPO_NAME}-extract"
      mkdir -p "${TMP_DIR}/${REPO_NAME}-extract"
      tar -xzf "$archive_path" -C "${TMP_DIR}/${REPO_NAME}-extract"

      extracted_dir=""
      while IFS= read -r -d '' candidate; do
        extracted_dir="$candidate"
        break
      done < <(find "${TMP_DIR}/${REPO_NAME}-extract" -mindepth 1 -maxdepth 1 -type d -print0)

      if [[ -n "$extracted_dir" ]]; then
        printf '%s\n' "$extracted_dir"
        return 0
      fi
    fi
    echo "下载失败，尝试下一个源码获取方式..." >&2
  done

  if command -v git >/dev/null 2>&1; then
    extracted_dir="${TMP_DIR}/${REPO_NAME}-git"
    echo "[1/7] 下载源码: git clone https://github.com/${REPO_OWNER}/${REPO_NAME}.git"
    if git clone --depth 1 --branch "$REPO_BRANCH" "https://github.com/${REPO_OWNER}/${REPO_NAME}.git" "$extracted_dir" >&2; then
      printf '%s\n' "$extracted_dir"
      return 0
    fi
  fi

  echo "源码下载失败，请检查仓库地址、分支名或 GitHub 网络连通性。" >&2
  return 1
}

ensure_python_310_or_newer() {
  local selected=""

  if selected="$(pick_compatible_python 2>/dev/null)"; then
    PYTHON_BIN="$selected"
    if python_cmd_has_venv "$PYTHON_BIN"; then
      return 0
    fi
  fi

  echo "检测到 Python 不满足 3.10+ 或缺少 venv，开始自动安装..." >&2

  if command -v apt-get >/dev/null 2>&1; then
    selected="$(install_python_with_apt || true)"
  elif command -v dnf >/dev/null 2>&1; then
    selected="$(install_python_with_dnf_family dnf || true)"
  elif command -v yum >/dev/null 2>&1; then
    selected="$(install_python_with_dnf_family yum || true)"
  fi

  if [[ -z "$selected" ]]; then
    selected="$(install_python_with_uv || true)"
  fi

  if [[ -z "$selected" ]]; then
    selected="$(pick_compatible_python 2>/dev/null || true)"
  fi

  if [[ -z "$selected" ]]; then
    echo "自动安装 Python 失败，请手动安装 Python 3.10+ 后重试。" >&2
    exit 1
  fi

  PYTHON_BIN="$selected"

  if ! python_cmd_is_compatible "$PYTHON_BIN"; then
    local version_text
    version_text="$("$PYTHON_BIN" - <<'PY'
import sys
print(sys.version.split()[0])
PY
)"
    echo "Python 版本过低: ${version_text}，需要 3.10+。" >&2
    exit 1
  fi

  if ! python_cmd_has_venv "$PYTHON_BIN"; then
    echo "已找到 ${PYTHON_BIN}，但缺少 venv 模块，请安装对应的 venv 包后重试。" >&2
    exit 1
  fi
}

parse_bool_value() {
  local value
  value="$(printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]')"
  case "$value" in
    1|true|yes|on|y) return 0 ;;
    0|false|no|off|n) return 1 ;;
    *)
      echo "不支持的布尔值: ${1:-}，请使用 true/false" >&2
      exit 1
      ;;
  esac
}

set_bool_var() {
  local var_name="$1"
  local raw_value="$2"
  if parse_bool_value "$raw_value"; then
    printf -v "$var_name" '%s' 1
  else
    printf -v "$var_name" '%s' 0
  fi
}

APP_ARGS=()
while (($# > 0)); do
  case "$1" in
    --install-dir)
      INSTALL_ROOT="$2"
      shift 2
      ;;
    --install-dir=*)
      INSTALL_ROOT="${1#*=}"
      shift
      ;;
    --branch)
      REPO_BRANCH="$2"
      shift 2
      ;;
    --branch=*)
      REPO_BRANCH="${1#*=}"
      shift
      ;;
    --repo-owner)
      REPO_OWNER="$2"
      shift 2
      ;;
    --repo-owner=*)
      REPO_OWNER="${1#*=}"
      shift
      ;;
    --repo-name)
      REPO_NAME="$2"
      shift 2
      ;;
    --repo-name=*)
      REPO_NAME="${1#*=}"
      shift
      ;;
    --python-bin)
      PYTHON_BIN="$2"
      shift 2
      ;;
    --python-bin=*)
      PYTHON_BIN="${1#*=}"
      shift
      ;;
    --source-dir)
      SOURCE_DIR_OVERRIDE="$2"
      shift 2
      ;;
    --source-dir=*)
      SOURCE_DIR_OVERRIDE="${1#*=}"
      shift
      ;;
    --use-systemd)
      set_bool_var USE_SYSTEMD "$2"
      shift 2
      ;;
    --use-systemd=*)
      set_bool_var USE_SYSTEMD "${1#*=}"
      shift
      ;;
    --cpu-quota)
      CPU_QUOTA="$2"
      shift 2
      ;;
    --cpu-quota=*)
      CPU_QUOTA="${1#*=}"
      shift
      ;;
    --memory-max)
      MEMORY_MAX="$2"
      shift 2
      ;;
    --memory-max=*)
      MEMORY_MAX="${1#*=}"
      shift
      ;;
    --service-name)
      SERVICE_NAME="$2"
      shift 2
      ;;
    --service-name=*)
      SERVICE_NAME="${1#*=}"
      shift
      ;;
    --no-run)
      RUN_AFTER_INSTALL=0
      shift
      ;;
    -h|--help)
      print_usage
      exit 0
      ;;
    --)
      shift
      if (($# > 0)); then
        APP_ARGS+=("$@")
      fi
      break
      ;;
    *)
      APP_ARGS+=("$1")
      shift
      ;;
  esac
done

ensure_python_310_or_newer

TMP_DIR="$(mktemp -d)"
cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

if [[ -n "$SOURCE_DIR_OVERRIDE" ]]; then
  SOURCE_DIR="$(cd "$SOURCE_DIR_OVERRIDE" && pwd)"
  echo "[1/7] 使用本地源码: $SOURCE_DIR"
else
  SOURCE_DIR="$(download_repo_source)"
fi

APP_DIR="${INSTALL_ROOT}/app"
RUNTIME_DIR="${INSTALL_ROOT}/runtime"
VENV_DIR="${INSTALL_ROOT}/.venv"
CONFIG_PATH="${RUNTIME_DIR}/config.json"
LOG_DIR="${RUNTIME_DIR}/logs"
RUNNER_PATH="${INSTALL_ROOT}/run.sh"

mkdir -p "$INSTALL_ROOT" "$RUNTIME_DIR" "$LOG_DIR"
rm -rf "$APP_DIR"
cp -R "$SOURCE_DIR" "$APP_DIR"

if [[ ! -f "$APP_DIR/auto_pool_maintainer.py" ]]; then
  echo "源码目录缺少 auto_pool_maintainer.py: $APP_DIR" >&2
  exit 1
fi

if [[ ! -f "$APP_DIR/requirements.txt" ]]; then
  echo "源码目录缺少 requirements.txt: $APP_DIR" >&2
  exit 1
fi

if [[ ! -f "$CONFIG_PATH" ]]; then
  cp "$APP_DIR/config.json" "$CONFIG_PATH"
fi

echo "[2/7] 创建虚拟环境: $VENV_DIR"
"$PYTHON_BIN" -m venv "$VENV_DIR"

echo "[3/7] 安装依赖"
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install -r "$APP_DIR/requirements.txt"

echo "[4/7] 生成启动脚本: $RUNNER_PATH"
{
  echo '#!/usr/bin/env bash'
  echo 'set -euo pipefail'
  printf 'cd %q\n' "$RUNTIME_DIR"
  printf 'exec'
  for arg in "$VENV_DIR/bin/python" "$APP_DIR/auto_pool_maintainer.py" --config "$CONFIG_PATH" --log-dir "$LOG_DIR" "${APP_ARGS[@]}"; do
    printf ' %q' "$arg"
  done
  printf '\n'
} > "$RUNNER_PATH"
chmod +x "$RUNNER_PATH"

echo "[5/7] 安装完成"
echo "安装目录: $INSTALL_ROOT"
echo "程序目录: $APP_DIR"
echo "运行目录: $RUNTIME_DIR"
echo "配置文件: $CONFIG_PATH"
echo "启动脚本: $RUNNER_PATH"

is_systemd_supported() {
  [[ "$(uname -s)" == "Linux" ]] && command -v systemctl >/dev/null 2>&1
}

configure_systemd_service() {
  local use_root_service=0
  local root_prefix=()
  local systemctl_cmd=()
  local unit_dir=""
  local unit_target=""
  local unit_path=""
  local service_user="${SUDO_USER:-${USER:-$(id -un)}}"
  local service_group
  service_group="$(id -gn "$service_user")"
  local exec_start working_dir

  exec_start="$(printf '%q' "$RUNNER_PATH")"
  working_dir="$(printf '%q' "$RUNTIME_DIR")"

  if [[ "$EUID" -eq 0 ]]; then
    use_root_service=1
  elif command -v sudo >/dev/null 2>&1 && sudo -n true >/dev/null 2>&1; then
    use_root_service=1
  fi

  if [[ "$use_root_service" -eq 1 ]]; then
    unit_dir="/etc/systemd/system"
    unit_target="multi-user.target"
    if [[ "$EUID" -eq 0 ]]; then
      systemctl_cmd=(systemctl)
    else
      root_prefix=(sudo -n)
      systemctl_cmd=(sudo -n systemctl)
    fi
    unit_path="${unit_dir}/${SERVICE_NAME}.service"
  else
    unit_dir="${HOME}/.config/systemd/user"
    unit_target="default.target"
    systemctl_cmd=(systemctl --user)
    unit_path="${unit_dir}/${SERVICE_NAME}.service"
    mkdir -p "$unit_dir"
  fi

  if [[ "$use_root_service" -eq 1 && "$EUID" -ne 0 ]]; then
    "${root_prefix[@]}" mkdir -p "$unit_dir"
  else
    mkdir -p "$unit_dir"
  fi

  local tmp_unit="${TMP_DIR}/${SERVICE_NAME}.service"
  {
    echo "[Unit]"
    echo "Description=miniServerAutoRegister"
    echo "After=network-online.target"
    echo "Wants=network-online.target"
    echo
    echo "[Service]"
    echo "Type=simple"
    echo "WorkingDirectory=${working_dir}"
    echo "ExecStart=${exec_start}"
    echo "Restart=always"
    echo "RestartSec=3"
    echo "TimeoutStopSec=30"
    echo "KillSignal=SIGINT"
    echo "Environment=PYTHONUNBUFFERED=1"
    echo "NoNewPrivileges=true"
    echo "PrivateTmp=true"
    echo "LimitNOFILE=65535"
    if [[ "$use_root_service" -eq 1 ]]; then
      echo "User=${service_user}"
      echo "Group=${service_group}"
    fi
    if [[ -n "$CPU_QUOTA" ]]; then
      echo "CPUQuota=${CPU_QUOTA}"
    fi
    if [[ -n "$MEMORY_MAX" ]]; then
      echo "MemoryMax=${MEMORY_MAX}"
    fi
    echo
    echo "[Install]"
    echo "WantedBy=${unit_target}"
  } > "$tmp_unit"

  if [[ "$use_root_service" -eq 1 && "$EUID" -ne 0 ]]; then
    "${root_prefix[@]}" cp "$tmp_unit" "$unit_path"
    "${systemctl_cmd[@]}" daemon-reload
    if [[ "$RUN_AFTER_INSTALL" -eq 1 ]]; then
      "${systemctl_cmd[@]}" enable --now "${SERVICE_NAME}.service"
    fi
  else
    cp "$tmp_unit" "$unit_path"
    "${systemctl_cmd[@]}" daemon-reload
    if [[ "$RUN_AFTER_INSTALL" -eq 1 ]]; then
      "${systemctl_cmd[@]}" enable --now "${SERVICE_NAME}.service"
    fi
  fi

  echo "[6/7] 已写入 systemd 服务: ${unit_path}"
  if [[ "$RUN_AFTER_INSTALL" -eq 1 ]]; then
    echo "[7/7] 已通过 systemd 启动: ${SERVICE_NAME}.service"
  else
    echo "[7/7] 已跳过启动（--no-run），可稍后手动启动: ${SERVICE_NAME}.service"
  fi

  if [[ "$use_root_service" -eq 1 ]]; then
    echo "查看状态: systemctl status ${SERVICE_NAME}.service"
    echo "重启服务: systemctl restart ${SERVICE_NAME}.service"
    echo "查看日志: journalctl -u ${SERVICE_NAME}.service -f"
  else
    echo "查看状态: systemctl --user status ${SERVICE_NAME}.service"
    echo "重启服务: systemctl --user restart ${SERVICE_NAME}.service"
    echo "查看日志: journalctl --user -u ${SERVICE_NAME}.service -f"
  fi
}

start_without_systemd() {
  echo "[6/7] 未启用 systemd，使用直接启动模式"
  if [[ "$RUN_AFTER_INSTALL" -eq 0 ]]; then
    echo "[7/7] 已跳过启动（--no-run）"
    return 0
  fi
  echo "[7/7] 以前台模式启动"
  cd "$RUNTIME_DIR"
  exec "$RUNNER_PATH"
}

if [[ "$USE_SYSTEMD" -eq 1 ]]; then
  if is_systemd_supported; then
    configure_systemd_service
    exit 0
  fi
  echo "提示: 当前环境不支持 systemd，自动回退为直接启动模式"
fi

start_without_systemd
