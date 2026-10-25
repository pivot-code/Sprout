"""Background Loop — OpenClaw 风格的定时任务调度器。

核心设计：
- 一个后台 loop 负责调度
- 每个定时功能 = 一个独立 async 函数
- 添加新任务只需：写函数 → 注册，无需改动原有代码
- 每个任务可以有自己的执行间隔
- 用户自定义任务存在 user_tasks.json，由 task_user_scheduler 统一调度
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Callable, Any


class BackgroundTask:
    """定时任务包装器。"""

    def __init__(
        self,
        name: str,
        func: Callable[..., Any],
        interval: float,
        description: str = "",
        *args,
        **kwargs
    ):
        self.name = name
        self.func = func
        self.interval = interval  # 秒
        self.description = description
        self.args = args
        self.kwargs = kwargs
        self.running = False
        self.task: asyncio.Task | None = None

    async def run(self):
        """任务执行循环。"""
        while self.running:
            try:
                if asyncio.iscoroutinefunction(self.func):
                    await self.func(*self.args, **self.kwargs)
                else:
                    self.func(*self.args, **self.kwargs)
            except Exception as e:
                print(f"[BackgroundTask:{self.name}] 错误: {e}")

            await asyncio.sleep(self.interval)

    def start(self):
        """启动任务。"""
        self.running = True
        self.task = asyncio.create_task(self.run())
        print(f"[BackgroundTask] 任务 [{self.name}] 已启动 (间隔 {self.interval}s)")

    def stop(self):
        """停止任务。"""
        self.running = False
        if self.task:
            self.task.cancel()
            print(f"[BackgroundTask] 任务 [{self.name}] 已停止")


class BackgroundLoop:
    """OpenClaw 风格的后台定时任务调度器。"""

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.running = False
        self.tasks: dict[str, BackgroundTask] = {}

    # ========================================================================
    # 👇 想加新定时任务，就在下面写一个新的 async 函数
    # ========================================================================

    async def task_check_skills(self):
        """示例任务：每30秒检查技能文件。"""
        skills_dir = self.base_dir / "skills"
        if skills_dir.exists():
            skill_count = len(list(skills_dir.glob("*/SKILL.md")))
            print(f"[定时任务] 当前有 {skill_count} 个技能")

    async def task_auto_save_memory(self):
        """示例任务：每60秒自动保存记忆。"""
        print("[定时任务] 自动保存记忆到磁盘")

    async def task_user_scheduler(self):
        """每60秒检查一次 user_tasks.json，执行到点的用户任务。"""
        import json
        from datetime import datetime

        tasks_file = self.base_dir / "user_tasks.json"
        if not tasks_file.exists():
            return

        try:
            config = json.loads(tasks_file.read_text(encoding="utf-8"))
        except Exception:
            return

        tasks = config.get("tasks", [])
        if not tasks:
            return

        now = datetime.now()
        changed = False

        for task in tasks:
            if not task.get("enabled", False):
                continue

            schedule = task.get("schedule", {})
            stype = schedule.get("type", "daily")

            should_run = False
            try:
                if stype == "daily":
                    time_str = schedule.get("time", "")
                    if time_str:
                        th, tm = map(int, time_str.split(":"))
                        target = now.replace(hour=th, minute=tm, second=0, microsecond=0)
                        if now >= target:
                            last_run = task.get("last_run", "")
                            if not last_run.startswith(now.strftime("%Y-%m-%d")):
                                should_run = True
                elif stype == "weekly":
                    weekday = int(schedule.get("weekday", 0))
                    time_str = schedule.get("time", "")
                    if time_str:
                        th, tm = map(int, time_str.split(":"))
                        target = now.replace(hour=th, minute=tm, second=0, microsecond=0)
                        if now.weekday() == weekday and now >= target:
                            last_run = task.get("last_run", "")
                            if not last_run.startswith(now.strftime("%Y-%m-%d")):
                                should_run = True
                elif stype == "interval":
                    minutes = int(schedule.get("minutes", 60))
                    last_run_str = task.get("last_run", "")
                    if not last_run_str:
                        should_run = True
                    else:
                        try:
                            last_run_dt = datetime.fromisoformat(last_run_str)
                            if (now - last_run_dt).total_seconds() >= minutes * 60:
                                should_run = True
                        except Exception:
                            should_run = True
            except Exception as e:
                print(f"[UserScheduler] 任务 {task.get('id')} 时间判断失败: {e}")
                continue

            if not should_run:
                continue

            action = task.get("action", "")
            params = task.get("params", {})
            name = task.get("name", task.get("id", "unknown"))
            print(f"[UserScheduler] 触发用户任务：{name}（{action}）")

            try:
                result = await self._run_user_action(action, params)
                print(f"[UserScheduler] 任务 {name} 完成：{str(result)[:120]}")
                self._add_notification(
                    title=name,
                    content=self._make_notification_summary(action, params, result),
                )
            except Exception as e:
                print(f"[UserScheduler] 任务 {name} 执行失败：{e}")
                self._add_notification(
                    title=name,
                    content=f"任务执行失败：{str(e)[:200]}",
                )
            finally:
                task["last_run"] = now.isoformat()
                changed = True

        if changed:
            try:
                tasks_file.write_text(
                    json.dumps(config, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except Exception as e:
                print(f"[UserScheduler] 写回 user_tasks.json 失败：{e}")

    def _make_notification_summary(self, action: str, params: dict, result: str) -> str:
        """根据 action 生成简短的通知内容。"""
        # fetch_arxiv：提取关键信息
        if action == "fetch_arxiv":
            query = params.get("query", "")
            max_results = params.get("max_results", 5)
            count = result.count("### ")
            saved_path = ""
            if "📁 已保存到：" in result:
                try:
                    saved_path = result.split("📁 已保存到：")[1].split("\n")[0].strip().strip("`")
                except Exception:
                    pass

            lines = ["已完成 arXiv 抓取"]
            if query:
                lines.append(f"关键词：{query}")
            lines.append(f"抓取数量：{count or max_results} 篇")
            if saved_path:
                lines.append(f"保存位置：{saved_path}")
            lines.append("")
            lines.append("详细内容请查看保存的文件。")
            return "\n".join(lines)

        # generate_study_report：提取保存路径
        if action == "generate_study_report":
            saved_path = ""
            if "reports/" in result:
                try:
                    saved_path = result.split("`")[1]
                except Exception:
                    pass
            lines = ["已完成学习报告生成"]
            if saved_path:
                lines.append(f"保存位置：{saved_path}")
            return "\n".join(lines)

        # 默认：截取前 200 字
        return f"任务完成：{str(result)[:200]}"

    def _add_notification(self, title: str, content: str):
        """写一条通知：既写 notifications.json，也写 sessions/notifications.json。"""
        import json
        import uuid
        from datetime import datetime

        now = datetime.now()
        notif_id = "notif_" + uuid.uuid4().hex[:8]
        notif_text = f"🔔 [{title}]\n{content}"
        ts = int(now.timestamp() * 1000)

        # 1. 写 notifications.json（用于未读提示）
        notif_file = self.base_dir / "notifications.json"
        try:
            if notif_file.exists():
                data = json.loads(notif_file.read_text(encoding="utf-8"))
            else:
                data = {"notifications": []}
        except Exception:
            data = {"notifications": []}

        notif = {
            "id": notif_id,
            "time": now.isoformat(),
            "title": title,
            "content": content,
            "read": False,
        }
        data["notifications"].append(notif)
        if len(data["notifications"]) > 50:
            data["notifications"] = data["notifications"][-50:]
        try:
            notif_file.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            print(f"[UserScheduler] 写通知失败：{e}")

        # 2. 写 sessions/notifications.json（通知会话）
        sess_file = self.base_dir / "sessions" / "notifications.json"
        try:
            if sess_file.exists():
                sess = json.loads(sess_file.read_text(encoding="utf-8"))
            else:
                sess = {
                    "id": "notifications",
                    "name": "🔔 通知",
                    "created_at": now.isoformat(),
                    "updated_at": now.isoformat(),
                    "messages": [],
                }

            sess["messages"].append({
                "role": "system",
                "content": notif_text,
                "time": ts,
            })
            sess["updated_at"] = now.isoformat()

            if len(sess["messages"]) > 100:
                sess["messages"] = sess["messages"][-100:]

            sess_file.write_text(
                json.dumps(sess, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            print(f"[UserScheduler] 写通知会话失败：{e}")

    async def _run_user_action(self, action: str, params: dict):
        """根据 action 名称找到对应工具并执行。"""
        tools_map = {}

        try:
            from tools.report_tool import create_study_report_tool
            tools_map["generate_study_report"] = create_study_report_tool(self.base_dir)
        except Exception:
            pass

        try:
            from tools.arxiv_tool import create_arxiv_tool
            tools_map["fetch_arxiv"] = create_arxiv_tool(work_dir=str(self.base_dir))
        except Exception:
            pass

        try:
            from tools.arxiv_tool import create_download_arxiv_pdf_tool
            tools_map["download_arxiv_pdf"] = create_download_arxiv_pdf_tool(work_dir=str(self.base_dir))
        except Exception:
            pass

        try:
            from tools.study_tool import create_digest_course_material_tool
            tools_map["digest_course_material"] = create_digest_course_material_tool(self.base_dir)
        except Exception:
            pass

        try:
            from tools.quiz_tool import create_quiz_tool
            tools_map["generate_quiz"] = create_quiz_tool(self.base_dir)
        except Exception:
            pass

        tool = tools_map.get(action)
        if not tool:
            raise ValueError(f"未知的 action：{action}")

        download_pdf = False
        if action == "fetch_arxiv":
            download_pdf = params.pop("download_pdf", False)

        result = await self._call_tool(tool, params)

        if download_pdf:
            pdf_tool = tools_map.get("download_arxiv_pdf")
            if pdf_tool:
                try:
                    pdf_result = await self._call_tool(pdf_tool, {"arxiv_ids": "all"})
                    result = str(result) + "\n\n---\n\n【PDF 下载结果】\n" + str(pdf_result)
                except Exception as e:
                    result = str(result) + f"\n\n【PDF 下载失败】{e}"

        return result

    async def _call_tool(self, tool, params: dict):
        """调用工具：异步工具直接 await，同步工具放到线程池。"""
        if asyncio.iscoroutinefunction(tool._run):
            return await tool._run(**params)
        else:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, lambda: tool._run(**params))

    # ========================================================================
    # 任务注册与管理
    # ========================================================================

    def register(
        self,
        name: str,
        func: Callable[..., Any],
        interval: float,
        description: str = "",
        *args,
        **kwargs
    ) -> BackgroundTask:
        """注册一个新任务。"""
        if name in self.tasks:
            print(f"[BackgroundLoop] 任务 [{name}] 已存在，先停止旧任务")
            self.tasks[name].stop()

        task = BackgroundTask(name, func, interval, description, *args, **kwargs)
        self.tasks[name] = task
        return task

    def start(self) -> None:
        """启动所有已注册的任务。"""
        self.running = True
        print("✅ BackgroundLoop 已启动")

        self.register("check_skills", self.task_check_skills, 30)
        self.register("auto_save_memory", self.task_auto_save_memory, 60)
        self.register("user_scheduler", self.task_user_scheduler, 60)

        self._load_tasks_from_folder()

        for task in self.tasks.values():
            task.start()

    def _load_tasks_from_folder(self) -> None:
        """从 tasks/ 文件夹加载所有任务。"""
        try:
            from tasks import scan_tasks
        except ImportError:
            return

        tasks_dir = self.base_dir / "tasks"
        task_infos = scan_tasks(tasks_dir)

        for task_info in task_infos:
            self.register(
                task_info["name"],
                task_info["func"],
                task_info["interval"],
                task_info.get("description", "")
            )

    def stop(self) -> None:
        """停止所有任务。"""
        self.running = False
        for task in self.tasks.values():
            task.stop()
        print("🛑 BackgroundLoop 已停止")

    def list_tasks(self) -> list[dict]:
        """列出所有任务状态。"""
        return [
            {
                "name": name,
                "running": task.running,
                "interval": task.interval,
                "description": task.description,
            }
            for name, task in self.tasks.items()
        ]


# 使用示例
if __name__ == "__main__":
    async def demo():
        loop = BackgroundLoop(Path("."))

        async def my_custom_task():
            print("🔔 自定义任务执行！")

        loop.register("my_task", my_custom_task, 5)
        loop.start()
        await asyncio.sleep(20)
        loop.stop()

    asyncio.run(demo())