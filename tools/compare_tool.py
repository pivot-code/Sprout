"""CompareTool -- Compare two concepts side by side."""

import os
import re
from pathlib import Path
from typing import Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field


class CompareConceptsInput(BaseModel):
    concept_a: str = Field(description="First concept, e.g. 'TCP'")
    concept_b: str = Field(description="Second concept, e.g. 'UDP'")
    course_name: str = Field(
        default="",
        description="Optional. If provided, use notes from this course as reference.",
    )
    save: bool = Field(
        default=True,
        description="Whether to save the comparison to comparisons/ directory.",
    )


class CompareConceptsTool(BaseTool):
    """Compare two concepts."""
    name: str = "compare_concepts"
    description: str = ""
    args_schema: Type[BaseModel] = CompareConceptsInput
    root_dir: str = ""

    def _collect_notes(self, course_name: str) -> str:
        """Collect notes from courses/{course_name}/ if specified."""
        if not course_name.strip():
            return ""
        course_dir = Path(self.root_dir) / "courses" / course_name.strip()
        if not course_dir.exists():
            return ""
        parts = []
        for f in sorted(course_dir.glob("*_notes.md")):
            try:
                parts.append(f"\n===== {f.name} =====\n{f.read_text(encoding='utf-8')}")
            except Exception:
                continue
        text = "\n".join(parts)
        if len(text) > 12000:
            text = text[:12000] + "\n...[已截断]"
        return text

    def _compare(self, concept_a: str, concept_b: str, notes: str) -> str:
        from langchain_deepseek import ChatDeepSeek

        api_key = os.getenv("DEEPSEEK_API_KEY")
        base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        model_name = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        if not api_key:
            return "(无法生成对比：DEEPSEEK_API_KEY 未设置)"

        llm = ChatDeepSeek(
            model=model_name,
            api_key=api_key,
            base_url=base_url,
            temperature=0.3,
        )

        if notes:
            source_hint = (
                "请**优先**依据下面提供的课程笔记进行对比。"
                "如果笔记里没有某个维度的信息，可以用通用知识补充，"
                "但要标注'（补充自通用知识）'。\n\n"
                f"课程笔记：\n{notes}"
            )
        else:
            source_hint = "下面没有提供课程笔记，请基于通用知识进行对比。"

        prompt = (
            f"请对比「{concept_a}」和「{concept_b}」这两个概念，"
            "用中文输出一份结构化的对比文档。\n\n"
            f"{source_hint}\n\n"
            "严格按以下 markdown 格式输出：\n\n"
            f"# {concept_a} vs {concept_b}\n\n"
            "## 一句话区分\n"
            "（用一句话说清两者的核心区别）\n\n"
            "## 对比表\n"
            "（一个 markdown 表格，至少包含 5 个对比维度）\n\n"
            "## 详细对比\n"
            "（用「### 序号. 维度名」的格式分点展开，每个维度下面解释两者的差异）\n\n"
            "## 如何选择\n"
            "（在什么情况下用 A，什么情况下用 B）\n\n"
            "## 常见误区\n"
            "（列出 2-3 个关于这两个概念的常见误解）\n\n"
            "要求：\n"
            "- 表格里的内容要简洁，每格不超过 15 字\n"
            "- 不要客套话，直接输出\n"
            "- 不要编造笔记里没有的内容（如果用了通用知识，要标注）\n"
        )

        try:
            result = llm.invoke(prompt)
            return result.content.strip()
        except Exception as e:
            return f"(对比失败：{e})"

    def _sanitize(self, name: str) -> str:
        name = re.sub(r'[<>:"/\\|?*]', "_", name)
        name = re.sub(r"\s+", "_", name).strip("_")
        return name[:30] or "untitled"

    def _run(self, concept_a: str, concept_b: str,
             course_name: str = "", save: bool = True) -> str:
        try:
            notes = self._collect_notes(course_name)
            result = self._compare(concept_a, concept_b, notes)

            if save:
                root = Path(self.root_dir)
                out_dir = root / "comparisons"
                out_dir.mkdir(parents=True, exist_ok=True)
                safe_a = self._sanitize(concept_a)
                safe_b = self._sanitize(concept_b)
                out_file = out_dir / f"{safe_a}_vs_{safe_b}.md"

                header = ""
                if course_name.strip():
                    header = f"<!-- 来源课程：{course_name} -->\n\n"
                out_file.write_text(header + result, encoding="utf-8")

                return (
                    f"已生成对比：{concept_a} vs {concept_b}\n"
                    f"保存位置：`{out_file.relative_to(root)}`\n\n"
                    f"{result}"
                )
            else:
                return result

        except Exception as e:
            return f"生成对比失败：{str(e)}"


def create_compare_tool(base_dir: Path) -> CompareConceptsTool:
    """Create tool for comparing concepts."""
    tool = CompareConceptsTool(root_dir=str(base_dir))
    tool.description = (
        "【概念对比】对比两个概念，生成结构化对比文档。 "
        "适用场景：用户说'对比 A 和 B''A 和 B 有什么区别'"
        "'A 和 B 哪个好'时。 "
        "参数：\n"
        "- concept_a：第一个概念\n"
        "- concept_b：第二个概念\n"
        "- course_name：可选。如果提供了，会从这门课的笔记里找依据；"
        "留空则用通用知识\n"
        "- save：是否保存到 comparisons/ 目录，默认 true\n"
        "输出：对比文档保存到 `comparisons/{A}_vs_{B}.md`，并在对话里返回全文。 "
        "对比文档包含：一句话区分、对比表、详细对比、如何选择、常见误区。"
    )
    return tool