"""ComparePapersTool -- Compare multiple paper analyses side by side."""

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field


class ComparePapersInput(BaseModel):
    paper_ids: str = Field(
        description="Comma-separated paper identifiers (file name prefixes under papers/). "
                    "E.g. '2610.02191,2610.01372'. "
                    "Support 2-5 papers."
    )
    focus: str = Field(
        default="",
        description="Optional. Comparison focus, e.g. 'methods', 'experiments', "
                    "'conclusions'. Leave empty for full comparison.",
    )
    save: bool = Field(
        default=True,
        description="Whether to save the comparison to papers/_对比/ directory.",
    )


class ComparePapersTool(BaseTool):
    """Compare multiple paper analyses."""
    name: str = "compare_papers"
    description: str = ""
    args_schema: Type[BaseModel] = ComparePapersInput
    root_dir: str = ""

    MAX_PAPERS: int = 5
    MIN_PAPERS: int = 2

    def _find_analysis(self, paper_id: str) -> tuple[Path, str]:
        """Find the analysis md file for a given paper id."""
        papers_dir = Path(self.root_dir) / "papers"
        if not papers_dir.exists():
            return (None, "")

        paper_id = paper_id.strip()
        # 优先精确匹配 {id}_解读.md
        candidates = list(papers_dir.glob(f"{paper_id}*_解读.md"))
        if not candidates:
            candidates = list(papers_dir.glob(f"*{paper_id}*_解读.md"))
        if not candidates:
            return (None, "")

        # 取第一个
        f = candidates[0]
        try:
            content = f.read_text(encoding="utf-8")
            return (f, content)
        except Exception:
            return (None, "")

    def _compare(self, papers: list, focus: str) -> str:
        """Call LLM to compare papers."""
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

        # 拼装论文内容
        papers_text = ""
        for i, p in enumerate(papers, 1):
            content = p["content"]
            # 截断单篇内容，防止过长
            if len(content) > 6000:
                content = content[:6000] + "\n...[已截断]"
            papers_text += f"\n\n===== 论文 {i}：{p['name']} =====\n\n{content}"

        # 标签
        labels = "、".join(f"论文 {i+1}" for i in range(len(papers)))

        focus_hint = ""
        if focus.strip():
            focus_hint = f"\n本次对比的**重点**是：{focus.strip()}。请在对比中突出这个维度。\n"

        prompt = (
            f"下面有 {len(papers)} 篇论文的解读。请用中文生成一份**结构化对比文档**。\n"
            f"{focus_hint}\n"
            "严格按以下 markdown 格式输出：\n\n"
            f"# 论文对比：{labels}\n\n"
            "## 一句话区分\n"
            "（每篇一句话，说清各自做了什么）\n\n"
            "## 对比表\n"
            "（一个 markdown 表格，至少包含：研究问题、核心方法、主要贡献、"
            "实验/数据、局限 五个维度）\n\n"
            "## 详细对比\n"
            "（用「### 序号. 维度名」分点展开，每个维度下逐篇说明）\n\n"
            "## 它们之间的关系\n"
            "（互补 / 竞争 / 递进？有没有引用关系？在同一个研究脉络里的位置）\n\n"
            "## 综合来看\n"
            "（这个方向的研究趋势是什么？从这几篇能看出什么共同问题、"
            "共同方法、共同局限？）\n\n"
            "## 关键差异\n"
            "（列出 3-5 个最重要的差异点）\n\n"
            "要求：\n"
            "- 对比表每格不超过 20 字\n"
            "- 不要客套话，直接输出\n"
            "- 不要编造解读文件里没有的内容\n"
            "- 如果某篇信息不全，说明'该篇信息不足'\n\n"
            f"论文解读：\n{papers_text}"
        )

        try:
            result = llm.invoke(prompt)
            return result.content.strip()
        except Exception as e:
            return f"(生成对比失败：{e})"

    def _run(self, paper_ids: str, focus: str = "",
             save: bool = True) -> str:
        try:
            ids = [x.strip() for x in paper_ids.split(",") if x.strip()]

            if len(ids) < self.MIN_PAPERS:
                return f"❌ 至少需要 {self.MIN_PAPERS} 篇论文才能对比。"
            if len(ids) > self.MAX_PAPERS:
                return f"❌ 一次最多对比 {self.MAX_PAPERS} 篇论文。"

            # 找每篇的解读文件
            papers = []
            not_found = []
            for pid in ids:
                f, content = self._find_analysis(pid)
                if f is None:
                    not_found.append(pid)
                else:
                    papers.append({
                        "id": pid,
                        "name": f.stem,
                        "path": f,
                        "content": content,
                    })

            if not_found:
                return (
                    f"❌ 以下论文没找到解读文件：{', '.join(not_found)}\n"
                    f"请先用 `analyze_paper` 解读它们，再进行对比。"
                )

            # 调 LLM 对比
            comparison = self._compare(papers, focus)

            if save:
                root = Path(self.root_dir)
                out_dir = root / "papers" / "_对比"
                out_dir.mkdir(parents=True, exist_ok=True)
                stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
                safe_ids = "_".join(
                    re.sub(r'[<>:"/\\|?*]', "_", p["id"])[:20] for p in papers
                )
                out_file = out_dir / f"{stamp}_{safe_ids}.md"

                header = (
                    f"<!-- 对比论文：{', '.join(p['name'] for p in papers)} -->\n"
                    f"<!-- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')} -->\n\n"
                )
                out_file.write_text(header + comparison, encoding="utf-8")

                return (
                    f"已生成对比：{len(papers)} 篇论文\n"
                    f"保存位置：`{out_file.relative_to(root)}`\n\n"
                    f"{comparison}"
                )
            else:
                return comparison

        except Exception as e:
            return f"❌ 对比失败：{str(e)}"


def create_compare_papers_tool(base_dir: Path) -> ComparePapersTool:
    """Create tool for comparing paper analyses."""
    tool = ComparePapersTool(root_dir=str(base_dir))
    tool.description = (
        "【论文对比】对比多篇论文，生成结构化对比文档。 "
        "适用场景：用户说'对比这几篇论文''它们有什么区别'"
        "'这几篇之间的关系是什么'时。 "
        "参数：\n"
        "- paper_ids：逗号分隔的论文标识（papers/ 下解读文件名的前缀），"
        "如 '2610.02191,2610.01372'。支持 2-5 篇\n"
        "- focus：可选。对比重点，如 'methods'、'experiments'。留空则全面对比\n"
        "- save：是否保存到 papers/_对比/ 目录，默认 true\n"
        "输出：对比文档保存到 `papers/_对比/{时间戳}_{IDs}.md`，"
        "并在对话里返回全文。 "
        "注意：\n"
        "- 本工具基于 papers/ 下的解读文件进行对比，"
        "所以必须先对每篇论文跑过 analyze_paper\n"
        "- 如果某篇论文没找到解读文件，会提示用户先解读"
    )
    return tool