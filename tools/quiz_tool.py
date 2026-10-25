"""QuizTool -- Generate self-test quizzes from course notes."""

import os
from datetime import datetime
from pathlib import Path
from typing import Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field


class GenerateQuizInput(BaseModel):
    course_name: str = Field(
        default="",
        description="Course name to generate quiz from, e.g. '智能感知技术'. "
                    "Leave empty to use all courses.",
    )
    num_questions: int = Field(
        default=5,
        description="How many questions to generate. Default 5.",
    )
    question_types: str = Field(
        default="choice,fill,short",
        description="Comma-separated question types. "
                    "Options: choice (单选题), fill (填空题), short (简答题). "
                    "Default: all three.",
    )
    save: bool = Field(
        default=True,
        description="Whether to save the quiz to quizzes/ directory.",
    )


class GenerateQuizTool(BaseTool):
    """Generate a self-test quiz from course notes."""
    name: str = "generate_quiz"
    description: str = ""
    args_schema: Type[BaseModel] = GenerateQuizInput
    root_dir: str = ""

    def _collect_notes(self, course_name: str) -> tuple[str, str]:
        """Return (course_label, combined_notes_text)."""
        root = Path(self.root_dir) / "courses"
        if not root.exists():
            return ("", "")

        if course_name.strip():
            course_dir = root / course_name.strip()
            if not course_dir.exists():
                return (course_name.strip(), "")
            note_files = sorted(course_dir.glob("*_notes.md"))
        else:
            note_files = sorted(root.rglob("*_notes.md"))

        if not note_files:
            return (course_name.strip() or "全部课程", "")

        parts = []
        for f in note_files:
            try:
                content = f.read_text(encoding="utf-8")
                parts.append(f"\n\n===== 来源：{f.name} =====\n\n{content}")
            except Exception:
                continue

        label = course_name.strip() if course_name.strip() else "全部课程"
        return (label, "\n".join(parts))

    def _generate(self, course_label: str, notes_text: str,
                  num_questions: int, question_types: str) -> str:
        """Call LLM to generate quiz questions and answers separately."""
        from langchain_deepseek import ChatDeepSeek

        api_key = os.getenv("DEEPSEEK_API_KEY")
        base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        model_name = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        if not api_key:
            return ""

        llm = ChatDeepSeek(
            model=model_name,
            api_key=api_key,
            base_url=base_url,
            temperature=0.5,
        )

        # 题型说明
        type_map = {
            "choice": "单选题",
            "fill": "填空题",
            "short": "简答题",
        }
        types = [t.strip() for t in question_types.split(",") if t.strip()]
        types_cn = "、".join(type_map.get(t, t) for t in types)

        # 限制笔记长度
        if len(notes_text) > 15000:
            notes_text = notes_text[:15000] + "\n...[内容过长，已截断]"

        # 出题
        prompt_questions = (
            f"下面是一门课程「{course_label}」的学习笔记。"
            f"请根据笔记内容，出 {num_questions} 道自测题，"
            f"题型包含：{types_cn}。\n\n"
            "要求：\n"
            "- 题目必须严格基于笔记内容，不要编造\n"
            "- 覆盖不同知识点，不要重复\n"
            "- 按题型分类，单选题在前，填空题其次，简答题最后\n"
            "- 用 markdown 格式输出\n\n"
            "输出格式（只输出题目，**不要包含答案**）：\n\n"
            f"# 自测题 · {course_label}\n\n"
            "## 一、单选题\n"
            "1. （题目）\n"
            "   A. ...\n"
            "   B. ...\n"
            "   C. ...\n"
            "   D. ...\n\n"
            "## 二、填空题\n"
            "1. （题目，用 ______ 表示空格）\n\n"
            "## 三、简答题\n"
            "1. （题目）\n\n"
            f"笔记内容：\n{notes_text}"
        )

        try:
            result_q = llm.invoke(prompt_questions)
            questions_text = result_q.content.strip()
        except Exception as e:
            return f"(出题失败：{e})"

        # 出答案
        prompt_answers = (
            "下面是一套自测题，请为每道题给出**标准答案和解析**。\n\n"
            "要求：\n"
            "- 单选题给出正确选项和解释\n"
            "- 填空题给出标准答案\n"
            "- 简答题给出答案要点\n"
            "- 解析必须基于下面的笔记内容，不要编造\n"
            "- 用 markdown 格式输出，题号要和题目对应\n\n"
            "输出格式（只输出答案）：\n\n"
            f"# 自测题答案 · {course_label}\n\n"
            "## 一、单选题\n"
            "1. **答案：** B\n"
            "   **解析：** ...\n\n"
            "## 二、填空题\n"
            "1. **答案：** ...\n"
            "   **解析：** ...\n\n"
            "## 三、简答题\n"
            "1. **答案要点：**\n"
            "   - ...\n"
            "   - ...\n"
            "   **解析：** ...\n\n"
            f"题目：\n{questions_text}\n\n"
            f"参考笔记：\n{notes_text}"
        )

        try:
            result_a = llm.invoke(prompt_answers)
            answers_text = result_a.content.strip()
        except Exception as e:
            answers_text = f"(答案生成失败：{e})"

        return questions_text + "\n\n---\n\n" + answers_text

    def _sanitize(self, name: str) -> str:
        import re
        name = re.sub(r'[<>:"/\\|?*]', "_", name)
        name = re.sub(r"\s+", "_", name).strip("_")
        return name or "untitled"

    def _run(self, course_name: str = "", num_questions: int = 5,
             question_types: str = "choice,fill,short",
             save: bool = True) -> str:
        try:
            course_label, notes_text = self._collect_notes(course_name)

            if not notes_text:
                return (
                    f"❌ 课程「{course_label}」还没有笔记。\n"
                    f"请先用 `digest_course_material` 消化一些资料，再来出题。"
                )

            full_text = self._generate(
                course_label, notes_text, num_questions, question_types
            )
            if not full_text or full_text.startswith("(出题失败"):
                return full_text or "❌ 出题失败"

            # 拆分题目和答案
            parts = full_text.split("\n---\n", 1)
            questions_part = parts[0].strip()
            answers_part = parts[1].strip() if len(parts) > 1 else ""

            if save:
                root = Path(self.root_dir)
                safe_course = self._sanitize(course_label)
                out_dir = root / "quizzes" / safe_course
                out_dir.mkdir(parents=True, exist_ok=True)
                stamp = datetime.now().strftime("%Y-%m-%d_%H%M")

                q_file = out_dir / f"{stamp}_quiz.md"
                a_file = out_dir / f"{stamp}_answers.md"
                q_file.write_text(questions_part, encoding="utf-8")
                if answers_part:
                    a_file.write_text(answers_part, encoding="utf-8")

                saved_msg = (
                    f"\n\n📁 已保存：\n"
                    f"- 题目：`{q_file.relative_to(root)}`\n"
                    f"- 答案：`{a_file.relative_to(root)}`"
                )
            else:
                saved_msg = ""

            # 返回给 Agent 的文本：题目 + 提示
            return (
                f"{questions_part}\n\n"
                f"（答案已{'保存到文件' if save else '生成'}，"
                f"用户做完题后可以说'看答案'，你再用 read_file 读取答案文件；"
                f"如果 save=false，则答案在下面：）\n\n"
                f"{answers_part if not save else ''}"
                f"{saved_msg}"
            )

        except Exception as e:
            return f"❌ 生成自测题失败：{str(e)}"


def create_quiz_tool(base_dir: Path) -> GenerateQuizTool:
    """Create tool for generating self-test quizzes."""
    tool = GenerateQuizTool(root_dir=str(base_dir))
    tool.description = (
        "【自测题生成】根据课程笔记自动生成一套自测题。 "
        "适用场景：用户说'出几道题''自测一下''帮我做个小测'"
        "'从 XX 课出题'时。 "
        "参数：\n"
        "- course_name：从哪门课出题，如 '智能感知技术'。留空表示从所有课程出题\n"
        "- num_questions：出几道题，默认 5\n"
        "- question_types：题型，逗号分隔，可选 choice（单选）/ fill（填空）/ short（简答），"
        "默认全出\n"
        "- save：是否保存到 quizzes/ 目录，默认 true\n"
        "行为：\n"
        "1. 读取 courses/{course_name}/ 下的所有 _notes.md\n"
        "2. 生成题目和答案（分开保存）\n"
        "3. 题目保存到 quizzes/{course_name}/{时间戳}_quiz.md\n"
        "4. 答案保存到 quizzes/{course_name}/{时间戳}_answers.md\n"
        "重要：\n"
        "- 对话里只展示题目，不要主动展示答案\n"
        "- 用户说'看答案'时，用 read_file 读取对应的 _answers.md\n"
        "- 如果课程还没有笔记，提示用户先用 digest_course_material 消化资料"
    )
    return tool