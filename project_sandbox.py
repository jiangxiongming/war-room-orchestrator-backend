"""
project_sandbox.py - 项目隔离域（沙箱）

每个项目独立的记忆空间，终稿后才提升到长期记忆。
"""
import json
from pathlib import Path
from datetime import datetime
from memory_store import (
    DATA_DIR, add_material_card, get_material_cards,
    record_usage, create_project, archive_project, get_active_projects
)


class ProjectSandbox:
    """单个项目的沙箱"""

    def __init__(self, project_id: str):
        self.project_id = project_id
        self._memory_path = DATA_DIR / "sandboxes" / f"{project_id}_project_memory.json"
        self._refs_path = DATA_DIR / "sandboxes" / f"{project_id}_refs.json"

    def _ensure_dirs(self):
        self._memory_path.parent.mkdir(parents=True, exist_ok=True)

    def save_unused_output(self, content: dict):
        """保存未采纳产出到项目记忆"""
        self._ensure_dirs()
        memory = []
        if self._memory_path.exists():
            memory = json.loads(self._memory_path.read_text())
        memory.append({
            **content,
            "saved_at": datetime.utcnow().isoformat(),
        })
        self._memory_path.write_text(json.dumps(memory, ensure_ascii=False, indent=2))

    def get_unused_outputs(self) -> list:
        """获取该项目所有未采纳产出"""
        if self._memory_path.exists():
            return json.loads(self._memory_path.read_text())
        return []

    def record_reference(self, card_id: str):
        """记录从长期记忆引用的素材"""
        self._ensure_dirs()
        refs = []
        if self._refs_path.exists():
            refs = json.loads(self._refs_path.read_text())
        refs.append({"card_id": card_id, "referenced_at": datetime.utcnow().isoformat()})
        self._refs_path.write_text(json.dumps(refs, ensure_ascii=False, indent=2))

    def get_references(self) -> list:
        """获取所有引用记录"""
        if self._refs_path.exists():
            return json.loads(self._refs_path.read_text())
        return []

    def promote_to_long_term(self, approved_card_ids: list,
                              rejected_card_ids: list = None):
        """
        终稿后提升：将批准素材加权，拒绝素材降权
        """
        for card_id in approved_card_ids:
            record_usage(card_id, self.project_id, kept=True)

        if rejected_card_ids:
            for card_id in rejected_card_ids:
                record_usage(card_id, self.project_id, kept=False)

        # 本地产生的优质内容提升为新卡片
        for output in self.get_unused_outputs():
            if output.get("promote", False):
                add_material_card({
                    "id": f"auto_{self.project_id}_{output.get('type', 'unknown')}",
                    "card_type": output.get("type", "case"),
                    "source": "project_output",
                    "summary": output.get("summary", ""),
                    "content": output.get("content", ""),
                    "tags": output.get("tags", []),
                    "usage_count": 0,
                    "delete_count": 0,
                    "retention_score": 0.5,
                    "anchor_relevance": output.get("relevance", 0.0),
                })

    def cleanup(self):
        """归档后清理沙箱文件"""
        if self._memory_path.exists():
            self._memory_path.unlink()
        if self._refs_path.exists():
            self._refs_path.unlink()


class SandboxRegistry:
    """全局沙箱注册表"""

    def __init__(self):
        self._sandboxes: dict[str, ProjectSandbox] = {}

    def get_or_create(self, project_id: str) -> ProjectSandbox:
        if project_id not in self._sandboxes:
            create_project(project_id)
            self._sandboxes[project_id] = ProjectSandbox(project_id)
        return self._sandboxes[project_id]

    def archive(self, project_id: str):
        sandbox = self._sandboxes.get(project_id)
        if sandbox:
            archive_project(project_id)
            sandbox.cleanup()
            del self._sandboxes[project_id]
