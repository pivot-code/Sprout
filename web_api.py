"""Sprout Web API -- REST + WebSocket + Provider Management + Multi-Session."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from Claw import RaspiClawAgent
from skills_scanner import scan_skills, generate_skills_prompt

# --- Multi-Session Agent Manager ---
BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
PROVIDERS_FILE = BASE_DIR / "providers.json"
USER_TASKS_FILE = BASE_DIR / "user_tasks.json"
NOTIFICATIONS_FILE = BASE_DIR / "notifications.json"
SESSIONS_DIR = BASE_DIR / "sessions"
SESSIONS_DIR.mkdir(exist_ok=True)

# Global agent pool: session_id -> RaspiClawAgent
_agents: dict[str, RaspiClawAgent] = {}
# Track streaming tasks for stop support
_stream_tasks: dict[str, asyncio.Task] = {}

# ─── Auto-shutdown when browser closes ───
_client_count: int = 0
_shutdown_delay: int = 5


async def auto_shutdown_check():
    """Wait for shutdown delay, then exit if no clients reconnected."""
    await asyncio.sleep(_shutdown_delay)
    if _client_count <= 0:
        print("[Sprout] No active clients, shutting down...")
        os._exit(0)


def dict_to_langchain_messages(messages: list):
    """把磁盘存的 dict 列表转成 LangChain 的 BaseMessage 列表。"""
    from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
    result = []
    for m in messages:
        role = m.get("role", "")
        content = m.get("content", "")
        if not content:
            continue
        if role == "user":
            result.append(HumanMessage(content=content))
        elif role == "assistant":
            result.append(AIMessage(content=content))
        elif role == "system":
            result.append(SystemMessage(content=content))
    return result


def get_or_create_agent(session_id: str) -> RaspiClawAgent:
    """Get existing agent or create new one for session."""
    if session_id not in _agents:
        agent = RaspiClawAgent(base_dir=BASE_DIR)
        # 从磁盘恢复历史消息
        data = load_session_file(session_id)
        messages = data.get("messages", [])
        if messages:
            try:
                agent.messages = dict_to_langchain_messages(messages)
                print(f"[Sprout] 已恢复 {len(agent.messages)} 条历史消息到会话 {session_id}")
            except Exception as e:
                print(f"[Sprout] 恢复历史消息失败：{e}")
        _agents[session_id] = agent
    return _agents[session_id]


# --- Provider Management ---
def load_providers() -> dict:
    """Load providers.json."""
    if PROVIDERS_FILE.exists():
        return json.loads(PROVIDERS_FILE.read_text(encoding="utf-8"))
    return {"activeId": "", "providers": [], "schemaVersion": 1}


def save_providers(data: dict):
    """Save providers.json."""
    PROVIDERS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# --- User Tasks Management ---
def load_user_tasks() -> dict:
    """Load user_tasks.json."""
    if USER_TASKS_FILE.exists():
        return json.loads(USER_TASKS_FILE.read_text(encoding="utf-8"))
    return {"tasks": []}


def save_user_tasks(data: dict):
    """Save user_tasks.json."""
    USER_TASKS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# --- Notifications ---
def load_notifications() -> dict:
    """Load notifications.json."""
    if NOTIFICATIONS_FILE.exists():
        try:
            return json.loads(NOTIFICATIONS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {"notifications": []}
    return {"notifications": []}


def save_notifications(data: dict):
    """Save notifications.json."""
    NOTIFICATIONS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# --- Session Persistence ---
def session_file(sid: str) -> Path:
    """Return the file path for a session."""
    safe_sid = "".join(c for c in sid if c.isalnum() or c in "-_")
    return SESSIONS_DIR / f"{safe_sid}.json"


def load_session_file(sid: str) -> dict:
    """Load a session from disk. Returns empty dict if not found."""
    f = session_file(sid)
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_session_file(sid: str, data: dict):
    """Save a session to disk."""
    f = session_file(sid)
    f.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def list_session_files() -> list:
    """List all persisted sessions, sorted by updated_at desc."""
    result = []
    for f in SESSIONS_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            result.append({
                "id": data.get("id", f.stem),
                "name": data.get("name", ""),
                "created_at": data.get("created_at", ""),
                "updated_at": data.get("updated_at", ""),
                "message_count": len(data.get("messages", [])),
            })
        except Exception:
            continue
    result.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return result


# --- FastAPI App ---
app = FastAPI(title="Sprout API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def on_startup():
    """Start background loop when the event loop is ready."""
    try:
        default_agent = get_or_create_agent("default")
        default_agent._created_at = default_agent._created_at or datetime.now().isoformat()
        if not getattr(default_agent, "_bg_started", False):
            default_agent.bg_loop.start()
            default_agent._bg_started = True
            print("[Sprout] Background loop started via startup event")
    except Exception as e:
        print(f"[Sprout] Failed to start background loop: {e}")


# Static files (frontend)
FRONTEND_DIR = BASE_DIR / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="assets")


# --- Request Models ---
class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"


class WorkDirRequest(BaseModel):
    path: str


class ProviderCreate(BaseModel):
    name: str
    apiKey: str
    baseUrl: str
    apiFormat: str = "openai"
    models: dict = {}
    runtimeKind: str = "deepseek"


class ProviderUpdate(BaseModel):
    name: str | None = None
    apiKey: str | None = None
    baseUrl: str | None = None
    apiFormat: str | None = None
    models: dict | None = None
    runtimeKind: str | None = None


class SwitchProviderRequest(BaseModel):
    provider_id: str


# --- REST Endpoints ---
@app.get("/")
async def serve_frontend():
    """Serve frontend page."""
    index_file = FRONTEND_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return JSONResponse({"status": "ok", "message": "Sprout API running"})


@app.get("/api/about")
async def get_about():
    """Get project info — read-only, cannot be modified via API."""
    about_file = BASE_DIR / "about.json"
    if about_file.exists():
        return json.loads(about_file.read_text(encoding="utf-8"))


# --- User Tasks Endpoints ---
@app.get("/api/user_tasks")
async def get_user_tasks():
    """List all user-defined scheduled tasks."""
    return load_user_tasks()


@app.post("/api/user_tasks")
async def create_user_task(req: dict):
    """Create a new user task."""
    data = load_user_tasks()
    task = {
        "id": "task_" + uuid.uuid4().hex[:8],
        "name": req.get("name", "未命名任务"),
        "enabled": bool(req.get("enabled", False)),
        "action": req.get("action", ""),
        "params": req.get("params", {}),
        "schedule": req.get("schedule", {"type": "daily", "time": "20:00"}),
        "last_run": "",
    }
    data["tasks"].append(task)
    save_user_tasks(data)
    return {"status": "ok", "task": task}


@app.put("/api/user_tasks/{task_id}")
async def update_user_task(task_id: str, req: dict):
    """Update a user task."""
    data = load_user_tasks()
    for t in data["tasks"]:
        if t["id"] == task_id:
            for key in ("name", "enabled", "action", "params", "schedule"):
                if key in req:
                    t[key] = req[key]
            save_user_tasks(data)
            return {"status": "ok", "task": t}
    raise HTTPException(status_code=404, detail="Task not found")


@app.delete("/api/user_tasks/{task_id}")
async def delete_user_task(task_id: str):
    """Delete a user task."""
    data = load_user_tasks()
    data["tasks"] = [t for t in data["tasks"] if t["id"] != task_id]
    save_user_tasks(data)
    return {"status": "ok"}


# --- Notifications Endpoints ---
@app.get("/api/notifications")
async def get_notifications(unread: bool = False):
    """Get notifications. If unread=true, only return unread ones."""
    data = load_notifications()
    notifs = data.get("notifications", [])
    if unread:
        notifs = [n for n in notifs if not n.get("read", False)]
    return {"notifications": notifs}


@app.post("/api/notifications/read")
async def mark_notifications_read(req: dict):
    """Mark notifications as read. Body: {"ids": ["notif_xxx", ...]}"""
    ids = req.get("ids", [])
    data = load_notifications()
    for n in data.get("notifications", []):
        if n.get("id") in ids:
            n["read"] = True
    save_notifications(data)
    return {"status": "ok"}


@app.get("/api/status")
async def get_status():
    """Get system status."""
    providers = load_providers()
    active_id = providers.get("activeId", "")
    active_provider = None
    for p in providers.get("providers", []):
        if p["id"] == active_id:
            active_provider = p
            break

    model_name = "Unknown"
    if active_provider:
        provider_models = active_provider.get("models", {})
        default_tier = provider_models.get("default", "sonnet")
        model_name = provider_models.get(default_tier) or provider_models.get("sonnet") or provider_models.get("main", active_provider.get("name", "Unknown"))
    elif _agents:
        first_agent = next(iter(_agents.values()))
        model_name = getattr(first_agent.llm, "model_name", None) or getattr(first_agent.llm, "model", "Unknown")

    tools = []
    if _agents:
        first_agent = next(iter(_agents.values()))
        tools = [t.name for t in first_agent.tools]

    skills = scan_skills(BASE_DIR / "skills")
    tasks = []
    if _agents:
        first_agent = next(iter(_agents.values()))
        tasks = first_agent.bg_loop.list_tasks()

    return {
        "status": "running",
        "model": model_name,
        "tools": tools,
        "skills": [{"name": s["name"], "description": s["description"]} for s in skills],
        "tasks": tasks,
        "work_dir": _agents[next(iter(_agents))].get_work_dir() if _agents else "",
        "memory_dir": str(_agents[next(iter(_agents))].memory.memory_dir) if _agents else "",
        "activeProvider": active_provider,
        "sessions": list(_agents.keys()),
    }


@app.get("/api/skills")
async def get_skills():
    """Get all skills."""
    skills = scan_skills(BASE_DIR / "skills")
    result = []
    for s in skills:
        skill_dir = BASE_DIR / "skills" / s["path"].rsplit("/", 1)[0]
        result.append({
            "name": s["name"],
            "description": s["description"],
            "path": s["path"],
            "has_skill_md": (skill_dir / "SKILL.md").exists(),
        })
    return result


@app.get("/api/skills/{skill_name}")
async def get_skill_detail(skill_name: str):
    """Get skill detail."""
    skill_path = BASE_DIR / "skills" / skill_name / "SKILL.md"
    if not skill_path.exists():
        raise HTTPException(status_code=404, detail=f"Skill {skill_name} not found")
    content = skill_path.read_text(encoding="utf-8")
    return {"name": skill_name, "content": content}


@app.get("/api/tools")
async def get_tools():
    """Get all tools."""
    if not _agents:
        a = get_or_create_agent("default")
    else:
        a = next(iter(_agents.values()))
    return [{"name": t.name, "description": t.description} for t in a.tools]


@app.get("/api/memory")
async def get_memory(session_id: str = "default"):
    """Get memory file contents."""
    a = get_or_create_agent(session_id)
    result = {}
    memory_dir = a.memory.memory_dir

    for name, path in a.memory.get_memory_files().items():
        if path.exists():
            try:
                content = path.read_text(encoding="utf-8")
                result[name] = content
            except Exception:
                result[name] = ""
        else:
            result[name] = ""

    logs_dir = memory_dir / "logs"
    chat_summary = []
    if logs_dir.exists():
        try:
            for log_file in sorted(logs_dir.glob("*.jsonl"), reverse=True)[:3]:
                date = log_file.stem
                lines = log_file.read_text(encoding="utf-8").strip().split("\n")
                chat_summary.append(f"## {date}（{len(lines)} 条消息）")
                for line in lines[-20:]:
                    try:
                        import json
                        entry = json.loads(line)
                        role = entry.get("role", entry.get("type", "?"))
                        content = entry.get("content", "")[:80]
                        if content.strip():
                            role_icon = {"user": "👤", "assistant": "🌱", "human": "👤"}.get(role, "💬")
                            chat_summary.append(f"{role_icon} {content}")
                    except Exception:
                        pass
        except Exception:
            pass

    if result.get("memory", "").strip():
        result["memory"] += "\n\n## 近期对话记录\n" + "\n".join(chat_summary) if chat_summary else ""
    elif chat_summary:
        result["memory"] = "# 长期记忆\n\n## 近期对话记录\n" + "\n".join(chat_summary)

    result["chat_logs"] = []
    return result


@app.post("/api/memory/update")
async def update_memory(name: str, content: str, session_id: str = "default"):
    """Update memory file."""
    a = get_or_create_agent(session_id)
    memory_dir = a.memory.memory_dir

    file_map = {
        "identity": memory_dir / "IDENTITY.md",
        "soul": memory_dir / "SOUL.md",
        "user": memory_dir / "USER.md",
        "memory": memory_dir / "MEMORY.md",
    }

    if name not in file_map:
        raise HTTPException(status_code=400, detail=f"Unknown memory file: {name}")

    file_map[name].write_text(content, encoding="utf-8")
    return {"status": "ok", "message": f"{name} updated"}


@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest):
    """Sync chat endpoint."""
    a = get_or_create_agent(req.session_id)
    try:
        response = await a.chat(req.message)
        return {"response": response, "session_id": req.session_id}
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e), "session_id": req.session_id},
        )


@app.post("/api/workdir")
async def set_work_dir(req: WorkDirRequest, session_id: str = "default"):
    """Set work directory."""
    a = get_or_create_agent(session_id)
    result = a.set_work_dir(req.path)
    return {"status": "ok", "message": result}


@app.post("/api/clear")
async def clear_history(session_id: str = "default"):
    """Clear chat history for a session."""
    a = get_or_create_agent(session_id)
    a.clear_history()
    return {"status": "ok", "message": "Conversation history cleared"}


@app.get("/api/tasks")
async def get_tasks():
    """Get all task statuses."""
    if _agents:
        a = next(iter(_agents.values()))
        return a.bg_loop.list_tasks()
    return []


# --- Session Persistence Endpoints ---
@app.get("/api/sessions/persisted")
async def list_persisted_sessions():
    """List all persisted sessions (without messages)."""
    return {"sessions": list_session_files()}


@app.get("/api/sessions/{session_id}/messages")
async def get_session_messages(session_id: str):
    """Get full messages of a persisted session."""
    data = load_session_file(session_id)
    if not data:
        return {"messages": [], "name": ""}
    return {
        "messages": data.get("messages", []),
        "name": data.get("name", ""),
        "created_at": data.get("created_at", ""),
    }


@app.put("/api/sessions/{session_id}/messages")
async def save_session_messages(session_id: str, req: dict):
    """Save session messages + name to disk."""
    messages = req.get("messages", [])
    name = req.get("name", "")

    existing = load_session_file(session_id)
    created_at = existing.get("created_at") or datetime.now().isoformat()

    data = {
        "id": session_id,
        "name": name,
        "created_at": created_at,
        "updated_at": datetime.now().isoformat(),
        "messages": messages,
    }
    save_session_file(session_id, data)
    return {"status": "ok"}


# --- Multi-Session Endpoints ---
@app.get("/api/sessions")
async def get_sessions():
    """List all active sessions."""
    result = []
    for sid, agent in _agents.items():
        model_name = getattr(agent.llm, "model_name", None) or getattr(agent.llm, "model", "Unknown")
        result.append({
            "id": sid,
            "model": model_name,
            "message_count": len(agent.messages),
            "work_dir": agent.get_work_dir(),
            "created_at": getattr(agent, "_created_at", ""),
        })
    return result


@app.post("/api/sessions")
async def create_session():
    """Create a new session."""
    session_id = f"session-{uuid.uuid4().hex[:8]}"
    a = get_or_create_agent(session_id)
    a._created_at = datetime.now().isoformat()

    save_session_file(session_id, {
        "id": session_id,
        "name": "",
        "created_at": a._created_at,
        "updated_at": a._created_at,
        "messages": [],
    })

    return {"session_id": session_id, "status": "created"}


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    """Delete a session and its agent."""
    if session_id in _agents:
        agent = _agents.pop(session_id)
        agent.close()

    f = session_file(session_id)
    if f.exists():
        try:
            f.unlink()
        except Exception:
            pass

    return {"status": "ok", "message": f"Session {session_id} deleted"}


# --- Auto Shutdown ---
@app.post("/api/shutdown")
async def shutdown_server():
    """Gracefully shutdown the server."""
    print("[Sprout] Shutdown requested by client...")
    os._exit(0)


# --- Permission Management ---
@app.post("/api/permission/{session_id}")
async def set_permission(session_id: str, mode: str = "ask"):
    """Set permission mode: full / ask / safe"""
    a = get_or_create_agent(session_id)
    msg = a.set_permission_mode(mode)
    return {"status": "ok", "message": msg, "mode": a.get_permission_mode()}


@app.get("/api/permission/{session_id}")
async def get_permission(session_id: str):
    """Get current permission mode."""
    a = get_or_create_agent(session_id)
    return {"mode": a.get_permission_mode()}

# --- Stop Generation ---
@app.post("/api/stop/{session_id}")
async def stop_generation(session_id: str):
    """Stop ongoing generation for a session."""
    if session_id in _stream_tasks:
        task = _stream_tasks[session_id]
        task.cancel()
        del _stream_tasks[session_id]
        return {"status": "ok", "message": "Generation stopped"}
    return {"status": "ok", "message": "No active generation"}


# --- File Upload ---
@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...), session_id: str = "default"):
    """Upload a file and return its path for agent access."""
    session_upload = UPLOAD_DIR / session_id
    session_upload.mkdir(parents=True, exist_ok=True)

    safe_name = Path(file.filename).name
    file_path = session_upload / safe_name
    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)

    return {
        "status": "ok",
        "filename": safe_name,
        "path": str(file_path),
        "size": len(content),
        "message": f"File uploaded: {safe_name}",
    }


# --- Provider Management ---
@app.get("/api/providers")
async def get_providers():
    """List all providers."""
    data = load_providers()
    return data


@app.post("/api/providers")
async def add_provider(req: ProviderCreate):
    """Add a new provider."""
    data = load_providers()
    new_id = str(uuid.uuid4())
    provider = {
        "id": new_id,
        "name": req.name,
        "apiKey": req.apiKey,
        "baseUrl": req.baseUrl,
        "apiFormat": req.apiFormat,
        "models": req.models,
        "runtimeKind": req.runtimeKind,
    }
    data["providers"].append(provider)
    save_providers(data)
    return {"status": "ok", "provider": provider}


@app.put("/api/providers/{provider_id}")
async def update_provider(provider_id: str, req: ProviderUpdate):
    """Update a provider."""
    data = load_providers()
    for p in data["providers"]:
        if p["id"] == provider_id:
            if req.name is not None:
                p["name"] = req.name
            if req.apiKey is not None:
                p["apiKey"] = req.apiKey
            if req.baseUrl is not None:
                p["baseUrl"] = req.baseUrl
            if req.apiFormat is not None:
                p["apiFormat"] = req.apiFormat
            if req.models is not None:
                p["models"] = req.models
            if req.runtimeKind is not None:
                p["runtimeKind"] = req.runtimeKind
            save_providers(data)
            return {"status": "ok", "provider": p}
    raise HTTPException(status_code=404, detail="Provider not found")


@app.delete("/api/providers/{provider_id}")
async def delete_provider(provider_id: str):
    """Delete a provider."""
    data = load_providers()
    data["providers"] = [p for p in data["providers"] if p["id"] != provider_id]
    if data.get("activeId") == provider_id:
        data["activeId"] = data["providers"][0]["id"] if data["providers"] else ""
    save_providers(data)
    return {"status": "ok"}


@app.post("/api/providers/switch")
async def switch_provider(req: SwitchProviderRequest):
    """Switch active provider. Creates new agent with the provider's config."""
    data = load_providers()
    target = None
    for p in data["providers"]:
        if p["id"] == req.provider_id:
            target = p
            break

    if not target:
        raise HTTPException(status_code=404, detail="Provider not found")

    data["activeId"] = req.provider_id
    save_providers(data)

    runtime = target.get("runtimeKind", "deepseek")
    base_url = target["baseUrl"]
    api_key = target["apiKey"]
    models = target.get("models", {})
    default_tier = models.get("default", "sonnet")
    main_model = models.get(default_tier) or models.get("sonnet") or models.get("main", "deepseek-chat")
    haiku_model = models.get("haiku", main_model)

    if runtime == "qwen":
        os.environ["MAIN_MODEL"] = "qwen"
        os.environ["DASHSCOPE_API_KEY"] = api_key
        os.environ["DASHSCOPE_BASE_URL"] = base_url
        os.environ["QWEN_MODEL"] = main_model
    elif runtime == "openai_compatible":
        os.environ["MAIN_MODEL"] = "openai_compatible"
        os.environ["DEEPSEEK_API_KEY"] = api_key
        os.environ["DEEPSEEK_BASE_URL"] = base_url
        os.environ["DEEPSEEK_MODEL"] = main_model
    else:
        os.environ["MAIN_MODEL"] = "deepseek"
        os.environ["DEEPSEEK_API_KEY"] = api_key
        os.environ["DEEPSEEK_BASE_URL"] = base_url
        os.environ["DEEPSEEK_MODEL"] = main_model

    session_ids = list(_agents.keys())
    for sid in session_ids:
        old_agent = _agents[sid]
        old_messages = old_agent.messages.copy()
        try:
            new_agent = RaspiClawAgent(base_dir=BASE_DIR, model=main_model)
            new_agent.messages = old_messages
            new_agent._created_at = getattr(old_agent, "_created_at", datetime.now().isoformat())
            old_agent.close()
            _agents[sid] = new_agent
        except Exception as e:
            print(f"[Provider Switch] Error recreating agent for session {sid}: {e}")

    return {
        "status": "ok",
        "activeProvider": target,
        "message": f"Switched to {target['name']}",
    }


# --- Data File Endpoints ---
@app.get("/api/data/{filename}")
async def get_data_file(filename: str):
    """Get data file."""
    data_dir = BASE_DIR / "data"
    file_path = data_dir / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"File {filename} not found")
    return FileResponse(file_path)


# --- Chat History for Session ---
@app.get("/api/chat/history/{session_id}")
async def get_chat_history(session_id: str):
    """Get chat history for a session."""
    if session_id not in _agents:
        return {"messages": []}
    a = _agents[session_id]
    result = []
    for msg in a.messages:
        entry = {"type": getattr(msg, "type", "unknown")}
        if hasattr(msg, "content") and msg.content:
            entry["content"] = msg.content
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            entry["tool_calls"] = [
                {"name": tc.get("name", ""), "args": tc.get("args", {})}
                for tc in msg.tool_calls
            ]
        result.append(entry)
    return {"messages": result}


# --- WebSocket Endpoint (Streaming Chat) ---
@app.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket):
    """WebSocket streaming chat with multi-session support."""
    global _client_count
    _client_count += 1
    await websocket.accept()

    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                user_input = msg.get("message", "")
                session_id = msg.get("session_id", "default")
            except json.JSONDecodeError:
                user_input = data
                session_id = "default"

            if not user_input.strip():
                continue

            a = get_or_create_agent(session_id)

            await websocket.send_json({
                "type": "start",
                "session_id": session_id,
            })

            async def stream_response(agent, text, sid):
                full_response = ""
                try:
                    async for event in agent.stream_chat_with_events(text):
                        event["session_id"] = sid
                        await websocket.send_json(event)
                        if event.get("type") == "final":
                            full_response = event.get("content", "")
                except asyncio.CancelledError:
                    await websocket.send_json({
                        "type": "stopped",
                        "session_id": sid,
                        "content": "[Generation stopped by user]",
                    })
                except Exception as e:
                    await websocket.send_json({
                        "type": "error",
                        "session_id": sid,
                        "content": str(e),
                    })
                finally:
                    await websocket.send_json({
                        "type": "done",
                        "session_id": sid,
                        "content": full_response,
                    })
                    if sid in _stream_tasks:
                        del _stream_tasks[sid]

            task = asyncio.create_task(stream_response(a, user_input, session_id))
            _stream_tasks[session_id] = task

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "content": str(e)})
        except Exception:
            pass
    finally:
        _client_count -= 1
        if _client_count <= 0:
            asyncio.create_task(auto_shutdown_check())


# --- Startup ---
def main():
    import uvicorn
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

    host = os.getenv("API_HOST", "127.0.0.1")
    port = int(os.getenv("API_PORT", "8000"))

    print(f"[Sprout] Web API v1.0 starting at http://{host}:{port}")
    print(f"[Sprout] WebSocket at ws://{host}:{port}/ws/chat")
    print(f"[Sprout] Multi-session + Provider management enabled")

    print("[Sprout] Initializing default Agent...")
    get_or_create_agent("default")._created_at = datetime.now().isoformat()
    print("[Sprout] Agent initialized successfully")

    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()