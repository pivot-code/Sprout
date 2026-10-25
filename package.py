"""Sprout 打包脚本 — 生成可分发 zip 包"""
import zipfile
import os
from pathlib import Path

BASE = Path(__file__).parent

# 版本号（读取 VERSION 文件，如果没有则默认 1.0.0）
version_file = BASE / "VERSION"
version = version_file.read_text(encoding="utf-8").strip() if version_file.exists() else "1.0.0"
output_name = BASE / f"Sprout-v{version}.zip"

# 需要包含的文件/目录模式
include_patterns = [
    "*.py", "*.bat", "*.md", "*.json", "*.example", "*.txt", "VERSION",
    "tools/*.py",
    "skills/*/SKILL.md", "skills/*/*.md", "skills/*/*.py", "skills/*/*.csv",
    "memory/*.md",
    "data/*.csv",
    "frontend/index.html",
    "frontend/assets/*.js",
    "frontend/assets/*.css",
]

# 排除的文件名（含真实密钥或隐私数据的文件不打包）
exclude_files = {
    "providers.json", ".env", "MEMORY.md", "USER.md", 
    "notifications.json", "user_tasks.json" # 排除本地生成的运行时数据
}

# 排除的目录（含隐私数据、缓存、生成文件）
exclude_dirs = {
    ".venv", ".git", "__pycache__", "uploads", "sessions", 
    "output", ".playwright-mcp", "logs", 
    # 排除所有 AI 生成的学习产物，避免打包体积过大
    "courses", "papers", "digests", "cards", "comparisons", 
    "maps", "reports", "quizzes", "arxiv_papers", "analysis"
}

print(f"  Sprout v{version} 打包中...")
print(f"  输出: {output_name}")

# 收集文件
files = []
for pattern in include_patterns:
    for f in BASE.glob(pattern):
        if f.is_file():
            # 检查是否在排除目录中
            parts = set(f.relative_to(BASE).parts)
            if not parts & exclude_dirs and f.name not in exclude_files:
                files.append(f.relative_to(BASE))

files = sorted(set(files))
print(f"  文件数: {len(files)}")

# 创建 zip
with zipfile.ZipFile(output_name, "w", zipfile.ZIP_DEFLATED) as zf:
    for rel in files:
        zf.write(BASE / rel, str(rel))
        print(f"    + {rel}")

# 显示大小
size_kb = output_name.stat().st_size / 1024
print()
print(f"  打包完成! {output_name.name} ({size_kb:.1f} KB)")
print()
print("  发布前请确认:")
print("    1. .env.example 中是占位符，不是真实 API Key")
print("    2. providers.json.example 中是占位符")
print("    3. VERSION 版本号正确")