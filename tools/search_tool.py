"""SearchTool -- Search the knowledge base (courses, papers, digests, etc.)."""

import os
from pathlib import Path
from typing import Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field


class SearchKnowledgeInput(BaseModel):
    query: str = Field(
        description="What the user is looking for, e.g. 'language drift in RLVR'."
    )
    scope: str = Field(
        default="all",
        description="Search scope: 'all', 'courses', 'papers', 'digests', "
                    "'cards', 'comparisons', 'maps'. Default 'all'.",
    )
    max_results: int = Field(
        default=5,
        description="How many results to return. Default 5.",
    )


class SearchKnowledgeTool(BaseTool):
    """Search the knowledge base."""
    name: str = "search_knowledge"
    description: str = ""
    args_schema: Type[BaseModel] = SearchKnowledgeInput
    root_dir: str = ""

    # 允许搜索的目录及其对应 scope
    SCOPE_MAP: dict = {
        "courses": "courses",
        "papers": "papers",
        "digests": "digests",
        "cards": "cards",
        "comparisons": "comparisons",
        "maps": "maps",
        "arxiv_papers": "arxiv_papers",
        "reports": "reports",
    }

    # 排除的目录
    EXCLUDE_DIRS: set ={"_对比", ".venv", "__pycache__", "node_modules"}

    def _collect_candidates(self, scope: str) -> list:
        """Scan md files and return list of (path, title, preview, full_text)."""
        root = Path(self.root_dir)
        candidates = []

        if scope == "all":
            dirs = list(self.SCOPE_MAP.values())
        else:
            if scope not in self.SCOPE_MAP:
                return []
            dirs = [self.SCOPE_MAP[scope]]

        for dir_name in dirs:
            d = root / dir_name
            if not d.exists():
                continue
            for f in d.rglob("*.md"):
                # 排除某些子目录
                if any(part in self.EXCLUDE_DIRS for part in f.parts):
                    continue
                try:
                    text = f.read_text(encoding="utf-8")
                except Exception:
                    continue

                # 提取标题（第一行 # 开头）
                title = ""
                for line in text.split("\n")[:20]:
                    if line.startswith("# "):
                        title = line[2:].strip()
                        break
                if not title:
                    title = f.stem

                # 预览：前 800 字
                preview = text[:800]

                candidates.append({
                    "path": str(f.relative_to(root)),
                    "title": title,
                    "preview": preview,
                    "full_text": text,
                })

        return candidates

    def _keyword_filter(self, query: str, candidates: list,
                        limit: int = 20) -> list:
        """Simple keyword filter to narrow down candidates."""
        query_lower = query.lower()
        # 分词：按空格切，再过滤掉太短的词
        keywords = [w for w in query_lower.split() if len(w) >= 2]
        if not keywords:
            keywords = [query_lower]

        scored = []
        for c in candidates:
            text_lower = (c["title"] + " " + c["preview"]).lower()
            # 统计关键词出现次数
            score = sum(text_lower.count(kw) for kw in keywords)
            if score > 0:
                scored.append((score, c))

        # 按分数排序，取前 limit 个
        scored.sort(key=lambda x: x[0], reverse=True)
        result = [c for _, c in scored[:limit]]

        # 如果关键词筛完是空的，直接返回前 limit 个（让 LLM 判断）
        if not result:
            result = candidates[:limit]

        return result

    def _llm_rank(self, query: str, candidates: list,
                  max_results: int) -> list:
        """Use LLM to rank candidates by relevance."""
        from langchain_deepseek import ChatDeepSeek
        import json as _json

        api_key = os.getenv("DEEPSEEK_API_KEY")
        base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        model_name = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        if not api_key:
            return []

        llm = ChatDeepSeek(
            model=model_name,
            api_key=api_key,
            base_url=base_url,
            temperature=0.1,
        )

        # 拼装候选列表
        items = []
        for i, c in enumerate(candidates, 1):
            preview = c["preview"][:400]
            items.append(f"[{i}] 标题：{c['title']}\n路径：{c['path']}\n预览：{preview}\n")

        candidates_text = "\n".join(items)

        prompt = (
            f"用户想找：{query}\n\n"
            f"下面是 {len(candidates)} 个候选文件。请判断每个文件和用户查询的"
            f"相关度，并选出最相关的 {max_results} 个。\n\n"
            "严格输出 JSON，不要 markdown 代码块：\n"
            '{\n'
            '  "results": [\n'
            '    {"index": 3, "score": "high", "reason": "..."},\n'
            '    {"index": 7, "score": "medium", "reason": "..."}\n'
            '  ]\n'
            '}\n\n'
            "score 可以是 high / medium / low。\n"
            "只返回真正相关的，不相关的不要返回。\n"
            "如果没有相关的，返回空数组。\n\n"
            f"候选：\n{candidates_text}"
        )

        try:
            result = llm.invoke(prompt)
            text = result.content.strip()
            # 去掉可能的 markdown 代码块
            text = text.replace("```json", "").replace("```", "").strip()
            data = _json.loads(text)
            ranked = data.get("results", [])
            # 映射回 candidates
            output = []
            for r in ranked[:max_results]:
                idx = r.get("index", 0) - 1
                if 0 <= idx < len(candidates):
                    output.append({
                        "candidate": candidates[idx],
                        "score": r.get("score", "low"),
                        "reason": r.get("reason", ""),
                    })
            return output
        except Exception as e:
            print(f"[SearchTool] LLM 排序失败：{e}")
            return []

    def _run(self, query: str, scope: str = "all",
             max_results: int = 5) -> str:
        try:
            query = query.strip()
            if not query:
                return "❌ 请提供搜索关键词。"

            # 1. 收集候选
            candidates = self._collect_candidates(scope)
            if not candidates:
                return f"❌ 在 {scope} 范围内没有找到任何笔记文件。"

            print(f"[SearchTool] 扫描到 {len(candidates)} 个候选文件")

            # 2. 关键词粗筛
            filtered = self._keyword_filter(query, candidates, limit=20)
            print(f"[SearchTool] 关键词筛出 {len(filtered)} 个")

            # 3. LLM 精排
            ranked = self._llm_rank(query, filtered, max_results)

            if not ranked:
                return (
                    f"没有找到和「{query}」相关的笔记。\n"
                    f"（共扫描了 {len(candidates)} 个文件）"
                )

            # 4. 组装结果
            lines = [f"## 搜索结果：{query}", f"找到 {len(ranked)} 个相关文件\n"]

            for i, r in enumerate(ranked, 1):
                c = r["candidate"]
                score_cn = {"high": "高", "medium": "中", "low": "低"}.get(
                    r["score"], r["score"]
                )
                lines.append(f"### {i}. {c['title']}")
                lines.append(f"- **路径**：`{c['path']}`")
                lines.append(f"- **相关度**：{score_cn}")
                if r.get("reason"):
                    lines.append(f"- **为什么相关**：{r['reason']}")
                lines.append(f"- **预览**：{c['preview'][:300]}...")
                lines.append("")

            lines.append(
                "---\n"
                "提示：如果用户想看某个文件的完整内容，"
                "用 `read_file` 读取对应路径。"
            )

            return "\n".join(lines)

        except Exception as e:
            return f"❌ 搜索失败：{str(e)}"


def create_search_tool(base_dir: Path) -> SearchKnowledgeTool:
    """Create tool for searching the knowledge base."""
    tool = SearchKnowledgeTool(root_dir=str(base_dir))
    tool.description = (
        "【知识库检索】在项目的笔记文件中搜索相关内容。 "
        "适用场景：用户说'我之前存过关于 XXX 的东西吗'"
        "'我之前读过关于 XXX 的论文吗''找一下我关于 XXX 的笔记'时。 "
        "参数：\n"
        "- query：搜索关键词\n"
        "- scope：搜索范围。可选 all / courses / papers / digests / "
        "cards / comparisons / maps / arxiv_papers / reports。默认 all\n"
        "- max_results：返回几个结果，默认 5\n"
        "行为：\n"
        "1. 扫描指定目录下的所有 .md 文件\n"
        "2. 用关键词粗筛出候选\n"
        "3. 用 LLM 判断每个候选和 query 的相关度\n"
        "4. 返回最相关的文件，附带路径和预览\n"
        "注意：本工具只返回**文件位置和预览**，不返回全文。"
        "如果用户想看某个文件的完整内容，用 read_file 读取对应路径。"
    )
    return tool