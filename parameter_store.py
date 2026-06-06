"""
parameter_store.py - 自优化参数持久化

管理编排器的可调参数，带阻尼约束。
"""
import json
import math
from datetime import datetime
from memory_store import get_db


DEFAULT_PARAMS = {
    "zhou_p2_cooldown_s":       {"default": 90.0,  "current": 90.0},
    "zhang_p2_cooldown_s":      {"default": 60.0,  "current": 60.0},
    "liu_p2_cooldown_s":        {"default": 120.0, "current": 120.0},
    "wu_p1_threshold":          {"default": 0.7,   "current": 0.7},
    "stability_window_minutes": {"default": 30.0,  "current": 30.0},
    "paragraph_lock_timeout_s": {"default": 120.0, "current": 120.0},
}


def init_params():
    """初始化默认参数到数据库"""
    conn = get_db()
    for name, vals in DEFAULT_PARAMS.items():
        conn.execute("""
            INSERT OR IGNORE INTO param_current (name, current_value, default_value, stabilization_projects)
            VALUES (?,?,?,0)
        """, (name, vals["current"], vals["default"]))
    conn.commit()
    conn.close()


def get_all_params() -> dict:
    """获取所有当前参数值"""
    conn = get_db()
    rows = conn.execute("SELECT * FROM param_current").fetchall()
    conn.close()
    result = {}
    for r in rows:
        d = dict(r)
        result[d["name"]] = {
            "current": d["current_value"],
            "default": d["default_value"],
            "stabilization_projects": d["stabilization_projects"],
        }
    return result


def get_param(name: str) -> float:
    """获取单个参数值"""
    conn = get_db()
    row = conn.execute(
        "SELECT current_value FROM param_current WHERE name=?", (name,)
    ).fetchone()
    conn.close()
    return row["current_value"] if row else DEFAULT_PARAMS.get(name, {}).get("current", 0)


def propose_adjustment(name: str, suggested: float) -> dict:
    """
    建议新值，应用阻尼约束：
    1. 绝对值：不低于50%不高于150%
    2. 变化率：单次不超过20%
    3. 稳定性：稳定3个项目才调
    """
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM param_current WHERE name=?", (name,)
    ).fetchone()
    conn.close()

    if not row:
        return {"accepted": False, "reason": "unknown param"}

    current = row["current_value"]
    default = row["default_value"]
    stabilized = row["stabilization_projects"]

    # 约束1：绝对值
    min_bound = default * 0.5
    max_bound = default * 1.5
    clamped = max(min_bound, min(max_bound, suggested))

    # 约束2：变化率
    max_delta = current * 0.20
    delta = clamped - current
    delta = max(-max_delta, min(max_delta, delta))
    proposed = round(current + delta, 1)

    # 约束3：稳定性
    if stabilized < 3 and abs(proposed - current) > 0.01:
        return {
            "accepted": False,
            "reason": f"need {3 - stabilized} more stable project(s)",
            "current": current,
            "proposed": proposed,
        }

    if abs(proposed - current) < 0.01:
        return {"accepted": True, "reason": "no change needed", "current": current}

    return {"accepted": True, "reason": "adjustment proposed", "current": current, "proposed": proposed}


def confirm_adjustment(name: str, new_value: float):
    """确认调整参数并记录历史"""
    conn = get_db()
    now = datetime.utcnow().isoformat()
    row = conn.execute(
        "SELECT current_value FROM param_current WHERE name=?", (name,)
    ).fetchone()
    old_value = row["current_value"] if row else 0

    conn.execute("""
        UPDATE param_current SET current_value=?, stabilization_projects=0 WHERE name=?
    """, (new_value, name))

    conn.execute("""
        INSERT INTO param_history (param_name, before_value, after_value, timestamp)
        VALUES (?,?,?,?)
    """, (name, old_value, new_value, now))

    conn.commit()
    conn.close()


def increment_stabilization():
    """所有参数稳定计数器+1（项目完成后调用）"""
    conn = get_db()
    conn.execute("UPDATE param_current SET stabilization_projects = stabilization_projects + 1")
    conn.commit()
    conn.close()


def reset_to_default(name: str):
    """一键重置为默认值"""
    conn = get_db()
    row = conn.execute(
        "SELECT default_value FROM param_current WHERE name=?", (name,)
    ).fetchone()
    if row:
        conn.execute("""
            UPDATE param_current SET current_value=?, stabilization_projects=0 WHERE name=?
        """, (row["default_value"], name))
    conn.commit()
    conn.close()


def get_adjustment_history(limit: int = 50) -> list:
    """获取调整历史"""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM param_history ORDER BY timestamp DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
