#!/usr/bin/env bash
set -euo pipefail

REPO_OWNER="${REPO_OWNER:-JnmHub}"
REPO_NAME="${REPO_NAME:-miniServerAutoRegister}"
REPO_BRANCH="${REPO_BRANCH:-main}"
INSTALL_ROOT="${INSTALL_ROOT:-$HOME/.miniServerAutoRegister}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
SOURCE_DIR_OVERRIDE="${LOCAL_SOURCE_DIR:-}"
RUN_AFTER_INSTALL=1

print_usage() {
  cat <<'EOF'
Usage:
  bash install.sh [install-options] [-- app-options]

Install options:
  --install-dir DIR    安装目录，默认 ~/.miniServerAutoRegister
  --branch NAME        GitHub 分支，默认 main
  --repo-owner NAME    GitHub 仓库 owner，默认 JnmHub
  --repo-name NAME     GitHub 仓库名，默认 miniServerAutoRegister
  --python-bin BIN     Python 可执行文件，默认 python3
  --source-dir DIR     使用本地源码目录，跳过 GitHub 下载
  --no-run             安装完成后不立即启动
  -h, --help           显示帮助

App options:
  未识别的参数会原样透传给 auto_pool_maintainer.py。

Examples:
  curl -fsSL https://raw.githubusercontent.com/JnmHub/miniServerAutoRegister/main/install.sh | bash

  curl -fsSL https://raw.githubusercontent.com/JnmHub/miniServerAutoRegister/main/install.sh | \
    bash -s -- \
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

APP_ARGS=()
while (($# > 0)); do
  case "$1" in
    --install-dir)
      INSTALL_ROOT="$2"
      shift 2
      ;;
    --branch)
      REPO_BRANCH="$2"
      shift 2
      ;;
    --repo-owner)
      REPO_OWNER="$2"
      shift 2
      ;;
    --repo-name)
      REPO_NAME="$2"
      shift 2
      ;;
    --python-bin)
      PYTHON_BIN="$2"
      shift 2
      ;;
    --source-dir)
      SOURCE_DIR_OVERRIDE="$2"
      shift 2
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
  echo "[1/5] 使用本地源码: $SOURCE_DIR"
else
  ARCHIVE_URL="https://codeload.githubusercontent.com/${REPO_OWNER}/${REPO_NAME}/tar.gz/refs/heads/${REPO_BRANCH}"
  ARCHIVE_PATH="${TMP_DIR}/repo.tar.gz"
  echo "[1/5] 下载源码: $ARCHIVE_URL"
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

echo "[2/5] 创建虚拟环境: $VENV_DIR"
"$PYTHON_BIN" -m venv "$VENV_DIR"

echo "[3/5] 安装依赖"
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install -r "$APP_DIR/requirements.txt"

echo "[4/5] 安装完成"
echo "安装目录: $INSTALL_ROOT"
echo "程序目录: $APP_DIR"
echo "运行目录: $RUNTIME_DIR"
echo "配置文件: $CONFIG_PATH"

if [[ "$RUN_AFTER_INSTALL" -eq 0 ]]; then
  echo "[5/5] 已跳过启动（--no-run）"
  exit 0
fi

echo "[5/5] 启动程序"
cd "$RUNTIME_DIR"
exec "$VENV_DIR/bin/python" "$APP_DIR/auto_pool_maintainer.py" \
  --config "$CONFIG_PATH" \
  --log-dir "$LOG_DIR" \
  "${APP_ARGS[@]}"
