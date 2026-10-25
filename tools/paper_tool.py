"""PaperTool -- Analyze a research paper PDF into structured notes."""

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field


class AnalyzePaperInput(BaseModel):
    file_path: str = Field(
        description="Path to the paper PDF (relative to project root, or absolute)."
    )
    depth: str = Field(
        default="full",
        description="'brief' for a quick read-worthiness check. "
                    "'full' for a complete structured analysis.",
    )
    save: bool = Field(
        default=True,
        description="Whether to save the analysis to papers/ directory.",
    )


class AnalyzePaperTool(BaseTool):
    """Read a paper PDF and produce a structured analysis."""
    name: str = "analyze_paper"
    description: str = ""
    args_schema: Type[BaseModel] = AnalyzePaperInput
    root_dir: str = ""

    # PDF 阅读上限（比通用 read_rich_file 更高，因为论文通常更长）
    MAX_PDF_CHARS: int = 50000
    MAX_PDF_PAGES: int = 60

    def _read_pdf(self, file_path: str):
        """Return (raw_text, error_msg). Reads PDF with a higher char limit."""

        # 解析路径（和 read_rich_file 一致）
        root = Path(self.root_dir)
        normalized = file_path.replace("\\", "/").lstrip("./")
        if Path(file_path).is_absolute():
            full_path = Path(file_path).resolve()
        else:
            full_path = (root / normalized).resolve()

        # 沙盒检查
        if self.root_dir and not str(full_path).startswith(str(root.resolve())):
            upload_dir = root / "uploads"
            if not str(full_path).startswith(str(upload_dir.resolve())):
                return ("", "访问被拒绝：路径超出允许范围")

        if not full_path.exists():
            return ("", f"找不到文件：{file_path}")
        if not full_path.is_file():
            return ("", f"不是一个文件：{file_path}")

        ext = full_path.suffix.lower()
        if ext != ".pdf":
            return ("", "本工具只处理 PDF 文件")

        try:
            from PyPDF2 import PdfReader
            reader = PdfReader(str(full_path))
            lines = []
            for i, page in enumerate(reader.pages[:self.MAX_PDF_PAGES]):
                text = page.extract_text()
                if text:
                    lines.append(f"--- Page {i+1} ---\n{text}")
            content = "\n\n".join(lines)

            if len(content.strip()) < 200:
                return ("", "PDF 内容过少，可能是扫描版或图片型 PDF，无法提取文字")

            if len(content) > self.MAX_PDF_CHARS:
                content = content[:self.MAX_PDF_CHARS] + "\n...[truncated]"

            return (content, "")
        except Exception as e:
            return ("", f"读取 PDF 失败：{e}")

    def _analyze(self, raw_text: str, file_name: str,
                 depth: str) -> str:
        from langchain_deepseek import ChatDeepSeek

        api_key = os.getenv("DEEPSEEK_API_KEY")
        base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        model_name = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        if not api_key:
            return "(无法生成解读：DEEPSEEK_API_KEY 未设置)"

        llm = ChatDeepSeek(
            model=model_name,
            api_key=api_key,
            base_url=base_url,
            temperature=0.3,
        )

        # 检测是否被截断
        truncated = "[truncated]" in raw_text
        truncation_note = (
            "\n\n【注意】本文档较长，只读到了前部分，"
            "请在解读里明确说明'本解读基于文档前部分内容'。"
            if truncated else ""
        )

        if depth == "brief":
            prompt = (
                "下面是一篇论文的内容。请用中文输出一份**简短**的解读，"
                "严格按以下 markdown 格式：\n\n"
                "# {标题}\n\n"
                "## 一句话概括\n"
                "（一句话说清这篇论文做了什么）\n\n"
                "## 研究问题\n"
                "（它想解决什么问题，2-3 句）\n\n"
                "## 主要贡献\n"
                "（它做成了什么，2-4 点）\n\n"
                "## 值不值得读\n"
                "（针对一个学生读者，判断这篇论文对他的价值，2-3 句）\n\n"
                "要求：\n"
                "- 总字数 300 字以内\n"
                "- 不要客套话，直接输出\n"
                "- 不要编造原文没有的内容\n"
                f"{truncation_note}\n\n"
                f"文件名：{file_name}\n\n"
                f"内容：\n{raw_text}"
            )
        else:
            prompt = (
                "下面是一篇论文的内容。请用中文输出一份**完整**的结构化解读，"
                "严格按以下 markdown 格式：\n\n"
                "# 论文解读：{标题}\n\n"
                "## 元信息\n"
                "- 标题：...\n"
                "- 作者：...\n"
                "- 来源文件：...\n\n"
                "## 一句话概括\n"
                "（一句话说清这篇论文做了什么）\n\n"
                "## 研究问题\n"
                "（它想解决什么问题？为什么这个问题重要？3-5 句）\n\n"
                "## 核心方法\n"
                "（它用了什么方法？关键思路是什么？分点说清，"
                "尽量保留原文的关键步骤和公式定义）\n\n"
                "## 主要贡献\n"
                "（做成了什么？和已有工作相比新在哪里？分点列出）\n\n"
                "## 实验 / 验证\n"
                "（怎么证明方法有效？在什么数据上、和什么对比？"
                "尽量保留关键实验数据，比如数据集名称、指标数值）\n\n"
                "## 局限 / 未解决的问题\n"
                "（作者提到的局限，以及你观察到的不足）\n\n"
                "## 可借鉴的点\n"
                "（对读者来说，这篇论文的哪些思路/方法/结论可以用到自己的工作里？"
                "3-5 点）\n\n"
                "## 关键术语\n"
                "（列出 5-10 个关键术语，每个一行，中英对照）\n\n"
                "## 原文关键段落\n"
                "（摘录原文里最重要的 5-8 段，优先选择方法、实验、结论相关的段落，"
                "原样保留，不要改写）\n\n"
                "要求：\n"
                "- 不要客套话，直接输出\n"
                "- 不要编造原文没有的内容\n"
                "- 如果原文是英文，解读用中文，术语保留英文\n"
                f"{truncation_note}\n\n"
                f"文件名：{file_name}\n\n"
                f"内容：\n{raw_text}"
            )

        try:
            result = llm.invoke(prompt)
            return result.content.strip()
        except Exception as e:
            return f"(生成解读失败：{e})"

    def _sanitize(self, name: str, max_len: int = 60) -> str:
        name = re.sub(r'[<>:"/\\|?*]', "_", name)
        name = re.sub(r"\s+", "_", name).strip("_")
        return name[:max_len] or "untitled"

    def _run(self, file_path: str, depth: str = "full",
             save: bool = True) -> str:
        try:
            # 1. 读取 PDF
            raw_text, err = self._read_pdf(file_path)
            if err:
                return f"❌ {err}"

            # 2. 基本信息
            src_path = Path(file_path)
            file_name = src_path.name
            file_stem = src_path.stem

            # 3. 调 LLM 解读
            analysis = self._analyze(raw_text, file_name, depth)

            # 4. 落盘
            if save:
                root = Path(self.root_dir)
                out_dir = root / "papers"
                out_dir.mkdir(parents=True, exist_ok=True)
                safe_stem = self._sanitize(file_stem)
                out_file = out_dir / f"{safe_stem}_解读.md"

                header = (
                    f"<!-- 来源文件：{file_name} -->\n"
                    f"<!-- 解读时间：{datetime.now().strftime('%Y-%m-%d %H:%M')} -->\n"
                    f"<!-- 解读深度：{depth} -->\n\n"
                )
                out_file.write_text(header + analysis, encoding="utf-8")

                preview = analysis[:800] + ("..." if len(analysis) > 800 else "")
                return (
                    f"已解读：{file_name}\n"
                    f"保存位置：`{out_file.relative_to(root)}`\n\n"
                    f"{preview}"
                )
            else:
                return analysis

        except Exception as e:
            return f"❌ 解读论文失败：{str(e)}"


def create_paper_tool(base_dir: Path) -> AnalyzePaperTool:
    """Create tool for analyzing paper PDFs."""
    tool = AnalyzePaperTool(root_dir=str(base_dir))
    tool.description = (
        "【论文解读】读取一篇论文 PDF，生成结构化的中文解读。 "
        "适用场景：用户上传了一篇论文 PDF，说'帮我解读这篇论文'"
        "'这篇讲了什么''总结一下这个 PDF'时。 "
        "参数：\n"
        "- file_path：PDF 路径（相对于项目根目录，或绝对路径）\n"
        "- depth：'full'（默认）完整解读；'brief' 只做快速判断\n"
        "- save：是否保存到 papers/ 目录，默认 true\n"
        "输出：解读保存到 `papers/{文件名}_解读.md`，并在对话里返回预览。 "
        "注意：\n"
        "- PDF 超过 50000 字符会被截断，解读会明确说明\n"
        "- 扫描版 PDF（图片型）无法提取文字，会报错\n"
        "- 只处理 PDF，其他格式请用 read_rich_file"
    )
    return tool