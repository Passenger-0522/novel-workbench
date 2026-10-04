"""
小说创作工作台 - 后端服务
"""
import os
import subprocess
import asyncio
from pathlib import Path
from typing import Optional
from datetime import datetime

import aiofiles
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ── 配置 ──────────────────────────────────────────────
ROOT = Path(__file__).parent.parent  # /Users/.../小说
WORKBENCH_DIR = Path(__file__).parent

app = FastAPI(title="小说工作台", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 数据模型 ──────────────────────────────────────────
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
def safe_path(rel_path: str) -> Path:
    """确保路径在项目根目录内，防止路径穿越攻击"""
    target = (ROOT / rel_path).resolve()
    if not str(target).startswith(str(ROOT)):
        raise HTTPException(status_code=403, detail="路径不合法")
    return target

def run_git(args: list[str]) -> dict:
    """执行 git 命令"""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30
        )
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "stdout": "", "stderr": "Git 命令超时"}
    except Exception as e:
        return {"success": False, "stdout": "", "stderr": str(e)}

def build_file_tree(path: Path, rel_base: Path) -> dict:
    """递归构建文件树"""
    skip = {".workbench", ".git", ".DS_Store", "__pycache__"}
    
    if path.name in skip:
        return None
    
    rel_path = str(path.relative_to(rel_base))
    
    if path.is_file():
        if path.suffix in {".md", ".txt"}:
            # 统计字数
            try:
                text = path.read_text(encoding="utf-8")
                # 排除 markdown 语法，粗略统计中文字数
                import re
                clean = re.sub(r'[#\-\*\|\s`>]', '', text)
                word_count = len(re.findall(r'[\u4e00-\u9fff]', clean))
            except:
                word_count = 0
            return {
                "type": "file",
                "name": path.name,
                "path": rel_path,
                "words": word_count,
            }
        return None
    
    if path.is_dir():
        children = []
        for child in sorted(path.iterdir()):
            if child.name in skip or child.name.startswith("."):
                continue
            node = build_file_tree(child, rel_base)
            if node:
                children.append(node)
        if children or path == rel_base:
            return {
                "type": "dir",
                "name": path.name,
                "path": rel_path,
                "children": children,
            }
    return None

# ── API 路由 ──────────────────────────────────────────

@app.get("/api/tree")
async def get_tree():
    """获取文件树"""
    tree = build_file_tree(ROOT, ROOT)
    return tree

@app.get("/api/file")
async def read_file(path: str):
    """读取文件内容"""
    target = safe_path(path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    async with aiofiles.open(target, encoding="utf-8") as f:
        content = await f.read()
    return {"path": path, "content": content}

@app.post("/api/file")
async def write_file(body: FileContent):
    """保存文件内容"""
    target = safe_path(body.path)
    target.parent.mkdir(parents=True, exist_ok=True)
    async with aiofiles.open(target, "w", encoding="utf-8") as f:
        await f.write(body.content)
    return {"success": True, "message": f"已保存：{body.path}"}

@app.post("/api/file/new")
async def create_file(body: NewFile):
    """新建文件"""
    target = safe_path(body.path)
    if target.exists():
        raise HTTPException(status_code=409, detail="文件已存在")
    target.parent.mkdir(parents=True, exist_ok=True)
    async with aiofiles.open(target, "w", encoding="utf-8") as f:
        await f.write(body.content)
    return {"success": True}

@app.delete("/api/file")
async def delete_file(path: str):
    """删除文件"""
    target = safe_path(path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    target.unlink()
    return {"success": True}

@app.get("/api/git/status")
async def git_status():
    """Git 状态"""
    result = run_git(["status", "--porcelain"])
    log = run_git(["log", "--oneline", "-10"])
    branch = run_git(["branch", "--show-current"])
    remote = run_git(["remote", "get-url", "origin"])
    
    changed_files = []
    for line in result["stdout"].splitlines():
        if line.strip():
            status = line[:2].strip()
            file_path = line[3:].strip()
            changed_files.append({"status": status, "file": file_path})
    
    commits = []
    for line in log["stdout"].splitlines():
        if line.strip():
            parts = line.split(" ", 1)
            commits.append({
                "hash": parts[0],
                "message": parts[1] if len(parts) > 1 else ""
            })
    
    return {
        "branch": branch["stdout"],
        "remote": remote["stdout"],
        "changed": changed_files,
        "commits": commits,
        "clean": len(changed_files) == 0,
    }

@app.post("/api/git/commit")
async def git_commit(body: GitCommit):
    """Git commit (并可选 push)"""
    # 添加所有变更
    add = run_git(["add", "-A"])
    if not add["success"]:
        raise HTTPException(status_code=500, detail=f"git add 失败: {add['stderr']}")
    
    # 提交
    commit = run_git(["commit", "-m", body.message])
    if not commit["success"]:
        if "nothing to commit" in commit["stdout"] or "nothing to commit" in commit["stderr"]:
            return {"success": True, "message": "没有需要提交的内容", "pushed": False}
        raise HTTPException(status_code=500, detail=f"commit 失败: {commit['stderr']}")
    
    pushed = False
    push_output = ""
    if body.push:
        push = run_git(["push"])
        pushed = push["success"]
        push_output = push["stdout"] or push["stderr"]
    
    return {
        "success": True,
        "message": commit["stdout"],
        "pushed": pushed,
        "push_output": push_output,
    }

@app.post("/api/git/push")
async def git_push():
    """单独 Push"""
    result = run_git(["push"])
    return {"success": result["success"], "output": result["stdout"] or result["stderr"]}

@app.get("/api/stats")
async def get_stats():
    """统计全书字数"""
    total = 0
    chapters = 0
    files_info = []
    
    text_dir = ROOT / "正文"
    if text_dir.exists():
        for md_file in sorted(text_dir.rglob("*.md")):
            try:
                import re
                text = md_file.read_text(encoding="utf-8")
                clean = re.sub(r'[#\-\*\|\s`>]', '', text)
                words = len(re.findall(r'[\u4e00-\u9fff]', clean))
                if words > 10:  # 排除空文件
                    total += words
                    chapters += 1
                    files_info.append({
                        "name": md_file.name,
                        "words": words,
                        "path": str(md_file.relative_to(ROOT))
                    })
            except:
                pass
    
    return {
        "total_words": total,
        "chapters": chapters,
        "files": files_info,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }

# ── 前端入口 ──────────────────────────────────────────
@app.get("/")
async def index():
    index_file = WORKBENCH_DIR / "index.html"
    return FileResponse(index_file)

if __name__ == "__main__":
    import uvicorn
    print("🚀 小说工作台启动中...")
    print(f"📁 项目目录：{ROOT}")
    print(f"🌐 访问地址：http://localhost:8765")
    uvicorn.run(app, host="0.0.0.0", port=8765, log_level="warning")
