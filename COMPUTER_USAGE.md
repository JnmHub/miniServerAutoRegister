# 电脑使用帮助

本仓库现在支持两类本地操作：

1. 按 `serve_list.csv` 批量启动多个 `origin.py` 进程
2. 按 `serve_list.csv` 统计每个 CPA 服务当前的文件数量

所有启动脚本都默认：

- 使用全局 Python
- 启动前自动安装 `requirements.txt`
- 直接在当前电脑上执行

## 一、批量启动

### macOS

```bash
sh run_a_py_macos.sh
```

### Linux

```bash
sh run_a_py_linux.sh
```

### Windows

```bat
run_a_py.bat
```

默认会读取 `serve_list.csv`，每一行启动一个本地 `origin.py` 进程。

字段映射关系：

- `服务器ip` + `cpa端口` -> `--cpa-base-url http://IP:PORT`
- `cpa管理员key` -> `--cpa-token`
- `线程` -> `--workers`

如果想强制回到单进程模式：

### macOS

```bash
sh run_a_py_macos.sh --single
```

### Linux

```bash
sh run_a_py_linux.sh --single
```

### Windows

```bat
run_a_py.bat --single
```

## 二、查看每个 CSV 节点的文件数量

### macOS

```bash
sh show_serve_file_counts_macos.sh
```

### Linux

```bash
sh show_serve_file_counts_linux.sh
```

### Windows

```bat
show_serve_file_counts.bat
```

默认会读取 `serve_list.csv`，然后逐个请求：

```text
http://服务器ip:cpa端口/v0/management/auth-files
```

脚本会输出每个节点的：

- 服务器 IP
- 服务器配置
- 线程数
- 当前文件数量
- 请求状态

并在最后输出总计：

- 总节点数
- 成功数
- 失败数
- 文件总和

## 三、常用附加参数

文件数量统计脚本支持这些参数：

```bash
sh show_serve_file_counts_macos.sh --only 38.55.134.133,38.55.134.134
sh show_serve_file_counts_macos.sh --max-parallel 4
sh show_serve_file_counts_macos.sh --timeout 10
```

Linux 和 Windows 只需要把脚本名替换掉即可。

批量启动脚本支持这些参数，参数会继续透传给 `origin.py`：

```bash
sh run_a_py_macos.sh --only 38.55.134.133
sh run_a_py_macos.sh --max-parallel 3 --once
sh run_a_py_macos.sh --dry-run
```

说明：

- `--only` 和 `--max-parallel` 由批量调度脚本处理
- `--once`、`--proxy`、`--browser` 这类参数会继续传给每个 `origin.py`
- `--dry-run` 只打印将执行的命令，不真正启动

## 四、前提要求

- 电脑已安装全局 Python
- 全局 Python 能使用 `pip`
- `serve_list.csv` 存在且字段完整

CSV 必须至少包含这些列：

- `服务器ip`
- `cpa端口`
- `cpa管理员key`
- `线程`

## 五、故障排查

如果提示 Python 不存在：

- macOS / Linux：先安装 `python3`
- Windows：先安装 Python，并确保 `py` 或 `python` 在 PATH 中

如果统计文件数量时报错：

- 先确认对应 `服务器ip:cpa端口` 可以从当前电脑访问
- 再确认 `cpa管理员key` 是否正确

如果批量启动数量太多导致电脑压力大：

- 使用 `--max-parallel` 限制同时运行的进程数
