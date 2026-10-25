"""WebSearchTool -- Search the web using DuckDuckGo."""

from typing import Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field


class WebSearchInput(BaseModel):
    query: str = Field(description="Search query string")


class WebSearchTool(BaseTool):
    """Search the web using DuckDuckGo."""
    name: str = "web_search"
    description: str = ""
    args_schema: Type[BaseModel] = WebSearchInput

    def _run(self, query: str) -> str:
        try:
            from duckduckgo_search import DDGS
            results = []
            with DDGS() as ddgs:
                for r in ddgs.text(query, max_results=5):
                    results.append(
                        f"Title: {r.get('title', '')}\n"
                        f"URL: {r.get('href', '')}\n"
                        f"Snippet: {r.get('body', '')}\n"
                    )
            if not results:
                return "No search results found."
            return "\n---\n".join(results)
        except ImportError:
            return "duckduckgo-search not installed. Run: pip install duckduckgo-search"
        except Exception as e:
            return f"Search error: {str(e)}"


class WebFetchInput(BaseModel):
    url: str = Field(description="URL to fetch content from")


class WebFetchTool(BaseTool):
    """Fetch content from a URL."""
    name: str = "web_fetch"
    description: str = ""
    args_schema: Type[BaseModel] = WebFetchInput

    def _run(self, url: str) -> str:
        try:
            import urllib.request
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; RaspiClaw/1.0)"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                content = resp.read().decode("utf-8", errors="replace")
                # Simple HTML to text: strip tags
                import re
                content = re.sub(r'<script[^>]*>[\s\S]*?</script>', '', content)
                content = re.sub(r'<style[^>]*>[\s\S]*?</style>', '', content)
                content = re.sub(r'<[^>]+>', ' ', content)
                content = re.sub(r'\s+', ' ', content).strip()
                if len(content) > 15000:
                    content = content[:15000] + "...[truncated]"
                return content
        except Exception as e:
            return f"Fetch error: {str(e)}"


def create_web_search_tool() -> WebSearchTool:
    """Create web search tool."""
    tool = WebSearchTool()
    tool.description = (
        "[Web Search] Search the web using DuckDuckGo. "
        "Returns top 5 results with title, URL, and snippet. "
        "Use this when you need to find current information, "
        "look up facts, or research topics online."
    )
    return tool


def create_web_fetch_tool() -> WebFetchTool:
    """Create web fetch tool."""
    tool = WebFetchTool()
    tool.description = (
        "[Web Fetch] Fetch and extract text content from a URL. "
        "Use this to read web pages, documentation, or API responses. "
        "Returns plain text with HTML tags stripped. "
        "Input: full URL including protocol (https://...)."
    )
    return tool
