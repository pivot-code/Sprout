"""MapTool -- Build a knowledge map from course notes."""

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field


class BuildKnowledgeMapInput(BaseModel):
    course_name: str = Field(
        default="",
        description="Optional. If provided, only process this course. "
                    "Leave empty to process all courses.",
    )
    save: bool = Field(
        default=True,
        description="Whether to save the map to maps/ directory.",
    )


class BuildKnowledgeMapTool(BaseTool):
    """Build a knowledge map from course notes."""
    name: str = "build_knowledge_map"
    description: str = ""
    args_schema: Type[BaseModel] = BuildKnowledgeMapInput
    root_dir: str = ""

    def _collect_notes(self, course_name: str) -> dict:
        """Return {course_name: combined_notes_text}."""
        root = Path(self.root_dir) / "courses"
        if not root.exists():
            return {}

        result = {}
        if course_name.strip():
            course_dir = root / course_name.strip()
            if not course_dir.exists():
                return {}
            dirs = [course_dir]
        else:
            dirs = [d for d in root.iterdir() if d.is_dir()]

        for d in dirs:
            parts = []
            for f in sorted(d.glob("*_notes.md")):
                try:
                    parts.append(f.read_text(encoding="utf-8"))
                except Exception:
                    continue
            if parts:
                text = "\n\n".join(parts)
                if len(text) > 12000:
                    text = text[:12000] + "\n...[已截断]"
                result[d.name] = text
        return result

    def _extract_concepts_and_relations(self, course: str,
                                        notes: str) -> dict:
        """Use LLM to extract concepts and relations from one course."""
        from langchain_deepseek import ChatDeepSeek

        api_key = os.getenv("DEEPSEEK_API_KEY")
        base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        model_name = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        if not api_key:
            return {"concepts": [], "relations": []}

        llm = ChatDeepSeek(
            model=model_name,
            api_key=api_key,
            base_url=base_url,
            temperature=0.3,
        )

        prompt = (
            f"下面是一门课程「{course}」的学习笔记。请从中提取"
            "**核心概念**和**概念之间的关系**。\n\n"
            "要求：\n"
            "- 概念：提取 5-10 个这门课最核心的概念，每个概念 2-8 个字，"
            "不要提取通用词（如'方法'、'问题'、'内容'）\n"
            "- 关系：只保留真正有信息量的关系，关系类型包括："
            "属于、对比、依赖、包含、应用、导致 等\n"
            "- 严格输出 JSON，不要有 markdown 代码块标记\n\n"
            "输出格式：\n"
            '{\n'
            '  "concepts": ["概念1", "概念2", ...],\n'
            '  "relations": [\n'
            '    {"from": "概念A", "type": "属于", "to": "概念B"},\n'
            '    ...\n'
            '  ]\n'
            '}\n\n'
            f"笔记内容：\n{notes}"
        )

        try:
            result = llm.invoke(prompt)
            text = result.content.strip()
            # 去掉可能的 markdown 代码块
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
            data = json.loads(text)
            return {
                "concepts": data.get("concepts", []),
                "relations": data.get("relations", []),
            }
        except Exception as e:
            print(f"[MapTool] 抽取「{course}」失败：{e}")
            return {"concepts": [], "relations": []}

    def _build_markdown(self, course_data: dict) -> str:
        """Build the markdown output."""
        today = datetime.now().strftime("%Y年%m月%d日")
        lines = [f"# 知识地图 · {today}", ""]

        # 概览
        total_concepts = sum(len(d["concepts"]) for d in course_data.values())
        total_relations = sum(len(d["relations"]) for d in course_data.values())
        lines.append("## 概览")
        lines.append(f"共 {len(course_data)} 门课，{total_concepts} 个概念，"
                     f"{total_relations} 条关系。")
        lines.append("")

        # 每门课
        for course, data in course_data.items():
            lines.append(f"## {course}")
            lines.append("")

            lines.append("### 概念")
            if data["concepts"]:
                for c in data["concepts"]:
                    lines.append(f"- {c}")
            else:
                lines.append("（未提取到概念）")
            lines.append("")

            lines.append("### 关系")
            if data["relations"]:
                for r in data["relations"]:
                    f = r.get("from", "")
                    t = r.get("type", "")
                    to = r.get("to", "")
                    if f and t and to:
                        lines.append(f"- {f} → {t} → {to}")
            else:
                lines.append("（未提取到关系）")
            lines.append("")

        return "\n".join(lines)

    def _run(self, course_name: str = "", save: bool = True) -> str:
        try:
            notes_by_course = self._collect_notes(course_name)
            if not notes_by_course:
                return (
                    "❌ 没有找到可用的课程笔记。\n"
                    "请先用 `digest_course_material` 消化一些资料。"
                )

            course_data = {}
            for course, notes in notes_by_course.items():
                print(f"[MapTool] 正在分析：{course}")
                course_data[course] = self._extract_concepts_and_relations(
                    course, notes
                )

            markdown = self._build_markdown(course_data)

            if save:
                root = Path(self.root_dir)
                out_dir = root / "maps"
                out_dir.mkdir(parents=True, exist_ok=True)
                stamp = datetime.now().strftime("%Y-%m-%d")
                out_file = out_dir / f"知识地图_{stamp}.md"
                out_file.write_text(markdown, encoding="utf-8")

                # 预览：前 1500 字符
                preview = markdown[:1500]
                if len(markdown) > 1500:
                    preview += "\n...[内容较长，完整版见文件]"

                return (
                    f"已生成知识地图。\n"
                    f"保存位置：`{out_file.relative_to(root)}`\n"
                    f"共 {len(course_data)} 门课。\n\n"
                    f"{preview}"
                )
            else:
                return markdown

        except Exception as e:
            return f"生成知识地图失败：{str(e)}"


def create_map_tool(base_dir: Path) -> BuildKnowledgeMapTool:
    """Create tool for building knowledge maps."""
    tool = BuildKnowledgeMapTool(root_dir=str(base_dir))
    tool.description = (
        "【知识地图生成】从课程笔记中提取核心概念和概念间的关系，"
        "生成一张结构化的知识地图。 "
        "适用场景：用户说'帮我梳理知识''生成知识地图'"
        "'我学的这些东西有什么关系''画一张知识图'时。 "
        "参数：\n"
        "- course_name：可选。只处理某门课。留空表示处理所有课程\n"
        "- save：是否保存到 maps/ 目录，默认 true\n"
        "输出：知识地图保存到 `maps/知识地图_{日期}.md`，"
        "包含每门课的概念列表和关系列表。 "
        "注意：本工具会调用 LLM 抽取概念，如果笔记很多，会比较慢。"
    )
    return tool