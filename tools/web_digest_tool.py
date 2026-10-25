"""WebDigestTool -- Digest a web page into structured notes."""

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field


class DigestWebPageInput(BaseModel):
    url: str = Field(
        description="URL of the web page to digest (must include http:// or https://)."
    )
    title: str = Field(
        default="",
        description="Optional title. Leave empty to auto-extract from the page or URL.",
    )
    detail_level: str = Field(
        default="full",
        description="'brief' returns a short summary only. "
                    "'full' returns structured notes with key points and keywords.",
    )
    save: bool = Field(
        default=True,
        description="Whether to save the digest to digests/ directory.",
    )


class DigestWebPageTool(BaseTool):
    """Fetch a web page and produce structured notes."""
    name: str = "digest_web_page"
    description: str = ""
    args_schema: Type[BaseModel] = DigestWebPageInput
    root_dir: str = ""

    def _fetch_and_clean(self, url: str):
        """Return (page_title, cleaned_text)."""
        import urllib.request

        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; RaspiClaw/3.0)"},
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            html = resp.read().decode("utf-8", errors="replace")

        # Extract title
        page_title = ""
        m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        if m:
            page_title = re.sub(r"\s+", " ", m.group(1)).strip()

        # Strip scripts, styles, nav, footer, header
        html = re.sub(r"<script[^>]*>[\s\S]*?</script>", " ", html, flags=re.IGNORECASE)
        html = re.sub(r"<style[^>]*>[\s\S]*?</style>", " ", html, flags=re.IGNORECASE)
        html = re.sub(r"<nav[^>]*>[\s\S]*?</nav>", " ", html, flags=re.IGNORECASE)
        html = re.sub(r"<footer[^>]*>[\s\S]*?</footer>", " ", html, flags=re.IGNORECASE)
        html = re.sub(r"<header[^>]*>[\s\S]*?</header>", " ", html, flags=re.IGNORECASE)

        # Convert block tags to newlines
        html = re.sub(r"<(br|p|div|h[1-6]|li)[^>]*>", "\n", html, flags=re.IGNORECASE)

        # Strip remaining tags
        text = re.sub(r"<[^>]+>", " ", html)

        # Decode common entities
        text = text.replace("&nbsp;", " ").replace("&amp;", "&")
        text = text.replace("&lt;", "<").replace("&gt;", ">")
        text = text.replace("&quot;", '"').replace("&#39;", "'")

        # Collapse whitespace
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n\s*\n+", "\n\n", text).strip()

        # Truncate
        if len(text) > 18000:
            text = text[:18000] + "\n...[内容过长，已截断]"

        return page_title, text

    def _digest(self, url: str, title: str, raw_text: str,
                detail_level: str) -> str:
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
                "下面是一个网页的内容。请用中文写一段简短概括，"
                "200 字以内，说清这个网页讲了什么。\n\n"
                f"标题：{title}\n"
                f"URL：{url}\n\n"
                f"内容：\n{raw_text}"
            )
        else:
            prompt = (
                "下面是一个网页的内容。请用中文把它整理成结构化的学习笔记，"
                "严格按以下 markdown 格式输出：\n\n"
                "## 一句话概括\n"
                "（一句话说清这个网页讲了什么）\n\n"
                "## 核心要点\n"
                "（分点列出，每点用「### 序号. 标题」格式，下面跟 2-4 行说明。"
                "如果原文有表格或列表，用 markdown 保留）\n\n"
                "## 关键词 / 术语\n"
                "（列出 5-10 个关键术语，每个一行）\n\n"
                "## 原文关键内容\n"
                "（摘录原文里最重要的段落，不要改写，原样保留）\n\n"
                "要求：\n"
                "- 不要客套话，直接输出\n"
                "- 不要编造原文没有的内容\n"
                "- 如果原文是英文，笔记用中文，但术语保留英文\n\n"
                f"标题：{title}\n"
                f"URL：{url}\n\n"
                f"内容：\n{raw_text}"
            )

        try:
            result = llm.invoke(prompt)
            return result.content.strip()
        except Exception as e:
            return f"(生成笔记失败：{e})"

    def _sanitize(self, name: str, max_len: int = 40) -> str:
        name = re.sub(r'[<>:"/\\|?*]', "_", name)
        name = re.sub(r"\s+", "_", name).strip("_")
        return name[:max_len] or "untitled"

    def _run(self, url: str, title: str = "",
             detail_level: str = "full", save: bool = True) -> str:
        try:
            if not url.startswith("http://") and not url.startswith("https://"):
                return "URL 必须以 http:// 或 https:// 开头"

            page_title, raw_text = self._fetch_and_clean(url)

            if not raw_text.strip():
                return "网页内容为空，可能被反爬挡住了，或者该页面是动态渲染的。"

            final_title = title.strip() or page_title or url
            notes = self._digest(url, final_title, raw_text, detail_level)

            if save:
                root = Path(self.root_dir)
                out_dir = root / "digests"
                out_dir.mkdir(parents=True, exist_ok=True)
                stamp = datetime.now().strftime("%Y-%m-%d")
                safe_title = self._sanitize(final_title)
                out_file = out_dir / f"{stamp}_{safe_title}.md"

                header = (
                    f"# {final_title}\n\n"
                    f"## 来源\n{url}\n\n"
                    f"## 消化时间\n{datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
                    f"---\n\n"
                )
                out_file.write_text(header + notes, encoding="utf-8")

                preview = notes[:600] + ("..." if len(notes) > 600 else "")
                return (
                    f"已消化：{final_title}\n"
                    f"链接：{url}\n"
                    f"保存位置：`{out_file.relative_to(root)}`\n"
                    f"笔记预览：\n\n{preview}"
                )
            else:
                return f"# {final_title}\n\n来源：{url}\n\n---\n\n{notes}"

        except Exception as e:
            return f"消化网页失败：{str(e)}"


def create_web_digest_tool(base_dir: Path) -> DigestWebPageTool:
    """Create tool for digesting web pages."""
    tool = DigestWebPageTool(root_dir=str(base_dir))
    tool.description = (
        "【网页内容消化】抓取一个网页，整理成结构化的学习笔记。 "
        "适用场景：用户说'帮我总结这个网页''把这个链接整理成笔记'"
        "'这篇文章讲了什么''消化一下这个 URL'时。 "
        "参数：\n"
        "- url：网页链接（必须以 http:// 或 https:// 开头）\n"
        "- title：可选标题，留空则从网页自动提取\n"
        "- detail_level：'full'（默认）输出结构化笔记；'brief' 只输出 200 字概括\n"
        "- save：是否保存到 digests/ 目录，默认 true\n"
        "输出：笔记保存到 `digests/{日期}_{标题}.md`，并在对话里返回预览。 "
        "注意：本工具只处理单个网页。如果是多个链接，分别调用。"
    )
    return tool