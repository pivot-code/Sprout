## 落盘约定

`fetch_arxiv` 本身**只返回结果，不写文件**。落盘由你（Agent）在对话里决定。

**当用户说"保存""存档""下载""存到本地"等意图时**，分两种情况：

### 情况一：用户想保存摘要/总结（不是 PDF）

按下面规范落盘到**当前工作目录**：

1. 创建 `arxiv_papers/` 文件夹
2. 每篇论文存一个 `.md` 文件，文件名格式：
   `{arXiv ID}_{标题前30字}.md`
   例如：`2610.01372_A Design Theory for AI-Assisted Software.md`
3. 文件内容包含：标题、作者、提交时间、链接、英文摘要，以及（如果是 summary 模式）中文深度总结
4. 同时把所有论文的元数据汇总到一个 `papers_meta.json`，结构如下：

（元数据格式：一个 JSON 数组，每个元素包含 `id`、`title`、`authors`、`link`、`abstract` 五个字段。）

### 情况二：用户想保存 PDF

调用 `download_arxiv_pdf` 工具，见上一节。**不要自己写文件**。

### 用户没明确说"保存"时

只在对话里返回结果，不要主动落盘，不要主动下载 PDF。

## 示例

**例 1：只查找**
用户："帮我找 5 篇 multi-agent 的最新论文"
→ `fetch_arxiv(query="multi-agent", max_results=5)`
→ 在对话里返回结果，不落盘

**例 2：查找 + 总结**
用户："帮我找几篇关于 LLM reasoning 的论文，最好总结一下"
→ `fetch_arxiv(query="LLM reasoning", detail_level="summary")`
→ 在对话里返回结果（含中文总结），不落盘

**例 3：查找 + 保存摘要**
用户："帮我找 5 篇 multi-agent 的论文并保存到本地"
→ `fetch_arxiv(query="multi-agent", max_results=5)`
→ 在工作目录建 `arxiv_papers/`，按规范写入 `.md` 和 `papers_meta.json`

**例 4：查找 + 下载 PDF**
用户："帮我找 5 篇 multi-agent 的论文，把 PDF 下下来"
→ `fetch_arxiv(query="multi-agent", max_results=5)`
→ `download_arxiv_pdf(arxiv_ids="all")`

**例 5：只下载刚才那批的 PDF**
用户："把刚才那几篇的 PDF 下载了"
→ `download_arxiv_pdf(arxiv_ids="all")`

**例 6：按分类 + 时间范围**
用户："最近一周 cs.AI 有什么新论文？"
→ `fetch_arxiv(query="", categories="cs.AI", lookback_days=7)`

## 注意

- 返回的是英文原文，**你（Agent）负责翻译、总结后再回复用户**
- 如果用户没说数量，默认 5 篇
- 如果抓取失败（429 限流、网络问题、关键词无结果），如实告诉用户，不要编造论文
- **不要主动落盘，不要主动下载 PDF，不要自己用 web_fetch 试下载 PDF**