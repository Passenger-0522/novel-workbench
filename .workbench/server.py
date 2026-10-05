"""
小说创作工作台 - 后端服务（升级版）
支持：文件管理 / Git操作 / 结构化数据（人物/大纲/章节/伏笔）
"""
import os
import subprocess
import json
from pathlib import Path
from datetime import datetime
import re

import aiofiles
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

# ── 配置 ──────────────────────────────────────────────
ROOT         = Path(__file__).parent.parent   # /Users/.../小说
WORKBENCH_DIR = Path(__file__).parent          # /Users/.../小说/.workbench
DATA_DIR     = WORKBENCH_DIR / "data"          # 结构化数据目录

app = FastAPI(title="小说工作台", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ── Pydantic 模型 ──────────────────────────────────────
class FileContent(BaseModel):
    path: str
    content: str

class GitCommit(BaseModel):
    message: str
    push: bool = False

class NewFile(BaseModel):
    path: str
    content: str = ""

# ── 工具函数 ──────────────────────────────────────────
def safe_path(rel: str) -> Path:
    t = (ROOT / rel).resolve()
    if not str(t).startswith(str(ROOT)):
        raise HTTPException(403, "路径不合法")
    return t

def run_git(args):
    try:
        r = subprocess.run(["git"] + args, cwd=ROOT, capture_output=True, text=True, timeout=30)
        return {"success": r.returncode == 0, "stdout": r.stdout.strip(), "stderr": r.stderr.strip()}
    except Exception as e:
        return {"success": False, "stdout": "", "stderr": str(e)}

def count_words(text: str) -> int:
    clean = re.sub(r'[#\-\*\|\s`>~\[\]()!]', '', text)
    return len(re.findall(r'[\u4e00-\u9fff]', clean))

def build_tree(path: Path, base: Path) -> dict:
    SKIP = {".workbench", ".git", ".DS_Store", "__pycache__", ".server.pid", ".server.log"}
    if path.name in SKIP or path.name.startswith("."):
        return None
    rel = str(path.relative_to(base))
    if path.is_file():
        if path.suffix not in {".md", ".txt"}:
            return None
        try:
            words = count_words(path.read_text(encoding="utf-8"))
        except:
            words = 0
        return {"type": "file", "name": path.name, "path": rel, "words": words}
    if path.is_dir():
        children = []
        for child in sorted(path.iterdir()):
            if child.name in SKIP or child.name.startswith("."):
                continue
            node = build_tree(child, base)
            if node:
                children.append(node)
        if children or path == base:
            return {"type": "dir", "name": path.name, "path": rel, "children": children}
    return None

# ── 文件 API ──────────────────────────────────────────
@app.get("/api/tree")
async def get_tree():
    return build_tree(ROOT, ROOT)

@app.get("/api/file")
async def read_file(path: str):
    t = safe_path(path)
    if not t.exists():
        raise HTTPException(404, "文件不存在")
    async with aiofiles.open(t, encoding="utf-8") as f:
        return {"path": path, "content": await f.read()}

@app.post("/api/file")
async def write_file(body: FileContent):
    t = safe_path(body.path)
    t.parent.mkdir(parents=True, exist_ok=True)
    async with aiofiles.open(t, "w", encoding="utf-8") as f:
        await f.write(body.content)
    return {"success": True}

@app.post("/api/file/new")
async def create_file(body: NewFile):
    t = safe_path(body.path)
    if t.exists():
        raise HTTPException(409, "文件已存在")
    t.parent.mkdir(parents=True, exist_ok=True)
    async with aiofiles.open(t, "w", encoding="utf-8") as f:
        await f.write(body.content)
    return {"success": True}

@app.delete("/api/file")
async def delete_file(path: str):
    t = safe_path(path)
    if not t.exists():
        raise HTTPException(404, "不存在")
    t.unlink()
    return {"success": True}

# ── 结构化数据 API（人物/大纲/章节/伏笔）──────────────
@app.get("/api/data/{kind}")
async def get_data(kind: str):
    DATA_DIR.mkdir(exist_ok=True)
    fp = DATA_DIR / f"{kind}.json"
    if not fp.exists():
        return {} if kind == "outline" else []
    return json.loads(fp.read_text(encoding="utf-8"))

@app.post("/api/data/{kind}")
async def post_data(kind: str, request: Request):
    DATA_DIR.mkdir(exist_ok=True)
    body = await request.json()
    (DATA_DIR / f"{kind}.json").write_text(
        json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"success": True}

# ── Git API ───────────────────────────────────────────
@app.get("/api/git/status")
async def git_status():
    result  = run_git(["status", "--porcelain"])
    log     = run_git(["log", "--oneline", "-10"])
    branch  = run_git(["branch", "--show-current"])
    remote  = run_git(["remote", "get-url", "origin"])
    changed = []
    for line in result["stdout"].splitlines():
        if line.strip():
            changed.append({"status": line[:2].strip(), "file": line[3:].strip()})
    commits = []
    for line in log["stdout"].splitlines():
        if line.strip():
            parts = line.split(" ", 1)
            commits.append({"hash": parts[0], "message": parts[1] if len(parts) > 1 else ""})
    return {"branch": branch["stdout"], "remote": remote["stdout"],
            "changed": changed, "commits": commits, "clean": len(changed) == 0}

@app.post("/api/git/commit")
async def git_commit(body: GitCommit):
    add = run_git(["add", "-A"])
    if not add["success"]:
        raise HTTPException(500, f"git add 失败: {add['stderr']}")
    commit = run_git(["commit", "-m", body.message])
    if not commit["success"]:
        if "nothing to commit" in commit["stdout"] + commit["stderr"]:
            return {"success": True, "message": "无变更", "pushed": False}
        raise HTTPException(500, f"commit 失败: {commit['stderr']}")
    pushed, push_out = False, ""
    if body.push:
        push = run_git(["push"])
        pushed, push_out = push["success"], push["stdout"] or push["stderr"]
    return {"success": True, "message": commit["stdout"], "pushed": pushed, "push_output": push_out}

@app.post("/api/git/push")
async def git_push():
    r = run_git(["push"])
    return {"success": r["success"], "output": r["stdout"] or r["stderr"]}

# ── 统计 API ─────────────────────────────────────────
@app.get("/api/stats")
async def get_stats():
    total, chapters = 0, 0
    text_dir = ROOT / "正文"
    if text_dir.exists():
        for f in sorted(text_dir.rglob("*.md")):
            try:
                w = count_words(f.read_text(encoding="utf-8"))
                if w > 10:
                    total += w
                    chapters += 1
            except:
                pass
    return {"total_words": total, "chapters": chapters,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M")}

# ── 前端入口 ──────────────────────────────────────────
@app.get("/")
async def index():
    return FileResponse(WORKBENCH_DIR / "index.html")

if __name__ == "__main__":
    import uvicorn
    print("🚀 小说工作台 v2.0 启动中…")
    print(f"📁 项目：{ROOT}")
    print(f"🌐 地址：http://localhost:8765")
    uvicorn.run(app, host="0.0.0.0", port=8765, log_level="warning")
