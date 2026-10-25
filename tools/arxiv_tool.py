"""ArxivTool -- fetch papers from arXiv, with optional summarization and PDF download."""

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field


ARXIV_API = "http://export.arxiv.org/api/query"
ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}


# ─────────────────────────────────────────────────────────────
# fetch_arxiv
# ─────────────────────────────────────────────────────────────

class FetchArxivInput(BaseModel):
    query: str = Field(
        description="Search keyword, e.g. 'multi-agent', 'LLM reasoning'. "
                    "Can be empty if categories is provided."
    )
    max_results: int = Field(
        default=5,
        description="How many papers to fetch. Default 5.",
    )
    categories: str = Field(
        default="",
        description="Optional arXiv category filter, comma-separated, "
                    "e.g. 'cs.AI' or 'cs.AI,cs.CL'. Leave empty to search all.",
    )
    lookback_days: int = Field(
        default=0,
        description="Only return papers submitted within the last N days. "
                    "0 means no time filter.",
    )
    detail_level: str = Field(
        default="brief",
        description="'brief' returns title/authors/date/link/abstract. "
                    "'summary' additionally generates a Chinese deep summary "
                    "for each paper (slower, costs LLM tokens).",
    )
    save: bool = Field(
        default=False,
        description="Whether to save results to arxiv_papers/. "
                    "Default false for interactive use. "
                    "Set true for scheduled tasks.",
    )


class FetchArxivTool(BaseTool):
    """Fetch papers from arXiv."""
    name: str = "fetch_arxiv"
    description: str = ""
    args_schema: Type[BaseModel] = FetchArxivInput
    work_dir: str = ""

    def _build_url(self, query: str, categories: str,
                   max_results: int) -> str:
        parts = []
        if query.strip():
            parts.append(f"all:{query.strip()}")
        if categories.strip():
            cats = [c.strip() for c in categories.split(",") if c.strip()]
            cat_query = " OR ".join(f"cat:{c}" for c in cats)
            parts.append(f"({cat_query})")

        if not parts:
            search_query = "all:*"
        elif len(parts) == 1:
            search_query = parts[0]
        else:
            search_query = " AND ".join(parts)

        params = {
            "search_query": search_query,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
            "max_results": str(max_results),
        }
        return f"{ARXIV_API}?{urllib.parse.urlencode(params)}"

    def _fetch_raw(self, url: str) -> str:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; RaspiClaw/3.0)"},
        )

        last_error = None
        for attempt in range(2):
            try:
                with urllib.request.urlopen(req, timeout=20) as resp:
                    return resp.read().decode("utf-8", errors="replace")
            except urllib.error.HTTPError as e:
                last_error = e
                if e.code == 429 and attempt == 0:
                    time.sleep(3)
                    continue
                raise
            except Exception as e:
                last_error = e
                raise

        raise last_error if last_error else RuntimeError("arXiv fetch failed")

    def _parse(self, xml_text: str, lookback_days: int) -> list:
        from datetime import datetime, timedelta, timezone

        root = ET.fromstring(xml_text)
        cutoff = None
        if lookback_days > 0:
            cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)

        papers = []
        for entry in root.findall("atom:entry", ATOM_NS):
            def _text(tag):
                el = entry.find(f"atom:{tag}", ATOM_NS)
                return el.text.strip() if el is not None and el.text else ""

            published = _text("published")
            if cutoff and published:
                try:
                    pub_dt = datetime.strptime(
                        published, "%Y-%m-%dT%H:%M:%SZ"
                    ).replace(tzinfo=timezone.utc)
                    if pub_dt < cutoff:
                        continue
                except Exception:
                    pass

            arxiv_id = _text("id")
            title = " ".join(_text("title").split())
            summary = " ".join(_text("summary").split())
            authors = [
                a.find("atom:name", ATOM_NS).text
                for a in entry.findall("atom:author", ATOM_NS)
                if a.find("atom:name", ATOM_NS) is not None
            ]

            papers.append({
                "id": arxiv_id,
                "title": title,
                "authors": authors,
                "published": published,
                "link": arxiv_id,
                "abstract": summary,
            })
        return papers

    def _summarize(self, paper: dict) -> str:
        try:
            from langchain_deepseek import ChatDeepSeek

            api_key = os.getenv("DEEPSEEK_API_KEY")
            base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
            model_name = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
            if not api_key:
                return "(无法生成总结：DEEPSEEK_API_KEY 未设置)"

            llm = ChatDeepSeek(
                model=model_name,
                api_key=api_key,
                base_url=base_url,
                temperature=0.3,
            )
            prompt = (
                "请用中文对下面这篇论文做一段深度总结，包含：\n"
                "1. 研究问题\n2. 核心方法\n3. 主要贡献\n4. 可能的局限\n\n"
                f"标题：{paper['title']}\n\n"
                f"摘要：{paper['abstract']}\n\n"
                "要求：条理清晰，300 字以内，不要客套话。"
            )
            result = llm.invoke(prompt)
            return result.content.strip()
        except Exception as e:
            return f"(总结失败：{e})"

    def _save_last_fetch(self, papers: list) -> None:
        """Persist the last fetch result so download_arxiv_pdf can use 'all'."""
        try:
            if not self.work_dir:
                return
            memory_dir = Path(self.work_dir) / "memory"
            memory_dir.mkdir(parents=True, exist_ok=True)
            cache_file = memory_dir / "_last_arxiv_fetch.json"
            cache_file.write_text(
                json.dumps(papers, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def _save_to_folder(self, papers: list, query: str,
                        categories: str, detail_level: str) -> str:
        """Save papers to arxiv_papers/{date}_{query}.md. Returns saved path."""
        from datetime import datetime

        if not self.work_dir:
            return ""

        root = Path(self.work_dir)
        out_dir = root / "arxiv_papers"
        out_dir.mkdir(parents=True, exist_ok=True)

        # 文件名：日期_关键词
        label = query.strip() or categories.strip() or "all"
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in label)[:40]
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
        out_file = out_dir / f"{stamp}_{safe}.md"

        lines = [f"# arXiv 抓取结果", ""]
        lines.append(f"- 关键词：{query or '（空）'}")
        lines.append(f"- 分类：{categories or '（全部）'}")
        lines.append(f"- 抓取时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
        lines.append(f"- 论文数量：{len(papers)}")
        lines.append("")
        lines.append("---")
        lines.append("")

        for i, p in enumerate(papers, 1):
            authors_str = ", ".join(p["authors"][:5])
            if len(p["authors"]) > 5:
                authors_str += " et al."
            lines.append(f"## {i}. {p['title']}")
            lines.append(f"- **作者**：{authors_str}")
            lines.append(f"- **提交时间**：{p['published']}")
            lines.append(f"- **链接**：{p['link']}")
            lines.append(f"- **英文摘要**：{p['abstract']}")
            if detail_level == "summary":
                lines.append(f"- **中文总结**：{self._summarize(p)}")
            lines.append("")

        out_file.write_text("\n".join(lines), encoding="utf-8")
        return str(out_file.relative_to(root))

    def _run(self, query: str, max_results: int = 5,
             categories: str = "", lookback_days: int = 0,
             detail_level: str = "brief", save: bool = False) -> str:
        try:
            url = self._build_url(query, categories, max_results)
            xml_text = self._fetch_raw(url)
            papers = self._parse(xml_text, lookback_days)

            if not papers:
                return (
                    f"No papers found for query='{query}', "
                    f"categories='{categories}', "
                    f"lookback_days={lookback_days}."
                )

            self._save_last_fetch(papers)

            # 如果 save=true，落盘
            saved_path = ""
            if save:
                saved_path = self._save_to_folder(
                    papers, query, categories, detail_level
                )

            lines = [f"## arXiv results: {query or categories}",
                     f"Total: {len(papers)}\n"]

            for i, p in enumerate(papers, 1):
                authors_str = ", ".join(p["authors"][:5])
                if len(p["authors"]) > 5:
                    authors_str += " et al."
                lines.append(f"### {i}. {p['title']}")
                lines.append(f"- Authors: {authors_str}")
                lines.append(f"- Published: {p['published']}")
                lines.append(f"- Link: {p['link']}")
                lines.append(f"- Abstract: {p['abstract']}")

                if detail_level == "summary":
                    lines.append(f"- Chinese Summary: {self._summarize(p)}")

                lines.append("")

            result = "\n".join(lines)
            if saved_path:
                result += f"\n\n📁 已保存到：`{saved_path}`"
            return result

        except urllib.error.HTTPError as e:
            if e.code == 429:
                return (
                    "arXiv 请求被限流（HTTP 429）。请等 1-2 分钟后再试，"
                    "或减少抓取数量。"
                )
            return f"arXiv fetch error: HTTP {e.code} {e.reason}"
        except Exception as e:
            return f"arXiv fetch error: {str(e)}"


def create_arxiv_tool(work_dir: str = "") -> FetchArxivTool:
    """Create tool for fetching papers from arXiv."""
    tool = FetchArxivTool(work_dir=work_dir)
    tool.description = (
        "【arXiv 文献搜索】从 arXiv 抓取最新论文。 "
        "适用场景：用户想查找某个研究方向的最新论文、追踪某个主题、"
        "了解某篇论文的内容。 "
        "参数：\n"
        "- query：搜索关键词，如 'multi-agent'、'LLM reasoning'（可留空，仅按分类抓）\n"
        "- max_results：抓几篇，默认 5\n"
        "- categories：arXiv 分类过滤（可选，逗号分隔），如 'cs.AI'、'cs.AI,cs.CL'\n"
        "- lookback_days：只看最近 N 天的论文，0 表示不限\n"
        "- detail_level：'brief'（默认）返回标题/作者/日期/链接/英文摘要；"
        "'summary' 额外为每篇生成中文深度总结（更慢、更费 token）\n"
        "- save：是否落盘到 arxiv_papers/，默认 false（交互式场景）；"
        "定时任务里应设为 true\n"
        "何时用 summary：用户明确说'帮我总结''翻译成中文''快速了解内容'时。"
        "用户没说时默认用 brief，不要主动用 summary。 "
        "返回的英文摘要由你负责翻译或总结后再回复用户。"
    )
    return tool


# ─────────────────────────────────────────────────────────────
# download_arxiv_pdf
# ─────────────────────────────────────────────────────────────

class DownloadArxivPdfInput(BaseModel):
    arxiv_ids: str = Field(
        description="Comma-separated arXiv IDs to download, e.g. "
                    "'2610.01372,2610.01367'. Use 'all' to download all "
                    "papers from the last fetch_arxiv call."
    )


class DownloadArxivPdfTool(BaseTool):
    """Download PDFs from arXiv with existence check and rate limiting."""
    name: str = "download_arxiv_pdf"
    description: str = ""
    args_schema: Type[BaseModel] = DownloadArxivPdfInput
    work_dir: str = ""

    MAX_DOWNLOAD: int = 10

    def _load_last_fetch(self) -> list:
        try:
            if not self.work_dir:
                return []
            cache_file = Path(self.work_dir) / "memory" / "_last_arxiv_fetch.json"
            if not cache_file.exists():
                return []
            return json.loads(cache_file.read_text(encoding="utf-8"))
        except Exception:
            return []

    def _check_pdf_exists(self, pdf_url: str) -> bool:
        req = urllib.request.Request(
            pdf_url,
            method="HEAD",
            headers={"User-Agent": "Mozilla/5.0 (compatible; RaspiClaw/3.0)"},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.status == 200
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return False
            if e.code == 429:
                raise
            return False
        except Exception:
            return False

    def _download_one(self, pdf_url: str, save_path: Path) -> None:
        req = urllib.request.Request(
            pdf_url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; RaspiClaw/3.0)"},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            save_path.write_bytes(resp.read())

    def _sanitize_filename(self, name: str, max_len: int = 50) -> str:
        import re
        name = re.sub(r'[<>:"/\\|?*]', "_", name)
        name = re.sub(r"\s+", " ", name).strip()
        return name[:max_len]

    def _run(self, arxiv_ids: str) -> str:
        last_fetched = self._load_last_fetch()

        if arxiv_ids.strip().lower() == "all":
            if not last_fetched:
                return (
                    "❌ 没有可下载的论文。请先用 fetch_arxiv 抓取一批论文，"
                    "然后再调用本工具下载全部。"
                )
            targets = [
                {"id": p["id"].split("/")[-1], "title": p["title"]}
                for p in last_fetched
            ]
        else:
            ids = [x.strip() for x in arxiv_ids.split(",") if x.strip()]
            title_map = {}
            for p in last_fetched:
                pid = p["id"].split("/")[-1]
                title_map[pid] = p["title"]
            targets = [
                {"id": x, "title": title_map.get(x, x)} for x in ids
            ]

        if not targets:
            return "❌ 没有指定要下载的论文 ID。"

        note = ""
        if len(targets) > self.MAX_DOWNLOAD:
            targets = targets[:self.MAX_DOWNLOAD]
            note = f"（超过 {self.MAX_DOWNLOAD} 篇，只下载前 {self.MAX_DOWNLOAD} 篇）"

        out_dir = Path(self.work_dir) / "arxiv_papers"
        out_dir.mkdir(parents=True, exist_ok=True)

        results = []
        success = 0
        skipped = 0
        failed = 0

        for i, t in enumerate(targets):
            pid = t["id"]
            title = t["title"]
            pdf_url = f"https://arxiv.org/pdf/{pid}"

            try:
                exists = self._check_pdf_exists(pdf_url)
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    results.append(
                        f"⚠️ {pid}: arXiv 限流（429），已停止后续下载。"
                        "请等 1-2 分钟再试。"
                    )
                    break
                exists = False

            if not exists:
                results.append(f"⏭️ {pid}: PDF 尚未生成或不可访问，已跳过。")
                skipped += 1
                if i < len(targets) - 1:
                    time.sleep(2)
                continue

            safe_title = self._sanitize_filename(title)
            filename = f"{pid}_{safe_title}.pdf"
            save_path = out_dir / filename

            if save_path.exists():
                results.append(f"✅ {pid}: 已存在，跳过 → {filename}")
                success += 1
                continue

            try:
                self._download_one(pdf_url, save_path)
                size_kb = save_path.stat().st_size // 1024
                results.append(
                    f"✅ {pid}: 下载成功 → {filename} ({size_kb} KB)"
                )
                success += 1
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    results.append(
                        f"⚠️ {pid}: 下载时被限流（429），已停止。"
                    )
                    break
                results.append(f"❌ {pid}: 下载失败 HTTP {e.code}")
                failed += 1
            except Exception as e:
                results.append(f"❌ {pid}: 下载失败 {e}")
                failed += 1

            if i < len(targets) - 1:
                time.sleep(3)

        header = (
            f"## arXiv PDF 下载报告 {note}\n"
            f"保存目录：`{out_dir}`\n"
            f"成功 {success} / 跳过 {skipped} / 失败 {failed}\n"
        )
        return header + "\n".join(results)


def create_download_arxiv_pdf_tool(work_dir: str = "") -> DownloadArxivPdfTool:
    """Create tool for downloading arXiv PDFs."""
    tool = DownloadArxivPdfTool(work_dir=work_dir)
    tool.description = (
        "【arXiv PDF 下载】下载指定论文的 PDF 文件，保存到工作目录下的 "
        "arxiv_papers/ 文件夹。 "
        "适用场景：用户说'把刚才那几篇下下来''下载这篇论文的 PDF'"
        "'把论文 PDF 存到本地'时。 "
        "参数：\n"
        "- arxiv_ids：逗号分隔的 arXiv ID，如 '2610.01372,2610.01367'；"
        "也可以传 'all' 表示下载上一次 fetch_arxiv 抓到的全部论文\n"
        "重要特性：\n"
        "1. 下载前会先探测 PDF 是否真实存在，不存在就跳过并说明原因\n"
        "2. 每次下载之间自动等待，避免被 arXiv 限流\n"
        "3. 一次最多下载 10 篇\n"
        "4. 下载成功后文件名格式为 {arXiv ID}_{标题}.pdf\n"
        "注意：arXiv 新提交的论文，PDF 可能要几小时到一天才生成。"
        "如果遇到大量'PDF 尚未生成'的提示，建议让用户稍后再试，"
        "或换一批更早的论文。"
    )
    return tool