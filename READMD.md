# miniServerAutoRegister 一键启动说明

这个项目现在支持通过 `curl | bash` 的方式一键拉取、安装依赖并启动。

如果你不传任何业务参数，脚本会继续使用当前项目里的默认值，不会主动改动默认配置。

## 1. 直接启动

```bash
curl -fsSL https://raw.githubusercontent.com/JnmHub/miniServerAutoRegister/main/install.sh | bash
```

## 2. 带参数启动

注意：`curl | bash` 传参时要用 `bash -s --`。

```bash
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
```

## 3. 支持的业务参数

这些参数会透传给 `auto_pool_maintainer.py`。不传就保持默认值。

| 参数 | 说明 |
| --- | --- |
| `--cpa-base-url` / `--cpa-path` | CPA 接口地址，例如 `http://127.0.0.1:8317` |
| `--cpa-token` / `--cpa-password` | CPA Bearer Token 或密码 |
| `--account-password` / `--password` | 注册账号固定密码；不传则继续随机生成 |
| `--mail-mode` | 邮箱模式，支持 `config`、`self_hosted_messages_api`、`self_hosted_mail_api`、`duckmail`、`tempmail_lol`、`cfmail`、`yyds_mail` |
| `--mail-api` | 邮箱接口地址 |
| `--mail-domains` | 邮箱域名池，多个值用英文逗号分隔 |
| `--min-candidates` | 触发补号的阈值 |
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

## 4. install.sh 自己支持的参数

这些参数是给安装脚本本身用的，不是业务参数。

| 参数 | 说明 |
| --- | --- |
| `--install-dir` | 安装目录，默认 `~/.miniServerAutoRegister` |
| `--branch` | GitHub 分支，默认 `main` |
| `--repo-owner` | GitHub 仓库 owner，默认 `JnmHub` |
| `--repo-name` | GitHub 仓库名，默认 `miniServerAutoRegister` |
| `--python-bin` | 指定 Python 可执行文件，默认 `python3` |
| `--source-dir` | 使用本地源码目录，跳过 GitHub 下载 |
| `--no-run` | 只安装，不立即启动 |

示例：

```bash
bash install.sh --source-dir . --install-dir /tmp/mini-server --no-run
```

## 5. Linux / Ubuntu 说明

建议至少准备以下环境：

```bash
sudo apt-get update
sudo apt-get install -y curl tar python3 python3-venv
```

安装脚本会自动：

1. 下载项目源码
2. 创建虚拟环境
3. 安装 `requirements.txt`
4. 把运行配置保存到 `~/.miniServerAutoRegister/runtime/config.json`
5. 启动 `auto_pool_maintainer.py`

## 6. 运行目录

默认安装目录：

```bash
~/.miniServerAutoRegister
```

目录说明：

- `app/`：程序源码
- `runtime/config.json`：持久化配置
- `runtime/logs/`：日志目录
- `.venv/`：Python 虚拟环境

## 7. 本地直接运行

如果你已经在项目目录里，也可以直接运行：

```bash
python3 auto_pool_maintainer.py --help
```

或者：

```bash
bash install.sh --source-dir .
```
