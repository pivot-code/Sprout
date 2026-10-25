"""ReportTool -- Generate a study report from recent activity."""

import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field


class GenerateStudyReportInput(BaseModel):
    hours: int = Field(
        default=24,
        description="How many hours back to include. Default 24.",
    )
    save: bool = Field(
        default=True,
        description="Whether to save the report to reports/ directory.",
    )


class GenerateStudyReportTool(BaseTool):
    """Generate a study report from recent activity."""
    name: str = "generate_study_report"
    description: str = ""
    args_schema: Type[BaseModel] = GenerateStudyReportInput
    root_dir: str = ""

    def _recent_files(self, dir_path: Path, hours: int,
                      exts=(".md", ".json")) -> list:
        """Return files modified within the last N hours."""
        if not dir_path.exists():
            return []
        cutoff = time.time() - hours * 3600
        result = []
        for f in dir_path.rglob("*"):
            if not f.is_file():
                continue
            if exts and f.suffix.lower() not in exts:
                continue
            try:
                if f.stat().st_mtime >= cutoff:
                    result.append(f)
            except Exception:
                pass
        return result

    def _collect_log_topics(self, hours: int) -> list:
        """Extract recent conversation topics from memory/logs/*.jsonl."""
        logs_dir = Path(self.root_dir) / "memory" / "logs"
        if not logs_dir.exists():
            return []

        cutoff = datetime.now() - timedelta(hours=hours)
        user_messages = []

        for log_file in logs_dir.glob("*.jsonl"):
            try:
                for line in log_file.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except Exception:
                        continue
                    ts_str = entry.get("timestamp", "")
                    try:
                        ts = datetime.fromisoformat(ts_str)
                    except Exception:
                        continue
                    if ts < cutoff:
                        continue
                    msg = entry.get("message", {})
                    if msg.get("type") == "human":
                        content = msg.get("content", "").strip()
                        if content:
                            user_messages.append(content[:100])
            except Exception:
                continue

        return user_messages

    def _build_context(self, hours: int) -> dict:
        """Collect all recent activity into a structured context."""
        root = Path(self.root_dir)

        courses = self._recent_files(root / "courses", hours, (".md",))
        arxiv = self._recent_files(root / "arxiv_papers", hours, (".md", ".json"))
        reports = self._recent_files(root / "reports", hours, (".md",))
        topics = self._collect_log_topics(hours)

        return {
            "hours": hours,
            "courses": [str(f.relative_to(root)) for f in courses],
            "arxiv": [str(f.relative_to(root)) for f in arxiv],
            "reports": [str(f.relative_to(root)) for f in reports],
            "topics": topics,
        }

    def _generate(self, context: dict) -> str:
        """Call LLM to write the report."""
        from langchain_deepseek import ChatDeepSeek

        api_key = os.getenv("DEEPSEEK_API_KEY")
        base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        model_name = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        if not api_key:
            return "(无法生成报告：DEEPSEEK_API_KEY 未设置)"

        llm = ChatDeepSeek(
            model=model_name,
            api_key=api_key,
            base_url=base_url,
            temperature=0.5,
        )

        hours = context["hours"]
        courses_str = "\n".join(f"- {p}" for p in context["courses"]) or "（无）"
        arxiv_str = "\n".join(f"- {p}" for p in context["arxiv"]) or "（无）"
        topics_str = "\n".join(f"- {t}" for t in context["topics"]) or "（无）"

        today = datetime.now().strftime("%Y年%m月%d日")

        prompt = (
            f"请根据下面的学习活动数据，生成一份中文学习报告，"
            f"统计范围是过去 {hours} 小时。\n\n"
            f"今天的日期是：{today}。请在报告标题里使用这个日期，"
            f"不要自己编造其他日期。\n\n"
            "严格按以下 markdown 格式输出：\n\n"
            f"# 学习报告 · {today}\n\n"
            "## 概览\n"
            "（用一两句话概括这段时间的学习状态，不要罗列数字，要有判断）\n\n"
            "## 新增笔记\n"
            "（列出 courses/ 下新增的笔记文件，每条一行，说明它属于哪门课。如果没有，写'本次无新增'）\n\n"
            "## 论文追踪\n"
            "（列出 arxiv_papers/ 下新增的内容。如果没有，写'本次无新增'）\n\n"
            "## 对话主题\n"
            "（从下面的对话记录里提炼出用户这段时间问了什么、关心什么。"
            "不要逐条列出，要归纳成 2-4 个主题）\n\n"
            "## 建议\n"
            "（根据以上内容，给出 2-3 条下一步学习建议。要具体，不要空话）\n\n"
            "---\n\n"
            f"数据：\n\n"
            f"新增笔记文件：\n{courses_str}\n\n"
            f"新增论文相关文件：\n{arxiv_str}\n\n"
            f"用户最近的提问：\n{topics_str}\n"
        )

        try:
            result = llm.invoke(prompt)
            return result.content.strip()
        except Exception as e:
            return f"(生成报告失败：{e})"

    def _run(self, hours: int = 24, save: bool = True) -> str:
        try:
            context = self._build_context(hours)
            report = self._generate(context)

            if save:
                root = Path(self.root_dir)
                out_dir = root / "reports"
                out_dir.mkdir(parents=True, exist_ok=True)
                stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
                out_file = out_dir / f"{stamp}.md"
                out_file.write_text(report, encoding="utf-8")
                return f"✅ 报告已生成并保存到 `{out_file.relative_to(root)}`\n\n{report}"

            return report

        except Exception as e:
            return f"❌ 生成报告失败：{str(e)}"


def create_study_report_tool(base_dir: Path) -> GenerateStudyReportTool:
    """Create tool for generating study reports."""
    tool = GenerateStudyReportTool(root_dir=str(base_dir))
    tool.description = (
        "【学习报告生成】扫描最近一段时间的学习活动，生成一份结构化报告。 "
        "数据来源：courses/ 下的课程笔记、arxiv_papers/ 下的论文、"
        "memory/logs/ 下的对话记录。 "
        "适用场景：用户说'生成一份学习报告''我最近学了什么'"
        "'总结一下今天的活动'时。 "
        "参数：\n"
        "- hours：统计过去多少小时，默认 24\n"
        "- save：是否保存到 reports/ 目录，默认 true\n"
        "输出：报告会保存到 `reports/{时间戳}.md`，并在对话里返回全文。 "
        "报告包含：概览、新增笔记、论文追踪、对话主题、下一步建议。"
    )
    return tool