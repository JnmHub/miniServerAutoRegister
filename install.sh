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

require_cmd tar
require_cmd curl

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
  elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
  else
    echo "未找到 Python，请先安装 Python 3.10+。" >&2
    exit 1
  fi
fi

"$PYTHON_BIN" - <<'PY'
import sys

if sys.version_info < (3, 10):
    raise SystemExit(f"Python 版本过低: {sys.version.split()[0]}，需要 3.10+")
PY

if ! "$PYTHON_BIN" -m venv -h >/dev/null 2>&1; then
  echo "当前 Python 缺少 venv 模块，请先安装 python3-venv。" >&2
  exit 1
fi

TMP_DIR="$(mktemp -d)"
cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

if [[ -n "$SOURCE_DIR_OVERRIDE" ]]; then
  SOURCE_DIR="$(cd "$SOURCE_DIR_OVERRIDE" && pwd)"
  echo "[1/7] 使用本地源码: $SOURCE_DIR"
else
  ARCHIVE_URL="https://codeload.githubusercontent.com/${REPO_OWNER}/${REPO_NAME}/tar.gz/refs/heads/${REPO_BRANCH}"
  ARCHIVE_PATH="${TMP_DIR}/repo.tar.gz"
  echo "[1/7] 下载源码: $ARCHIVE_URL"
  curl -fsSL "$ARCHIVE_URL" -o "$ARCHIVE_PATH"
  tar -xzf "$ARCHIVE_PATH" -C "$TMP_DIR"

  SOURCE_DIR=""
  while IFS= read -r -d '' candidate; do
    SOURCE_DIR="$candidate"
    break
  done < <(find "$TMP_DIR" -mindepth 1 -maxdepth 1 -type d -name "${REPO_NAME}-*" -print0)

  if [[ -z "$SOURCE_DIR" ]]; then
    echo "源码下载完成，但未找到解压目录。" >&2
    exit 1
  fi
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
