"""Core Tools factory -- returns all tools for the Agent."""

from pathlib import Path
from typing import List, Union

from langchain_core.tools import BaseTool

from .python_repl_tool import create_python_repl_tool
from .read_file_tool import create_read_file_tool, create_read_skill_tool
from .terminal_tool import create_terminal_tool
from .write_memory_tool import create_write_memory_tool
from .rich_file_tool import create_rich_file_tool
from .web_search_tool import create_web_search_tool, create_web_fetch_tool
from .arxiv_tool import create_arxiv_tool
from .arxiv_tool import create_arxiv_tool, create_download_arxiv_pdf_tool
from .study_tool import create_digest_course_material_tool
from .report_tool import create_study_report_tool
from .quiz_tool import create_quiz_tool
from .web_digest_tool import create_web_digest_tool
from .compare_tool import create_compare_tool
from .map_tool import create_map_tool
from .paper_tool import create_paper_tool
from .compare_papers_tool import create_compare_papers_tool
from .card_tool import create_card_tool
from .search_tool import create_search_tool


def get_all_tools(base_dir: Union[Path, str]) -> List[BaseTool]:
    """Create and return all tools, sandboxed to base_dir."""
    base_dir = Path(base_dir) if isinstance(base_dir, str) else base_dir
    memory_dir = base_dir / "memory"
    skills_dir = base_dir / "skills"
    tools = [
        create_terminal_tool(base_dir),
        create_python_repl_tool(),
        create_read_file_tool(base_dir),
        create_read_skill_tool(skills_dir),
        create_write_memory_tool(memory_dir),
        create_rich_file_tool(base_dir),
        create_web_search_tool(),
        create_web_fetch_tool(),
        create_arxiv_tool(work_dir=str(base_dir)),
        create_download_arxiv_pdf_tool(work_dir=str(base_dir)),
        create_digest_course_material_tool(base_dir),
        create_study_report_tool(base_dir),
        create_quiz_tool(base_dir),
        create_web_digest_tool(base_dir),
        create_compare_tool(base_dir),
        create_map_tool(base_dir),
        create_paper_tool(base_dir),
        create_compare_papers_tool(base_dir),
        create_card_tool(base_dir),
        create_search_tool(base_dir),
    ]
    return tools
