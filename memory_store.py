"""
memory_store.py - 持久化记忆层

三层记忆的JSON存储:
- working_memory/: 当前工作台（会话级，每个项目一个文件）
- project_memory/: 项目记忆（终稿后归档，SQLite）
- long_term_memory/: 长期记忆（素材卡片+写作画像，JSON文件）
"""
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"


# ── 数据库初始化 ──────────────────────────────────────────

def get_db():
    """获取SQLite连接（项目记忆 + 参数存储）"""
    db_path = DATA_DIR / "orchestrator.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    """初始化数据库表"""
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            status TEXT DEFAULT 'active',
            created_at TEXT,
            archived_at TEXT
        );
        CREATE TABLE IF NOT EXISTS material_cards (
            id TEXT PRIMARY KEY,
            card_type TEXT,
            source TEXT,
            summary TEXT,
            content TEXT,
            tags TEXT,
            usage_count INTEGER DEFAULT 0,
            delete_count INTEGER DEFAULT 0,
            retention_score REAL DEFAULT 0.0,
            anchor_relevance REAL DEFAULT 0.0,
            created_at TEXT,
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS usage_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            card_id TEXT,
            project_id TEXT,
            kept INTEGER,
            timestamp TEXT,
            anchor_relevance REAL DEFAULT 0.0,
            FOREIGN KEY(card_id) REFERENCES material_cards(id)
        );
        CREATE TABLE IF NOT EXISTS param_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            param_name TEXT,
            before_value REAL,
            after_value REAL,
            timestamp TEXT
        );
        CREATE TABLE IF NOT EXISTS param_current (
            name TEXT PRIMARY KEY,
            current_value REAL,
            default_value REAL,
            stabilization_projects INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS event_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            priority TEXT,
            layer TEXT,
            role TEXT,
            description TEXT,
            target_paragraph TEXT,
            timestamp TEXT,
            resolved INTEGER DEFAULT 0
        );
    """)
    conn.commit()
    conn.close()


# ── 工作记忆（当前工作台） ──────────────────────────────

def save_workbench(project_id: str, workbench: dict):
    """保存当前工作台状态到JSON"""
    path = DATA_DIR / "working_memory" / f"{project_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(workbench, ensure_ascii=False, indent=2))


def load_workbench(project_id: str) -> dict:
    """加载工作台状态"""
    path = DATA_DIR / "working_memory" / f"{project_id}.json"
    if path.exists():
        return json.loads(path.read_text())
    return {"anchor": {}, "framework": {}, "content": {}, "state": "blank"}


# ── 素材卡片（长期记忆核心） ─────────────────────────────

def add_material_card(card: dict) -> str:
    """新增素材卡片"""
    conn = get_db()
    now = datetime.utcnow().isoformat()
    conn.execute("""
        INSERT OR REPLACE INTO material_cards
        (id, card_type, source, summary, content, tags,
         usage_count, delete_count, retention_score,
         anchor_relevance, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        card.get("id"), card.get("card_type"), card.get("source"),
        card.get("summary"), card.get("content"),
        json.dumps(card.get("tags", []), ensure_ascii=False),
        card.get("usage_count", 0), card.get("delete_count", 0),
        card.get("retention_score", 0.0),
        card.get("anchor_relevance", 0.0), now, now
    ))
    conn.commit()
    conn.close()
    return card.get("id")


def record_usage(card_id: str, project_id: str, kept: bool,
                 anchor_relevance: float = 0.0):
    """记录素材使用情况（用于质量加权）"""
    conn = get_db()
    now = datetime.utcnow().isoformat()
    conn.execute("""
        INSERT INTO usage_records (card_id, project_id, kept, timestamp, anchor_relevance)
        VALUES (?,?,?,?,?)
    """, (card_id, project_id, 1 if kept else 0, now, anchor_relevance))
    # 更新计数
    if kept:
        conn.execute("UPDATE material_cards SET usage_count = usage_count + 1, updated_at=? WHERE id=?",
                     (now, card_id))
    else:
        conn.execute("UPDATE material_cards SET delete_count = delete_count + 1, updated_at=? WHERE id=?",
                     (now, card_id))
    conn.commit()
    conn.close()


def get_material_cards(card_type: str = None, tags: list = None) -> list:
    """查询素材卡片（支持类型和标签过滤）"""
    conn = get_db()
    query = "SELECT * FROM material_cards"
    params = []
    conditions = []
    if card_type:
        conditions.append("card_type=?")
        params.append(card_type)
    if tags:
        for tag in tags:
            conditions.append("tags LIKE ?")
            params.append(f"%{tag}%")
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY (usage_count - delete_count) * retention_score DESC LIMIT 50"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── 项目隔离 ───────────────────────────────────────────

def create_project(project_id: str) -> dict:
    """创建新项目沙箱"""
    conn = get_db()
    now = datetime.utcnow().isoformat()
    conn.execute(
        "INSERT OR IGNORE INTO projects (id, status, created_at) VALUES (?,?,?)",
        (project_id, "active", now)
    )
    conn.commit()
    conn.close()
    return {"id": project_id, "status": "active", "created_at": now}


def archive_project(project_id: str):
    """归档项目：结束沙箱，标记可提升到长期记忆"""
    conn = get_db()
    now = datetime.utcnow().isoformat()
    conn.execute(
        "UPDATE projects SET status=?, archived_at=? WHERE id=?",
        ("archived", now, project_id)
    )
    conn.commit()
    conn.close()


def get_active_projects() -> list:
    """获取所有活跃项目"""
    conn = get_db()
    rows = conn.execute(
        "SELECT id, created_at FROM projects WHERE status='active'"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
