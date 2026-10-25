"""StudyTool -- Digest course materials into structured notes."""

import os
import re
import shutil
from pathlib import Path
from typing import Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field


class DigestCourseMaterialInput(BaseModel):
    file_path: str = Field(
        description="Path to the course material file (relative to project "
                    "root or absolute). Supported: .pptx, .pdf, .docx, .xlsx, "
                    "and plain text."
    )
    course_name: str = Field(
        default="",
        description="Course name for archiving, e.g. '计算机网络'. "
                    "Leave empty to put it in '_未分类'.",
    )
    extra_save_dir: str = Field(
        default="",
        description="Optional. If provided, also save a copy of the notes "
                    "to this directory. Can be absolute or relative to "
                    "project root. Leave empty to only save to "
                    "courses/{course_name}/.",
    )
    detail_level: str = Field(
        default="full",
        description="'brief' returns a short summary only. "
                    "'full' returns structured notes with key points, "
                    "keywords, and possible exam points.",
    )


class DigestCourseMaterialTool(BaseTool):
    """Read a course material file and produce structured notes."""
    name: str = "digest_course_material"
    description: str = ""
    args_schema: Type[BaseModel] = DigestCourseMaterialInput
    root_dir: str = ""

    def _read_source(self, file_path: str) -> str:
        """Read the source file using the same logic as read_rich_file."""
        from tools.rich_file_tool import RichFileReadTool

        reader = RichFileReadTool(root_dir=self.root_dir)
        return reader._run(file_path)

    def _digest(self, raw_text: str, file_name: str,
                detail_level: str) -> str:
        """Call LLM to produce structured notes."""
        from langchain_deepseek import ChatDeepSeek

        api_key = os.getenv("DEEPSEEK_API_KEY")
        base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        model_name = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        if not api_key:
            return "(无法生成笔记：DEEPSEEK_API_KEY 未设置)"

        llm = ChatDeepSeek(
            model=model_name,
            api_key=api_key,
            base_url=base_url,
            temperature=0.3,
        )

        if detail_level == "brief":
            prompt = (
                "下面是一份课程资料的内容。请用中文写一段简短概括，"
                "200 字以内，说清这份资料讲了什么。\n\n"
                f"文件名：{file_name}\n\n"
                f"内容：\n{raw_text}"
            )
        else:
            prompt = (
                "下面是一份课程资料的内容。请用中文把它整理成结构化的学习笔记，"
                "严格按以下 markdown 格式输出：\n\n"
                "## 一句话概括\n"
                "（一句话说清这份资料讲了什么）\n\n"
                "## 核心要点\n"
                "（分点列出，每点用「### 序号. 标题」格式，下面跟 2-4 行说明。"
                "如果原文里有表格，用 markdown 表格保留）\n\n"
                "## 关键词 / 术语\n"
                "（列出 5-10 个关键术语，每个一行）\n\n"
                "## 可能的考点\n"
                "（根据内容推断 3-5 个可能的考试点，每个一行）\n\n"
                "## 原文关键内容\n"
                "（摘录原文里最重要的段落，不要改写，原样保留）\n\n"
                "要求：\n"
                "- 不要客套话，直接输出\n"
                "- 不要编造原文没有的内容\n"
                "- 如果原文是英文，笔记用中文，但术语保留英文\n\n"
                f"文件名：{file_name}\n\n"
                f"内容：\n{raw_text}"
            )

        try:
            result = llm.invoke(prompt)
            return result.content.strip()
        except Exception as e:
            return f"(生成笔记失败：{e})"

    def _sanitize_name(self, name: str) -> str:
        """Clean a string for use as a file/folder name."""
        name = re.sub(r'[<>:"/\\|?*]', "_", name)
        name = re.sub(r"\s+", "_", name).strip("_")
        return name or "untitled"

    def _run(self, file_path: str, course_name: str = "",
             extra_save_dir: str = "",
             detail_level: str = "full") -> str:
        try:
            raw_text = self._read_source(file_path)
            if raw_text.startswith("File not found") or \
               raw_text.startswith("Access denied") or \
               raw_text.startswith("Not a file"):
                return f"❌ 无法读取文件：{raw_text}"

            src_path = Path(file_path)
            file_name = src_path.name
            file_stem = src_path.stem

            notes = self._digest(raw_text, file_name, detail_level)

            course_folder = self._sanitize_name(course_name) if course_name.strip() else "_未分类"
            out_dir = Path(self.root_dir) / "courses" / course_folder
            out_dir.mkdir(parents=True, exist_ok=True)

            safe_stem = self._sanitize_name(file_stem)
            out_file = out_dir / f"{safe_stem}_notes.md"

            header = (
                f"# {course_name or '未分类'}\n"
                f"## 来源：{file_name}\n\n"
                f"---\n\n"
            )
            out_file.write_text(header + notes, encoding="utf-8")

            # 额外保存目录
            extra_file = None
            if extra_save_dir.strip():
                try:
                    extra_dir = Path(extra_save_dir)
                    if not extra_dir.is_absolute():
                        extra_dir = Path(self.root_dir) / extra_dir
                    extra_dir = extra_dir.resolve()
                    extra_dir.mkdir(parents=True, exist_ok=True)
                    extra_file = extra_dir / f"{safe_stem}_notes.md"
                    extra_file.write_text(header + notes, encoding="utf-8")
                except Exception as e:
                    extra_file = f"(额外保存失败：{e})"

            preview = notes[:600] + ("..." if len(notes) > 600 else "")
            result_msg = (
                f"✅ 已消化：{file_name}\n"
                f"📁 保存位置：`{out_file}`\n"
            )
            if extra_file:
                if isinstance(extra_file, str) and extra_file.startswith("("):
                    result_msg += f"⚠️ {extra_file}\n"
                else:
                    result_msg += f"📁 额外保存：`{extra_file}`\n"
            result_msg += f"📝 笔记预览：\n\n{preview}"
            return result_msg

        except Exception as e:
            return f"❌ 消化失败：{str(e)}"


def create_digest_course_material_tool(base_dir: Path) -> DigestCourseMaterialTool:
    """Create tool for digesting course materials."""
    tool = DigestCourseMaterialTool(root_dir=str(base_dir))
    tool.description = (
        "【课堂资料消化】把一份课程资料（PPT / PDF / Word / Excel / 纯文本）"
        "读取后整理成结构化的学习笔记，保存到 courses/ 目录下。 "
        "适用场景：用户说'帮我整理这份讲义''把这份 PPT 变成笔记'"
        "'消化一下这个文件''把这份资料存到 XX 课'时。 "
        "参数：\n"
        "- file_path：文件路径（相对于项目根目录，或绝对路径）\n"
        "- course_name：课程名，如 '计算机网络'。留空则存到 '_未分类/'\n"
        "- extra_save_dir：可选。如果填了，会**额外**保存一份笔记到该目录。"
        "用户说'存到 XXX 目录'时填这个参数。支持绝对路径和相对路径\n"
        "- detail_level：'full'（默认）输出结构化笔记（要点+术语+考点+原文关键内容）；"
        "'brief' 只输出 200 字概括\n"
        "输出：笔记保存到 `courses/{课程名}/{文件名}_notes.md`，"
        "并在对话里返回一段预览。 "
        "注意：\n"
        "- 本工具只处理单个文件\n"
        "- 如果用户说'存到 XXX 目录'，**必须**用 extra_save_dir 参数，"
        "不要用 terminal 手动复制"
    )
    return tool