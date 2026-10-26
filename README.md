# 🌱 Sprout v1.0

**学习成长智能体** — 基于 LangChain + LangGraph 的个人学习助手，具备强大的文献抓取、资料消化、知识沉淀与对话式交互能力。

---

## 功能特性

| 模块 | 能力 |
|------|------|
| 💬 **智能对话** | 多会话管理、流式输出、思考过程可视化、对话历史持久化 |
| 🔧 **工具调用** | 终端操作、Python 代码执行、文件读写、丰富格式文件解析 |
| 📚 **学术检索** | arXiv 最新论文抓取、PDF 自动下载、全库知识检索 |
| 📝 **内容消化** | 课堂资料消化、网页链接总结、论文深度解读与多篇对比 |
| 🧠 **知识管理** | 知识卡片生成、知识地图生成、长期记忆自动提取 |
| ⚡ **技能系统** | 可扩展的 SKILL.md 技能（自测出题、作业助手、数据分析等） |
| ⏰ **定时任务** | 支持配置每日/每周自动抓取文献、生成学习报告，并在通知栏提醒 |
| 🎨 **生机主题UI** | 现代 Web 界面，提供“生机绿”与“深林色”两套主题 |

---

## 快速开始

### 环境要求

- **Python 3.10+**
- **Windows 10/11**（macOS/Linux 亦可，脚本需手动适配）
- DeepSeek API Key（[免费注册获取](https://platform.deepseek.com/api_keys)）

### 一键安装（Windows）

```bat
双击 install.bat
```

脚本会自动完成：
1. 检测 Python 环境
2. 创建虚拟环境 `.venv`
3. 安装所有 Python 依赖
4. 生成 `.env` 配置文件模板

### 配置 API 密钥

安装完成后，编辑项目目录下的 **`.env`** 文件：

```ini
MAIN_MODEL=deepseek
DEEPSEEK_API_KEY=sk-你的密钥
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
```

### 启动

```bat
双击 start.bat
```

浏览器自动打开 **http://127.0.0.1:8000** 即可使用。

---

## 手动安装（macOS / Linux）

```bash
# 1. 创建虚拟环境
python -m venv .venv
source .venv/bin/activate   # Linux/macOS

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置密钥
cp .env.example .env
# 编辑 .env 填入 API Key

# 4. 启动
python web_api.py
```

---

## 项目结构

```text
Sprout/
├── web_api.py                  # FastAPI 后端（REST + WebSocket + 多会话）
├── Claw.py                     # 核心 Agent（LangGraph ReAct）
├── background_loop.py          # 后台定时任务调度器
├── memory_manager.py           # 记忆管理器
├── skills_scanner.py           # 技能扫描器
├── requirements.txt            # Python 依赖
├── install.bat                 # 一键安装脚本 (Windows)
├── start.bat                   # 一键启动脚本 (Windows)
├── package.bat                 # 一键打包脚本 (Windows)
├── .env.example                # 环境变量模板
│
├── tools/                      # 底层能力工具集
│   ├── arxiv_tool.py           # arXiv 抓取与 PDF 下载
│   ├── paper_tool.py           # 论文深度解读
│   ├── compare_papers_tool.py  # 论文对比
│   ├── card_tool.py            # 知识卡片生成
│   ├── search_tool.py          # 知识库检索
│   ├── map_tool.py             # 知识地图生成
│   ├── quiz_tool.py            # 自测题生成
│   ├── report_tool.py          # 学习报告生成
│   ├── study_tool.py           # 课堂资料消化
│   ├── web_digest_tool.py      # 网页内容消化
│   ├── rich_file_tool.py       # 多格式文档解析 (PDF/PPT/Word等)
│   └── ...                     # 其他底层工具
│
├── skills/                     # Agent 技能定义 (SKILL.md 驱动)
│   ├── arxiv_search/           # 文献抓取技能
│   ├── paper_analyzer/         # 论文解读技能
│   ├── course_digest/          # 资料消化技能
│   ├── knowledge_cards/        # 知识卡片技能
│   └── ...                     # 其他扩展技能
│
├── frontend/                   # Web 前端交互界面
│   ├── index.html              # 页面骨架
│   └── assets/
│       ├── app.js              # 前端逻辑
│       └── style.css           # 生机绿主题样式
│
└── memory/                     # Agent 长期记忆与身份设定
    ├── IDENTITY.md             # 身份设定
    ├── SOUL.md                 # 性格特征
    └── ...
```

---

## 核心使用指南

### 1. 论文与研究
- **找论文**：输入“帮我找 5 篇关于 multi-agent 的最新论文”，Agent 会调用 arXiv 接口抓取并自动下载。
- **读论文**：上传一篇论文 PDF，说“帮我深度解读这篇论文”，Agent 会生成包含背景、方法、贡献、局限的结构化解读。
- **对比论文**：说“对比刚才那两篇论文”，Agent 会自动生成多维度对比文档。

### 2. 课堂与复习
- **消化资料**：上传 PPT 或 PDF，说“帮我整理这份讲义，存到计算机网络课”，Agent 会将其转化为结构化笔记。
- **出题自测**：说“从计算机网络笔记里出 3 道题”，Agent 会调取笔记并生成题目。
- **知识卡片**：说“帮我做知识卡片，课程是计算机网络”，Agent 会拆解出问答卡片。

### 3. 主动型学习助手（定时任务）
- 进入 **任务** 面板，点击“+ 新建任务”。
- 配置如“每天 20:00 自动抓取 LLM 最新论文并下载 PDF”。
- 任务执行完毕后，结果会自动推送到左侧的 **🔔 通知** 会话中，避免打断你的当前对话。

### 4. 会话持久化
- 所有的对话历史都会自动保存在后端 `sessions/` 目录。
- 刷新浏览器、重启服务，历史对话与 Agent 记忆完美恢复。

---

## 添加新技能

1. 在 `skills/` 下创建新目录，如 `skills/my_skill/`
2. 创建 `SKILL.md` 描述技能用途、调用方式和使用方法
3. 如需新的底层能力，在 `tools/` 编写 Python 工具并注册到 `tools/__init__.py`
4. **重启服务**后生效

```text
skills/my_skill/
├── SKILL.md               # 技能定义（必须）
└── prompts/
    └── task_guide.md       # 任务指引
```

---

## 配置多用户访问

将 `.env` 中的 `API_HOST` 改为 `0.0.0.0`：

```ini
API_HOST=0.0.0.0
API_PORT=8000
```

重启后，局域网内其他电脑可通过 `http://你的IP:8000` 访问。

---

## API 密钥获取

### DeepSeek（推荐）

1. 访问 [platform.deepseek.com/api_keys](https://platform.deepseek.com/api_keys)
2. 注册/登录 → API Keys → 创建新 Key
3. 复制 `sk-...` 填入 `.env`

### Qwen / 通义千问

1. 访问 [bailian.console.aliyun.com](https://bailian.console.aliyun.com/)
2. 登录阿里云 → 百炼控制台 → API-KEY 管理
3. 创建并复制 Key，将 `.env` 中的 `MAIN_MODEL` 改为 `qwen`

---

## 常见问题

| 问题 | 解决方案 |
|------|---------|
| 启动提示 "DEEPSEEK_API_KEY not found" | 检查 `.env` 文件是否存在，API Key 是否正确填入 |
| 对话没有响应 | 检查网络和 API Key 有效性 |
| 端口 8000 被占用 | 修改 `.env` 中 `API_PORT` 为其他端口（如 8008） |
| WebSocket 连接失败 | 检查防火墙是否拦截，确认 API_HOST 设置正确 |

---

## 技术栈

| 层 | 技术 |
|---|---|
| Agent 框架 | LangGraph (ReAct Agent) |
| LLM | DeepSeek / Qwen（通义千问） |
| 后端 | FastAPI + WebSocket |
| 前端 | 原生 HTML/CSS/JS（生机绿/深林色主题） |
| 数据处理 | Pandas + Scikit-learn + Matplotlib + Seaborn |
| 文件解析 | python-docx + PyPDF2 + openpyxl + python-pptx |
| 学术检索 | arXiv API |
| 网络搜索 | duckduckgo-search |

---

## 许可证

MIT License — 自由使用、修改和分发。
