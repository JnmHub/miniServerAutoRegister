import requests
from pathlib import Path
from datetime import datetime, timezone, timedelta
import threading
import time


class ZeaburAuthFileManager:
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.log_path = Path(__file__).resolve().with_name("cleanup_error.log")
        self.session = requests.Session()
        self.session.headers.update({
            "accept": "application/json, text/plain, */*",
            "authorization": f"Bearer {token}",
            "referer": "https://jnm.zeabur.app/management.html",
            "user-agent": "Mozilla/5.0"
        })

    # ================= 上传 =================
    def upload(self, token_dir: str, file_name: str):
        print(f"保存文件 开始上传文件：{file_name}")
        url = f"{self.base_url}/v0/management/auth-files"
        file_path = Path(token_dir) / file_name

        if not file_path.exists():
            raise FileNotFoundError(f"{file_path} 不存在")

        with open(file_path, "rb") as f:
            files = {"file": (file_name, f, "application/json")}
            response = self.session.post(url, files=files)

        data = self._handle_response(response)
        success = response.status_code == 200 and data.get("status") == "ok"

        if success:
            print(f"✈️ 上传成功：{file_name}")
        else:
            print(f"❌ 上传失败：{file_name}")
        file_path.unlink(missing_ok=True)
        return success, data
    # def _ban_file(self, file_name: str):
    #     url = f"{self.base_url}/v0/management/auth-files/status"
    #     data = {"disabled": True,"name": file_name}
    #     response = self.session.post(url, json=data)
    #     data = self._handle_response(response)
    #     if response.status_code == 200 and data.get("status") == "ok":
    #         print(f"✅ 禁用成功：{file_name}")
    #     else:
    #         print(f"❌ 禁用失败：{file_name}")
    # ================= 删除 =================
    def delete(self, file_name: str):
        url = f"{self.base_url}/v0/management/auth-files"
        response = self.session.delete(url, params={"name": file_name})

        data = self._handle_response(response)

        if response.status_code == 200 and data.get("status") == "ok":
            print(f"🗑 删除成功：{file_name}")
            return True, data
        else:
            print(f"❌ 删除失败：{file_name}")
            return False, data

    # ================= 获取所有 =================
    def list_files(self):
        url = f"{self.base_url}/v0/management/auth-files"
        response = self.session.get(url)

        data = self._handle_response(response)

        if response.status_code == 200:
            return data.get("files", [])
        else:
            print("❌ 获取列表失败")
            self._append_log(
                "获取文件列表失败",
                [
                    f"HTTP 状态码：{response.status_code}",
                    f"响应内容：{data}",
                ],
            )
            return []

    # ================= 检查错误 =================
    def check_error(self):
        """
        检查超过 401 的文件
        """
        files = self.list_files()
        print(f"\n🔎 开始检查异常状态文件... 当前共 {len(files)} 个文件\n")
        err1_num = 0
        xhigh_num = 0
        deleted_files = []
        error_files = []
        xhigh_files = []
        for file in files:
            file_name = file.get("name", "unknown")
            status = file.get("status", None)
            status_message = file.get("status_message", "")
            if status == "error" and ("401" in status_message or "usage_limit_reached" in status_message):
                err1_num += 1
                delete_ok, delete_resp = self.delete(file_name)
                error_info = {
                    "name": file_name,
                    "status": status,
                    "status_message": status_message,
                    "delete_success": delete_ok,
                    "delete_response": delete_resp,
                }
                error_files.append(error_info)
                deleted_files.append(error_info)
                continue
            elif 'level "xhigh"' in status_message:
                xhigh_num += 1
                xhigh_files.append(
                    {
                        "name": file_name,
                        "status": status,
                        "status_message": status_message,
                    }
                )

        print(f"\n检查完成！共 {len(files)} 个文件，{xhigh_num}个不能用高级思考 {err1_num}个错误了，删除\n")
        log_lines = [
            f"检查时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"文件总数：{len(files)}",
            f"删除数量：{err1_num}",
            f"高级思考受限数量：{xhigh_num}",
            f"当前可用数量：{len(files) - err1_num - xhigh_num}",
            "",
            "删除明细：",
        ]

        if deleted_files:
            for item in deleted_files:
                delete_result = "成功" if item["delete_success"] else "失败"
                log_lines.append(
                    f"- 文件：{item['name']}｜状态：{item['status']}｜原因：{item['status_message']}｜删除结果：{delete_result}"
                )
                if item["delete_response"]:
                    log_lines.append(f"  删除接口返回：{item['delete_response']}")
        else:
            log_lines.append("- 本次没有删除任何文件")

        log_lines.extend(["", "错误文件明细："])
        if error_files:
            for item in error_files:
                log_lines.append(
                    f"- 文件：{item['name']}｜状态：{item['status']}｜错误信息：{item['status_message']}"
                )
        else:
            log_lines.append("- 本次没有发现 401 或 usage_limit_reached 错误文件")

        log_lines.extend(["", "高级思考受限文件："])
        if xhigh_files:
            for item in xhigh_files:
                log_lines.append(
                    f"- 文件：{item['name']}｜状态：{item['status']}｜提示：{item['status_message']}"
                )
        else:
            log_lines.append("- 本次没有发现高级思考受限文件")

        self._append_log("错误检查结果", log_lines)
        return len(files)-err1_num-xhigh_num
    # ================= 统一处理响应 =================
    @staticmethod
    def _handle_response(response: requests.Response):
        try:
            return response.json()
        except Exception:
            return {}

    def _append_log(self, title: str, lines: list[str]):
        """
        以普通文本 .log 形式追加中文日志。
        """
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write("=" * 80 + "\n")
            f.write(f"时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"事件：{title}\n")
            f.write("-" * 80 + "\n")
            for line in lines:
                f.write(f"{line}\n")
            f.write("\n")


def _sync_limit_state(limit, valid_count: int):
    if hasattr(limit, "update") and callable(limit.update):
        limit.update(valid_count)
        return

    limit.go = valid_count < limit.limit
    if hasattr(limit, "valid_count"):
        limit.valid_count = valid_count


def _mark_limit_ready(limit):
    if hasattr(limit, "ready"):
        limit.ready.set()
    if hasattr(limit, "resume_event") and getattr(limit, "go", True):
        limit.resume_event.set()


def start_periodic_expired_check(
    manager: ZeaburAuthFileManager,
    limit,
    interval_seconds: int = 600,
    run_immediately: bool = True,
):
    """
    启动后台守护线程，按固定间隔执行过期检查。
    """

    def worker():
        if run_immediately:
            try:
                number = manager.check_error()
                _sync_limit_state(limit, number)
            except Exception as exc:
                _mark_limit_ready(limit)
                manager._append_log(
                    "定时任务首次执行失败",
                    [
                        "阶段：启动时立即执行",
                        f"错误信息：{exc}",
                    ],
                )
                print(f"❌ 首次执行 失败：{exc}")

        while True:
            time.sleep(interval_seconds)
            try:
                number = manager.check_error()
                _sync_limit_state(limit, number)
            except Exception as exc:
                _mark_limit_ready(limit)
                manager._append_log(
                    "定时任务周期执行失败",
                    [
                        f"执行间隔：{interval_seconds} 秒",
                        f"错误信息：{exc}",
                    ],
                )
                print(f"❌ 定时执行 失败：{exc}")

    thread = threading.Thread(
        target=worker,
        daemon=True,
        name="zeabur-auth-expired-checker",
    )
    thread.start()
    return thread
