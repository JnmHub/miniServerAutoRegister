# miniServerAutoRegister 一键启动说明

这个项目现在支持通过 `curl | bash` 一键安装。

默认行为：

- Linux / Ubuntu 下优先使用 `systemd` 进程守护
- 默认自动拉起服务
- 如果系统 Python 低于 3.10，安装脚本会自动尝试安装 Python 3.10+
- 如果安装 Python 时碰到 `apt/dpkg` 锁，脚本会自动等待并重试
- 如果系统仓库或 PPA 无法提供 Python 3.10+，脚本会自动回退到 `uv` 托管安装 Python 3.12
- 如果 GitHub 的 `codeload` 下载异常，脚本会自动回退到 GitHub 官方归档链接，必要时再回退到 `git clone`
- 默认 CPA 地址为 `http://127.0.0.1:8317`
- 不传业务参数时，继续使用项目当前默认值，不会主动修改默认配置

## 1. 直接启动

```bash
curl -fsSL https://raw.githubusercontent.com/JnmHub/miniServerAutoRegister/main/install.sh | bash
```

systemctl restart mini-server-auto-register.service

默认会：

1. 下载源码
2. 检查 Python 版本，不满足时自动安装 Python 3.10+
3. 创建虚拟环境
4. 安装依赖
5. 生成启动脚本
6. 注册并启动 `systemd` 服务

## 2. 带参数启动

注意：`curl | bash` 传参时要用 `bash -s --`。

```bash
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
```

## 3. 新增参数说明

这几个是这次新增的重点参数：

| 参数 | 作用 | 默认值 |
| --- | --- | --- |
| `--worker-count` / `--threads` | 控制补号并发线程数 | 使用代码默认值 |
| `--use-systemd` | 是否使用 `systemd` 进行进程守护 | `true` |
| `--cpu-quota` | 设置 `systemd` 的 CPU 限额 | 不限制 |
| `--memory-max` | 设置 `systemd` 的内存上限 | 不限制 |

说明：

- `--worker-count` 是传给 Python 主程序的业务参数。
- `--use-systemd`、`--cpu-quota`、`--memory-max` 是安装脚本参数。
- `--cpu-quota` 和 `--memory-max` 只在启用 `systemd` 时生效。
- 如果当前环境不是 Linux，或者没有 `systemctl`，即使传了 `--use-systemd true`，也会自动回退为直接启动模式。

示例 1：启用 `systemd` 守护，并限制资源

```bash
curl -fsSL https://raw.githubusercontent.com/JnmHub/miniServerAutoRegister/main/install.sh | \
  bash -s -- \
    --use-systemd true \
    --cpu-quota 80% \
    --memory-max 3G \
    --worker-count 50
```

示例 2：不使用 `systemd`，直接运行

```bash
curl -fsSL https://raw.githubusercontent.com/JnmHub/miniServerAutoRegister/main/install.sh | \
  bash -s -- \
    --use-systemd false \
    --worker-count 20
```

## 4. 支持的业务参数

这些参数会透传给 `auto_pool_maintainer.py`。不传就保持默认值。

| 参数 | 说明 |
| --- | --- |
| `--cpa-base-url` / `--cpa-path` | CPA 接口地址，例如 `http://127.0.0.1:8317` |
| `--cpa-token` / `--cpa-password` | CPA Bearer Token 或密码 |
| `--account-password` / `--password` | 注册账号固定密码；不传则继续随机生成 |
| `--worker-count` / `--threads` | 补号并发线程数 |
| `--mail-mode` | 邮箱模式，支持 `config`、`self_hosted_messages_api`、`self_hosted_mail_api`、`duckmail`、`tempmail_lol`、`cfmail`、`yyds_mail` |
| `--mail-api` | 邮箱接口地址 |
| `--mail-domains` | 邮箱域名池，多个值用英文逗号分隔 |
| `--min-candidates` | 补号触发阈值 |
| `--loop-mode` | 是否开启循环模式，填 `true` 或 `false` |
| `--loop` | 强制开启循环模式 |
| `--once` | 强制单次执行 |
| `--clean-files` | 是否先清理问题文件，填 `true` 或 `false` |
| `--use-proxy` | 是否使用代理，填 `true` 或 `false` |
| `--proxy-url` / `--proxy` | 代理地址，例如 `http://127.0.0.1:7890` |
| `--token-json-dir` | token JSON 本地保存目录 |
| `--log-dir` | 日志目录 |
| `--config` | 自定义配置文件路径 |

说明：

- `--use-proxy true` 时，建议同时传 `--proxy-url`。如果不传，就要求配置文件里已经有 `run.proxy`。
- `--loop` / `--once` 和 `--loop-mode` 都能控制循环模式；如果都不传，就继续使用代码默认值。

## 5. install.sh 自己支持的参数

这些参数由安装脚本处理，不会传给 Python 主程序。

| 参数 | 说明 |
| --- | --- |
| `--install-dir` | 安装目录，默认 `~/.miniServerAutoRegister` |
| `--branch` | GitHub 分支，默认 `main` |
| `--repo-owner` | GitHub 仓库 owner，默认 `JnmHub` |
| `--repo-name` | GitHub 仓库名，默认 `miniServerAutoRegister` |
| `--python-bin` | 指定 Python 可执行文件，默认 `python3` |
| `--source-dir` | 使用本地源码目录，跳过 GitHub 下载 |
| `--use-systemd` | 是否启用 `systemd` 守护，默认 `true` |
| `--cpu-quota` | `systemd` CPU 限制，例如 `50%`、`80%` |
| `--memory-max` | `systemd` 内存限制，例如 `512M`、`1G`、`2G` |
| `--service-name` | `systemd` 服务名，默认 `mini-server-auto-register` |
| `--no-run` | 只安装，不立即启动 |

示例：

```bash
bash install.sh --source-dir . --install-dir /tmp/mini-server --use-systemd false --no-run
```

## 6. systemd 守护说明

默认在 Linux / Ubuntu 下启用 `systemd` 守护。

服务特性：

- `Restart=always`
- 支持 `CPUQuota`
- 支持 `MemoryMax`
- 开机自启

如果当前环境不是 Linux，或者没有 `systemctl`，安装脚本会自动回退为直接启动模式。

常用命令：

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

## 7. Linux / Ubuntu 环境准备

建议至少准备以下环境：

```bash
sudo apt-get update
sudo apt-get install -y curl tar systemd
```

说明：

- `python3` 不再是必须前置条件。
- 如果机器只有 `Python 3.8` 或者根本没装合适版本，安装脚本会自动尝试安装 `Python 3.10+` 和对应的 `venv` 包。
- 在 Ubuntu 上，脚本会优先使用系统仓库；如果系统仓库没有合适版本，会自动尝试接入 `deadsnakes` 并安装。
- 如果系统正在跑 `unattended-upgrades` 占用 `dpkg` 锁，脚本会自动等待锁释放后继续安装。
- 如果 `apt + deadsnakes` 仍然拿不到可用的 Python 包，脚本会自动安装 `uv`，再用 `uv` 安装受管的 Python 3.12。

## 8. 运行目录

默认安装目录：

```bash
~/.miniServerAutoRegister
```

目录说明：

- `app/`：程序源码
- `runtime/config.json`：持久化配置
- `runtime/logs/`：日志目录
- `.venv/`：Python 虚拟环境
- `run.sh`：统一启动脚本，`systemd` 和手动启动都走这个入口

## 9. 本地直接运行

查看主程序参数：

```bash
python3 auto_pool_maintainer.py --help
```

本地源码安装测试：

```bash
bash install.sh --source-dir . --no-run
```


查看状态: systemctl status mini-server-auto-register.service
重启服务: systemctl restart mini-server-auto-register.service
查看日志: journalctl -u mini-server-auto-register.service -f
