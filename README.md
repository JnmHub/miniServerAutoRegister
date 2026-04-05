# miniServerAutoRegister

当前主入口是 `origin.py`。

`install.sh` 会优先使用 `origin.py` 启动当前版本，并兼容一部分旧参数别名。默认 CPA 地址是 `http://127.0.0.1:8317`。

## 快速开始

一键安装并按默认方式启动：

```bash
curl -fsSL https://raw.githubusercontent.com/JnmHub/miniServerAutoRegister/main/install.sh | bash
```

最简单推荐命令：

```bash
curl -fsSL https://raw.githubusercontent.com/JnmHub/miniServerAutoRegister/main/install.sh | \
  bash -s -- \
    --cpu-quota 50% \
    --memory-max 50% \
    --auto-workers
```

其他参数都不填时，会继续使用程序默认值。

带更多参数安装：

```bash
curl -fsSL https://raw.githubusercontent.com/JnmHub/miniServerAutoRegister/main/install.sh | \
  bash -s -- \
    --cpu-quota 50% \
    --memory-max 2G \
    --workers 50 \
    --cpa-base-url http://127.0.0.1:8317 \
    --cpa-token your-token \
    --proxy http://127.0.0.1:7890 \
    --target-tokens 100 \
    --run-retries 2 \
    --once
```

本地源码安装测试：

```bash
bash install.sh --source-dir . --no-run --workers 10 --once
```

## 当前启动方式

- 安装脚本默认在 Linux 且可用 `systemd` 时创建并启动 `mini-server-auto-register.service`
- 如果系统 Python 低于 3.10 或缺少 `venv`，安装脚本会自动尝试安装新版本 Python
- 当前仓库主程序是 `origin.py`，安装脚本会自动识别；只有旧仓库快照才会回退到 `auto_pool_maintainer.py`
- 当前默认 CPA URL 为 `http://127.0.0.1:8317`
- 当前默认代理为本地自动探测的 Clash/V2RayN 地址；传 `--proxy direct` 或 `--proxy off` 可关闭代理

## install.sh 参数

这些参数由安装脚本自己处理：

| 参数 | 说明 |
| --- | --- |
| `--install-dir` | 安装目录，默认 `~/.miniServerAutoRegister` |
| `--branch` | GitHub 分支，默认 `main` |
| `--repo-owner` | GitHub 仓库 owner，默认 `JnmHub` |
| `--repo-name` | GitHub 仓库名，默认 `miniServerAutoRegister` |
| `--python-bin` | 指定 Python 可执行文件，默认 `python3` |
| `--source-dir` | 使用本地源码目录，跳过 GitHub 下载 |
| `--use-systemd` | 是否启用 `systemd` 守护，默认 `true` |
| `--cpu-quota` | `systemd` CPU 限额，例如 `50%`、`80%` |
| `--memory-max` | `systemd` 内存限制，例如 `512M`、`1G` |
| `--service-name` | `systemd` 服务名，默认 `mini-server-auto-register` |
| `--no-run` | 只安装，不立即启动 |

## origin.py 常用参数

这些参数会传给当前主程序 `origin.py`：

| 参数 | 说明 |
| --- | --- |
| `--cpa-base-url` | CPA 上传服务地址，默认 `http://127.0.0.1:8317` |
| `--cpa-token` | CPA Bearer Token |
| `--proxy` | 代理地址；传 `direct` / `off` 可关闭 |
| `--once` | 只运行一次 |
| `--sleep-min` | 循环模式最短等待秒数 |
| `--sleep-max` | 循环模式最长等待秒数 |
| `--workers` | 并发线程数 |
| `--auto-workers` | 按可用 CPU 自动计算线程数 |
| `--mailbox-limit` | 邮箱申请阶段并发上限，`0` 表示不限制 |
| `--otp-limit` | 验证码轮询阶段并发上限，`0` 表示不限制 |
| `--register-limit` | 注册阶段并发上限，`0` 表示不限制 |
| `--run-retries` | 单个 worker 的整轮补跑次数 |
| `--target-tokens` | 当前进程目标产出数量，`0` 表示不限制 |
| `--experiment` | 开启实验分支 |
| `--experiment2` | 开启托管实验分支 |
| `--experiment2-profile` | 托管实验 profile |
| `--experiment2-family` | 托管实验 family |
| `--experiment2-domains` | 指定实验域名池 |
| `--experiment2-fresh-cloudvxz` | 自动生成新的 cloudvxz 域名池 |
| `--experiment2-fresh-count` | fresh cloudvxz 生成数量 |
| `--experiment2-fresh-lengths` | fresh cloudvxz 标签长度 |
| `--experiment2-accept-language` | 覆盖实验 Accept-Language |
| `--beta` | 开启 beta 域名池 |
| `--beta2` | 开启 beta2 域名池 |
| `--alpha` | 强制使用 infini-ai.eu.cc 子域邮箱 |
| `--skymail` | 优先使用 skymail/cloudmail |
| `--dropmail-pool` | `primary` / `backup` / `all` |
| `--legacy` | 使用旧邮箱链路 |
| `--no-blacklist` | 关闭 blacklist/quarantine 读写 |
| `--browser` | 开启 browser-assisted 模式 |
| `--low` | 兼容旧 low/original 模式 |

完整参数请直接查看：

```bash
python3 origin.py --help
```

## 推荐启动示例

单次执行：

```bash
python3 origin.py \
  --cpa-base-url http://127.0.0.1:8317 \
  --cpa-token your-token \
  --proxy direct \
  --workers 20 \
  --once
```

循环模式：

```bash
python3 origin.py \
  --cpa-base-url http://127.0.0.1:8317 \
  --cpa-token your-token \
  --proxy http://127.0.0.1:7890 \
  --workers 50 \
  --sleep-min 5 \
  --sleep-max 30
```

使用环境变量传 CPA：

```bash
CPA_BASE_URL=http://127.0.0.1:8317 \
CPA_TOKEN=your-token \
python3 origin.py --workers 20 --once
```

## 旧参数兼容

`install.sh` 兼容以下旧参数别名，并自动转换为当前参数：

| 旧参数 | 当前参数 |
| --- | --- |
| `--worker-count` | `--workers` |
| `--threads` | `--workers` |
| `--proxy-url` | `--proxy` |
| `--cpa-path` | `--cpa-base-url` |
| `--cpa-password` | `--cpa-token` |
| `--loop-mode false` | `--once` |
| `--use-proxy false` | `--proxy direct` |

以下旧参数在当前 `origin.py` 中已经不再支持；通过 `install.sh` 传入时会被忽略并输出提示：

- `--account-password`
- `--password`
- `--mail-mode`
- `--mail-api`
- `--mail-domains`
- `--min-candidates`
- `--clean-files`
- `--token-json-dir`
- `--config`
- `--log-dir`

## systemd 常用命令

系统服务：

```bash
systemctl status mini-server-auto-register.service
systemctl restart mini-server-auto-register.service
journalctl -u mini-server-auto-register.service -f
```

用户服务：

```bash
systemctl --user status mini-server-auto-register.service
systemctl --user restart mini-server-auto-register.service
journalctl --user -u mini-server-auto-register.service -f
```

## 安装目录

默认安装目录：

```bash
~/.miniServerAutoRegister
```

目录说明：

- `app/`：程序源码
- `runtime/`：运行目录
- `runtime/config.json`：安装脚本复制的运行配置文件
- `runtime/logs/`：日志目录
- `.venv/`：Python 虚拟环境
- `run.sh`：统一启动入口，`systemd` 和手动启动都走这个脚本

## 环境准备

Ubuntu / Debian 最低建议：

```bash
sudo apt-get update
sudo apt-get install -y curl tar systemd
```

如果系统仓库没有合适的 Python 版本，安装脚本会继续尝试：

1. 系统仓库安装 `python3.10+`
2. Ubuntu 下接入 `deadsnakes`
3. 回退到 `uv` 托管安装 Python 3.12
