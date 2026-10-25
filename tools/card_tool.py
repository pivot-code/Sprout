"""CardTool -- Generate knowledge cards from course notes for review."""

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field


class GenerateCardsInput(BaseModel):
    course_name: str = Field(
        description="Course name, e.g. '智能感知技术'. Required. "
                    "Cards are generated only from courses/{course_name}/."
    )
    source_file: str = Field(
        default="",
        description="Optional. If provided, only generate cards from this "
                    "specific notes file (e.g. '5.电感式传感器_notes.md'). "
                    "Leave empty to process all notes in the course.",
    )
    cards_per_note: int = Field(
        default=5,
        description="How many cards to generate per notes file. Default 5.",
    )
    save: bool = Field(
        default=True,
        description="Whether to save cards to cards/ directory.",
    )


class GenerateCardsTool(BaseTool):
    """Generate knowledge cards from course notes."""
    name: str = "generate_cards"
    description: str = ""
    args_schema: Type[BaseModel] = GenerateCardsInput
    root_dir: str = ""

    def _find_notes(self, course_name: str, source_file: str) -> list:
        """Return list of note file paths."""
        course_dir = Path(self.root_dir) / "courses" / course_name.strip()
        if not course_dir.exists():
            return []

        if source_file.strip():
            f = course_dir / source_file.strip()
            if f.exists() and f.suffix == ".md":
                return [f]
            return []

        return sorted(course_dir.glob("*_notes.md"))

    def _generate_cards(self, notes_text: str, note_name: str,
                        num_cards: int) -> str:
        from langchain_deepseek import ChatDeepSeek

        api_key = os.getenv("DEEPSEEK_API_KEY")
        base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        model_name = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        if not api_key:
            return "(无法生成卡片：DEEPSEEK_API_KEY 未设置)"

        llm = ChatDeepSeek(
            model=model_name,
            api_key=api_key,
            base_url=base_url,
            temperature=0.4,
        )

        # 截断过长的笔记
        if len(notes_text) > 12000:
            notes_text = notes_text[:12000] + "\n...[已截断]"

        prompt = (
            f"下面是一份课程笔记（{note_name}）。请把它拆成 {num_cards} 张"
            "**知识卡片**，用于复习。\n\n"
            "每张卡片是一个问答对（Q/A），格式如下：\n\n"
            "### 卡片 N\n"
            "**Q:** （问题）\n"
            "**A:** （答案）\n\n"
            "要求：\n"
            "- 每张卡片只覆盖**一个知识点**，不要一张卡塞多个\n"
            "- 问题要具体，能直接回答，不要是'请解释XX'这种开放式\n"
            "- 答案要简洁，1-3 句，抓住核心\n"
            "- 优先提取**容易考、容易忘**的知识点\n"
            "- 覆盖不同知识点，不要重复\n"
            "- 卡片之间不要有依赖（单独看一张也能理解）\n"
            "- 用中文，专业术语可保留英文\n"
            "- 严格按上面的 markdown 格式输出\n\n"
            f"笔记内容：\n{notes_text}"
        )

        try:
            result = llm.invoke(prompt)
            return result.content.strip()
        except Exception as e:
            return f"(生成卡片失败：{e})"

    def _sanitize(self, name: str, max_len: int = 60) -> str:
        name = re.sub(r'[<>:"/\\|?*]', "_", name)
        name = re.sub(r"\s+", "_", name).strip("_")
        return name[:max_len] or "untitled"

    def _run(self, course_name: str, source_file: str = "",
             cards_per_note: int = 5, save: bool = True) -> str:
        try:
            course_name = course_name.strip()
            if not course_name:
                return "❌ 请指定课程名，例如'智能感知技术'。"

            note_files = self._find_notes(course_name, source_file)
            if not note_files:
                if source_file.strip():
                    return (
                        f"❌ 在 courses/{course_name}/ 下找不到笔记文件："
                        f"{source_file}"
                    )
                return (
                    f"❌ 课程「{course_name}」下还没有笔记。\n"
                    f"请先用 `digest_course_material` 消化一些资料。"
                )

            all_cards = []
            for nf in note_files:
                try:
                    notes_text = nf.read_text(encoding="utf-8")
                except Exception:
                    continue

                print(f"[CardTool] 正在为 {nf.name} 生成卡片...")
                cards_md = self._generate_cards(
                    notes_text, nf.name, cards_per_note
                )

                header = f"\n\n---\n\n## 来源：{nf.name}\n\n"
                all_cards.append(header + cards_md)

            full_text = (
                f"# 知识卡片 · {course_name}\n\n"
                f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
                f"共 {len(note_files)} 份笔记，每份 {cards_per_note} 张卡片\n"
                + "".join(all_cards)
            )

            if save:
                root = Path(self.root_dir)
                safe_course = self._sanitize(course_name)
                out_dir = root / "cards" / safe_course
                out_dir.mkdir(parents=True, exist_ok=True)
                stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
                out_file = out_dir / f"{stamp}_cards.md"
                out_file.write_text(full_text, encoding="utf-8")

                # 预览：前 1200 字符
                preview = full_text[:1200]
                if len(full_text) > 1200:
                    preview += "\n...[完整内容见文件]"

                return (
                    f"已生成知识卡片：{course_name}\n"
                    f"来源：{len(note_files)} 份笔记，共约 "
                    f"{len(note_files) * cards_per_note} 张卡片\n"
                    f"保存位置：`{out_file.relative_to(root)}`\n\n"
                    f"{preview}"
                )
            else:
                return full_text

        except Exception as e:
            return f"❌ 生成知识卡片失败：{str(e)}"


def create_card_tool(base_dir: Path) -> GenerateCardsTool:
    """Create tool for generating knowledge cards."""
    tool = GenerateCardsTool(root_dir=str(base_dir))
    tool.description = (
        "【知识卡片生成】从课程笔记中提取知识点，生成可用于复习的问答卡片。 "
        "适用场景：用户说'帮我做知识卡片''把笔记变成复习卡片'"
        "'生成 XX 课的复习卡片'时。 "
        "参数：\n"
        "- course_name（必填）：课程名，如 '智能感知技术'。"
        "只从 courses/{课程名}/ 下生成\n"
        "- source_file：可选。只从某一份笔记生成卡片\n"
        "- cards_per_note：每份笔记生成几张卡片，默认 5\n"
        "- save：是否保存到 cards/ 目录，默认 true\n"
        "输出：卡片保存到 `cards/{课程名}/{时间戳}_cards.md`，"
        "包含多张问答卡片。 "
        "重要：本工具**只从课程笔记（courses/）生成卡片**，"
        "不处理论文（papers/）或其他资料。"
    )
    return tool