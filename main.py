"""
main.py - 编排器后端服务 (Flask)

一套轻量API，承载记忆层、参数管理、项目隔离。
Zeabur 部署：gunicorn main:app
"""
import os
import json
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# ── 初始化 ──────────────────────────────────────────────
from memory_store import init_db, save_workbench, load_workbench
from memory_store import add_material_card, get_material_cards
from memory_store import create_project, archive_project, get_active_projects
from parameter_store import init_params, get_all_params, get_param
from parameter_store import propose_adjustment, confirm_adjustment
from parameter_store import increment_stabilization, reset_to_default
from parameter_store import get_adjustment_history
from project_sandbox import SandboxRegistry

sandbox_registry = SandboxRegistry()

with app.app_context():
    try:
        init_db()
        init_params()
        print("[OK] Database initialized")
    except Exception as e:
        print(f"[WARN] DB init: {e}")


# ── 健康检查 ────────────────────────────────────────────

@app.route("/", methods=["GET"])
def index():
    """API 根路径入口"""
    return jsonify({
        "service": "war-room-orchestrator-backend",
        "version": "1.0",
        "status": "running",
        "endpoints": {
            "health": "/health",
            "workbench": "/workbench/<project_id>",
            "materials": "/materials",
            "material_usage": "/materials/<card_id>/usage",
            "projects": "/projects",
            "project_archive": "/projects/<project_id>/archive",
            "project_sandbox": "/projects/<project_id>/sandbox",
            "params": "/params",
            "param_detail": "/params/<name>",
            "param_propose": "/params/<name>/propose",
            "param_confirm": "/params/<name>/confirm",
            "param_reset": "/params/<name>/reset",
            "param_history": "/params/history",
        },
        "timestamp": datetime.utcnow().isoformat(),
    })


@app.route("/health", methods=["GET"])
def health():
    """服务健康检查"""
    return jsonify({
        "status": "healthy",
        "service": "war-room-orchestrator-backend",
        "timestamp": datetime.utcnow().isoformat(),
    })


# ── 工作记忆API ─────────────────────────────────────────

@app.route("/workbench/<project_id>", methods=["GET", "PUT"])
def workbench(project_id):
    """读写工作台"""
    if request.method == "GET":
        return jsonify(load_workbench(project_id))
    data = request.get_json()
    save_workbench(project_id, data)
    return jsonify({"status": "saved"})


# ── 素材卡片API ─────────────────────────────────────────

@app.route("/materials", methods=["GET", "POST"])
def materials():
    """素材卡片CRUD"""
    if request.method == "GET":
        card_type = request.args.get("type")
        tags = request.args.get("tags")
        tags_list = tags.split(",") if tags else None
        return jsonify(get_material_cards(card_type, tags_list))

    data = request.get_json()
    card_id = add_material_card(data)
    return jsonify({"id": card_id, "status": "created"}), 201


@app.route("/materials/<card_id>/usage", methods=["POST"])
def record_material_usage(card_id):
    """记录素材使用"""
    data = request.get_json()
    from memory_store import record_usage as rec
    rec(card_id, data.get("project_id"), data.get("kept", True),
        data.get("anchor_relevance", 0.0))
    return jsonify({"status": "recorded"})


# ── 项目隔离API ─────────────────────────────────────────

@app.route("/projects", methods=["GET", "POST"])
def projects():
    """项目管理"""
    if request.method == "GET":
        return jsonify(get_active_projects())
    data = request.get_json()
    result = create_project(data.get("id"))
    return jsonify(result), 201


@app.route("/projects/<project_id>/archive", methods=["POST"])
def archive(project_id):
    """归档项目"""
    sandbox = sandbox_registry.get_or_create(project_id)
    data = request.get_json() or {}
    sandbox.promote_to_long_term(
        data.get("approved_card_ids", []),
        data.get("rejected_card_ids", []),
    )
    sandbox_registry.archive(project_id)
    increment_stabilization()
    return jsonify({"status": "archived"})


@app.route("/projects/<project_id>/sandbox", methods=["POST"])
def sandbox_unused(project_id):
    """保存未采纳产出到沙箱"""
    sandbox = sandbox_registry.get_or_create(project_id)
    data = request.get_json()
    sandbox.save_unused_output(data)
    return jsonify({"status": "saved"})


# ── 参数管理API ─────────────────────────────────────────

@app.route("/params", methods=["GET"])
def params():
    """获取所有参数"""
    return jsonify(get_all_params())


@app.route("/params/<name>", methods=["GET"])
def param(name):
    """获取单个参数"""
    return jsonify({"name": name, "value": get_param(name)})


@app.route("/params/<name>/propose", methods=["POST"])
def propose(name):
    """建议参数调整"""
    data = request.get_json()
    result = propose_adjustment(name, data.get("suggested", 0))
    return jsonify(result)


@app.route("/params/<name>/confirm", methods=["POST"])
def confirm(name):
    """确认参数调整"""
    data = request.get_json()
    confirm_adjustment(name, data.get("value"))
    return jsonify({"status": "confirmed"})


@app.route("/params/<name>/reset", methods=["POST"])
def reset_param(name):
    """重置参数为默认"""
    reset_to_default(name)
    return jsonify({"status": "reset"})


@app.route("/params/history", methods=["GET"])
def param_history():
    """调整历史"""
    limit = request.args.get("limit", 50, type=int)
    return jsonify(get_adjustment_history(limit))


# ── 启动 ────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"[BOOT] Orchestrator backend starting on :{port}")
    app.run(host="0.0.0.0", port=port, debug=True)
