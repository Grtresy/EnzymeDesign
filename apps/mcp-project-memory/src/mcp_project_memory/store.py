from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
from typing import Any
from urllib.parse import urlparse
import uuid

from .config import ProjectMemoryConfig
from .models import CandidateSummaryRecord
from .models import DecisionRecord
from .models import EpisodeRecord
from .models import ExperimentResultRecord
from .models import ProjectRecord
from .models import RunManifestRecord
from .models import utc_now_iso

_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_RESERVED_IDS = {".", ".."}


class ProjectMemoryStore:
    def __init__(self, config: ProjectMemoryConfig) -> None:
        self.config = config

    def project_record(self, project_id: str) -> ProjectRecord:
        root = self.resolve_project_root(project_id)
        return ProjectRecord(project_id=project_id, root=str(root))

    def resolve_project_root(self, project_id: str) -> Path:
        self._validate_id(project_id, "project_id")
        root = self.config.resolve_project_root(project_id).resolve()
        return root

    def ensure_project_root(self, project_id: str) -> Path:
        root = self.resolve_project_root(project_id)
        root.mkdir(parents=True, exist_ok=True)
        (root / "episodes").mkdir(exist_ok=True)
        (root / ".enzyme" / "indexes").mkdir(parents=True, exist_ok=True)
        return root

    def ensure_episode_dir(self, project_id: str, episode_id: str) -> Path:
        self._validate_id(episode_id, "episode_id")
        root = self.ensure_project_root(project_id)
        episode_dir = root / "episodes" / episode_id
        episode_dir.mkdir(parents=True, exist_ok=True)
        (episode_dir / "runs").mkdir(exist_ok=True)
        (episode_dir / "artifacts").mkdir(exist_ok=True)
        return episode_dir

    def list_project_ids(self) -> list[str]:
        project_ids = set(self.config.projects)
        if self.config.projects_root and self.config.projects_root.exists():
            for child in self.config.projects_root.iterdir():
                if child.is_dir() and _ID_RE.match(child.name):
                    project_ids.add(child.name)
        return sorted(project_ids)

    def list_episode_records(self, project_id: str) -> list[EpisodeRecord]:
        root = self.resolve_project_root(project_id)
        episodes_dir = root / "episodes"
        if not episodes_dir.exists():
            return []
        records: list[EpisodeRecord] = []
        for child in sorted(episodes_dir.iterdir()):
            if not child.is_dir() or not _ID_RE.match(child.name):
                continue
            archived = False
            manifest_path = child / "manifest.json"
            if manifest_path.exists():
                manifest = self._read_json(manifest_path)
                archived = bool(manifest.get("archived"))
            records.append(
                EpisodeRecord(project_id=project_id, episode_id=child.name, archived=archived)
            )
        return records

    def list_resource_descriptors(self) -> list[dict[str, str]]:
        descriptors: list[dict[str, str]] = []
        for project_id in self.list_project_ids():
            try:
                descriptors.extend(self._project_resource_descriptors(project_id))
            except KeyError:
                continue
        return descriptors

    def read_resource_text(self, uri: str) -> str:
        target = self.parse_uri(uri)
        kind = target["kind"]
        if kind == "project_config":
            return self._read_text(self.resolve_project_root(target["project_id"]) / "enzyme.yaml")
        if kind == "episodes":
            payload = {
                "project": self.project_record(target["project_id"]).to_dict(),
                "episodes": [record.to_dict() for record in self.list_episode_records(target["project_id"])],
            }
            return self._dump_json(payload)
        if kind == "episode_goal":
            return self._read_text(self._episode_file(target["project_id"], target["episode_id"], "goal.md"))
        if kind == "episode_state":
            return self._dump_json(self._read_json(self._episode_file(target["project_id"], target["episode_id"], "state.json")))
        if kind == "episode_plan":
            return self._read_text(self._episode_file(target["project_id"], target["episode_id"], "plan.yaml"))
        if kind == "episode_annotations":
            return self._dump_json(self._read_json(self._episode_file(target["project_id"], target["episode_id"], "annotations.json")))
        if kind == "run_manifest":
            return self._dump_json(self._read_json(self._resolve_indexed_file("runs", target["run_id"])))
        if kind == "candidate_summary":
            return self._dump_json(self._read_json(self._resolve_indexed_file("candidates", target["candidate_id"])))
        if kind == "experiment_result":
            return self._dump_json(self._read_json(self._resolve_indexed_file("experiments", target["experiment_id"])))
        raise ValueError(f"Unsupported resource URI: {uri}")

    def update_episode_state(
        self, project_id: str, episode_id: str, state: dict[str, Any]
    ) -> dict[str, Any]:
        episode_dir = self.ensure_episode_dir(project_id, episode_id)
        existing_meta = state.get("_meta")
        meta = dict(existing_meta) if isinstance(existing_meta, dict) else {}
        payload = {
            **state,
            "_meta": {
                **meta,
                "updated_at": utc_now_iso(),
            },
        }
        self._write_json_atomic(episode_dir / "state.json", payload)
        return payload

    def save_episode_goal(
        self, project_id: str, episode_id: str, goal_markdown: str
    ) -> dict[str, Any]:
        episode_dir = self.ensure_episode_dir(project_id, episode_id)
        payload = goal_markdown
        if not payload.endswith("\n"):
            payload += "\n"
        self._write_text_atomic(episode_dir / "goal.md", payload)
        return {
            "project_id": project_id,
            "episode_id": episode_id,
            "path": self._relative_to_project_root(project_id, episode_dir / "goal.md"),
        }

    def record_decision(
        self,
        project_id: str,
        episode_id: str,
        decision_type: str,
        reason: str,
        author: str,
        evidence_refs: list[str] | None = None,
    ) -> dict[str, Any]:
        episode_dir = self.ensure_episode_dir(project_id, episode_id)
        decision = DecisionRecord(
            decision_id=self._new_object_id("decision"),
            project_id=project_id,
            episode_id=episode_id,
            type=decision_type,
            reason=reason,
            author=author,
            evidence_refs=list(evidence_refs or []),
            timestamp=utc_now_iso(),
        )
        self._append_jsonl(episode_dir / "decision_log.jsonl", decision.to_dict())
        return decision.to_dict()

    def confirm_plan(
        self, project_id: str, episode_id: str, plan: dict[str, Any]
    ) -> dict[str, Any]:
        episode_dir = self.ensure_episode_dir(project_id, episode_id)
        existing_meta = plan.get("_meta")
        meta = dict(existing_meta) if isinstance(existing_meta, dict) else {}
        payload = {
            **plan,
            "_meta": {
                **meta,
                "confirmed_at": utc_now_iso(),
            },
        }
        self._write_text_atomic(episode_dir / "plan.yaml", self._dump_json(payload))
        return payload

    def save_structure_annotations(
        self, project_id: str, episode_id: str, annotations: dict[str, Any]
    ) -> dict[str, Any]:
        episode_dir = self.ensure_episode_dir(project_id, episode_id)
        existing_meta = annotations.get("_meta")
        meta = dict(existing_meta) if isinstance(existing_meta, dict) else {}
        payload = {
            **annotations,
            "_meta": {
                **meta,
                "saved_at": utc_now_iso(),
            },
        }
        self._write_json_atomic(episode_dir / "annotations.json", payload)
        return payload

    def import_experiment_results(
        self,
        project_id: str,
        episode_id: str,
        result: dict[str, Any],
        experiment_id: str | None = None,
        candidate_ids: list[str] | None = None,
        run_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        episode_dir = self.ensure_episode_dir(project_id, episode_id)
        experiment_id = experiment_id or self._new_object_id("experiment")
        self._validate_id(experiment_id, "experiment_id")
        self._ensure_object_id_available("experiments", experiment_id, project_id)
        candidate_ids = list(candidate_ids or [])
        run_ids = list(run_ids or [])
        for candidate_id in candidate_ids:
            self._validate_id(candidate_id, "candidate_id")
        for run_id in run_ids:
            self._validate_id(run_id, "run_id")
        payload = {
            **result,
            "experiment_id": experiment_id,
            "project_id": project_id,
            "episode_id": episode_id,
            "candidate_ids": candidate_ids,
            "run_ids": run_ids,
            "imported_at": utc_now_iso(),
        }
        result_path = (
            episode_dir / "artifacts" / "experiments" / experiment_id / "result.json"
        )
        result_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_json_atomic(result_path, payload)
        record = ExperimentResultRecord(
            experiment_id=experiment_id,
            project_id=project_id,
            episode_id=episode_id,
            path=self._relative_to_project_root(project_id, result_path),
            candidate_ids=candidate_ids,
            run_ids=run_ids,
            imported_at=payload["imported_at"],
        )
        self._update_index("experiments", experiment_id, record.to_dict(), project_id)
        return payload

    def archive_episode(self, project_id: str, episode_id: str) -> dict[str, Any]:
        episode_dir = self.ensure_episode_dir(project_id, episode_id)
        manifest = {
            "project_id": project_id,
            "episode_id": episode_id,
            "archived": True,
            "archived_at": utc_now_iso(),
            "goal": self._path_ref(project_id, episode_dir / "goal.md"),
            "state": self._path_ref(project_id, episode_dir / "state.json"),
            "plan": self._path_ref(project_id, episode_dir / "plan.yaml"),
            "annotations": self._path_ref(project_id, episode_dir / "annotations.json"),
            "decision_log": {
                "path": self._relative_to_project_root(project_id, episode_dir / "decision_log.jsonl"),
                "count": len(self.read_decision_log(project_id, episode_id)),
            },
            "run_refs": self._collect_index_refs("runs", project_id, episode_id),
            "candidate_refs": self._collect_index_refs("candidates", project_id, episode_id),
            "experiment_refs": self._collect_index_refs("experiments", project_id, episode_id),
        }
        self._write_json_atomic(episode_dir / "manifest.json", manifest)
        return manifest

    def write_run_manifest(
        self, project_id: str, episode_id: str, run_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        self._validate_id(run_id, "run_id")
        self._ensure_object_id_available("runs", run_id, project_id)
        episode_dir = self.ensure_episode_dir(project_id, episode_id)
        manifest_path = episode_dir / "runs" / run_id / "manifest.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        body = {
            **payload,
            "run_id": run_id,
            "project_id": project_id,
            "episode_id": episode_id,
        }
        self._write_json_atomic(manifest_path, body)
        record = RunManifestRecord(
            run_id=run_id,
            project_id=project_id,
            episode_id=episode_id,
            path=self._relative_to_project_root(project_id, manifest_path),
            tool=payload.get("tool"),
            status=payload.get("status"),
        )
        self._update_index("runs", run_id, record.to_dict(), project_id)
        return body

    def write_candidate_summary(
        self, project_id: str, episode_id: str, candidate_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        self._validate_id(candidate_id, "candidate_id")
        self._ensure_object_id_available("candidates", candidate_id, project_id)
        episode_dir = self.ensure_episode_dir(project_id, episode_id)
        summary_path = (
            episode_dir / "artifacts" / "candidates" / candidate_id / "summary.json"
        )
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        body = {
            **payload,
            "candidate_id": candidate_id,
            "project_id": project_id,
            "episode_id": episode_id,
        }
        self._write_json_atomic(summary_path, body)
        record = CandidateSummaryRecord(
            candidate_id=candidate_id,
            project_id=project_id,
            episode_id=episode_id,
            path=self._relative_to_project_root(project_id, summary_path),
            status=payload.get("status"),
        )
        self._update_index("candidates", candidate_id, record.to_dict(), project_id)
        return body

    def read_decision_log(self, project_id: str, episode_id: str) -> list[dict[str, Any]]:
        path = self._episode_file(project_id, episode_id, "decision_log.jsonl")
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def parse_uri(self, uri: str) -> dict[str, str]:
        parsed = urlparse(uri)
        if parsed.scheme != "enzyme":
            raise ValueError(f"Unsupported resource URI: {uri}")

        raw_parts = [parsed.netloc, *[part for part in parsed.path.split("/") if part]]
        if any(part in {"..", "."} for part in raw_parts):
            raise ValueError(f"Unsupported resource URI: {uri}")

        if parsed.netloc == "project" and len(raw_parts) == 3 and raw_parts[2] == "config":
            return {"kind": "project_config", "project_id": raw_parts[1]}
        if parsed.netloc == "project" and len(raw_parts) == 3 and raw_parts[2] == "episodes":
            return {"kind": "episodes", "project_id": raw_parts[1]}
        if parsed.netloc == "project" and len(raw_parts) == 5 and raw_parts[2] == "episode":
            project_id = raw_parts[1]
            episode_id = raw_parts[3]
            leaf = raw_parts[4]
            mapping = {
                "goal": "episode_goal",
                "state": "episode_state",
                "plan": "episode_plan",
                "annotations": "episode_annotations",
            }
            if leaf in mapping:
                return {
                    "kind": mapping[leaf],
                    "project_id": project_id,
                    "episode_id": episode_id,
                }
        if parsed.netloc == "run" and len(raw_parts) == 3 and raw_parts[2] == "manifest":
            return {"kind": "run_manifest", "run_id": raw_parts[1]}
        if parsed.netloc == "candidate" and len(raw_parts) == 3 and raw_parts[2] == "summary":
            return {"kind": "candidate_summary", "candidate_id": raw_parts[1]}
        if parsed.netloc == "experiment" and len(raw_parts) == 3 and raw_parts[2] == "result":
            return {"kind": "experiment_result", "experiment_id": raw_parts[1]}
        raise ValueError(f"Unsupported resource URI: {uri}")

    def _project_resource_descriptors(self, project_id: str) -> list[dict[str, str]]:
        root = self.resolve_project_root(project_id)
        descriptors: list[dict[str, str]] = []
        if root.exists():
            descriptors.append(
                {
                    "uri": f"enzyme://project/{project_id}/episodes",
                    "name": f"{project_id}-episodes",
                    "mime_type": "application/json",
                }
            )
        config_path = root / "enzyme.yaml"
        if config_path.exists():
            descriptors.append(
                {
                    "uri": f"enzyme://project/{project_id}/config",
                    "name": f"{project_id}-config",
                    "mime_type": "text/plain",
                }
            )
        for record in self.list_episode_records(project_id):
            episode_id = record.episode_id
            descriptors.extend(
                [
                    {
                        "uri": f"enzyme://project/{project_id}/episode/{episode_id}/goal",
                        "name": f"{project_id}-{episode_id}-goal",
                        "mime_type": "text/markdown",
                    },
                    {
                        "uri": f"enzyme://project/{project_id}/episode/{episode_id}/state",
                        "name": f"{project_id}-{episode_id}-state",
                        "mime_type": "application/json",
                    },
                    {
                        "uri": f"enzyme://project/{project_id}/episode/{episode_id}/plan",
                        "name": f"{project_id}-{episode_id}-plan",
                        "mime_type": "application/yaml",
                    },
                    {
                        "uri": f"enzyme://project/{project_id}/episode/{episode_id}/annotations",
                        "name": f"{project_id}-{episode_id}-annotations",
                        "mime_type": "application/json",
                    },
                ]
            )
        descriptors.extend(self._indexed_resource_descriptors(project_id, "runs", "run", "manifest"))
        descriptors.extend(self._indexed_resource_descriptors(project_id, "candidates", "candidate", "summary"))
        descriptors.extend(self._indexed_resource_descriptors(project_id, "experiments", "experiment", "result"))
        return [item for item in descriptors if self._resource_exists(item["uri"])]

    def _resource_exists(self, uri: str) -> bool:
        try:
            self.read_resource_text(uri)
        except (FileNotFoundError, KeyError, ValueError):
            return False
        return True

    def _indexed_resource_descriptors(
        self, project_id: str, index_name: str, prefix: str, suffix: str
    ) -> list[dict[str, str]]:
        result: list[dict[str, str]] = []
        index = self._load_index(index_name, project_id)
        for object_id, payload in index.items():
            result.append(
                {
                    "uri": f"enzyme://{prefix}/{object_id}/{suffix}",
                    "name": f"{prefix}-{object_id}",
                    "mime_type": "application/json",
                }
            )
        return result

    def _resolve_indexed_file(self, index_name: str, object_id: str) -> Path:
        label = {
            "runs": "run_id",
            "candidates": "candidate_id",
            "experiments": "experiment_id",
        }[index_name]
        self._validate_id(object_id, label)
        matches = self._find_index_matches(index_name, object_id)
        if len(matches) > 1:
            projects = ", ".join(sorted(project_id for project_id, _ in matches))
            raise ValueError(f"Duplicate {label} across projects: {object_id} ({projects})")
        if matches:
            project_id, payload = matches[0]
            root = self.resolve_project_root(project_id)
            path = (root / payload["path"]).resolve()
            self._ensure_within(path, root)
            if not path.exists():
                raise FileNotFoundError(path)
            return path
        raise FileNotFoundError(f"{index_name} entry not found: {object_id}")

    def _collect_index_refs(
        self, index_name: str, project_id: str, episode_id: str
    ) -> list[dict[str, Any]]:
        refs: list[dict[str, Any]] = []
        for object_id, payload in self._load_index(index_name, project_id).items():
            if payload.get("episode_id") != episode_id:
                continue
            refs.append(
                {
                    f"{index_name[:-1]}_id": object_id,
                    "path": payload["path"],
                }
            )
        return sorted(refs, key=lambda item: next(iter(item.values())))

    def _update_index(
        self, index_name: str, object_id: str, payload: dict[str, Any], project_id: str
    ) -> None:
        index_path = self._index_path(project_id, index_name, create=True)
        with self._file_lock(index_path):
            index = self._read_json(index_path) if index_path.exists() else {}
            index[object_id] = payload
            self._write_json_atomic(index_path, index)

    def _load_index(self, index_name: str, project_id: str) -> dict[str, Any]:
        index_path = self._index_path(project_id, index_name)
        if not index_path.exists():
            return {}
        return self._read_json(index_path)

    def _index_path(self, project_id: str, index_name: str, create: bool = False) -> Path:
        root = self.ensure_project_root(project_id) if create else self.resolve_project_root(project_id)
        return root / ".enzyme" / "indexes" / f"{index_name}.json"

    def _episode_file(self, project_id: str, episode_id: str, filename: str) -> Path:
        episode_dir = self._resolve_episode_dir(project_id, episode_id)
        path = (episode_dir / filename).resolve()
        self._ensure_within(path, self.resolve_project_root(project_id))
        return path

    def _resolve_episode_dir(self, project_id: str, episode_id: str) -> Path:
        self._validate_id(episode_id, "episode_id")
        root = self.resolve_project_root(project_id)
        episode_dir = (root / "episodes" / episode_id).resolve()
        self._ensure_within(episode_dir, root)
        return episode_dir

    def _path_ref(self, project_id: str, path: Path) -> dict[str, Any]:
        return {
            "path": self._relative_to_project_root(project_id, path),
            "exists": path.exists(),
        }

    def _relative_to_project_root(self, project_id: str, path: Path) -> str:
        return os.fspath(path.resolve().relative_to(self.resolve_project_root(project_id)))

    def _read_text(self, path: Path) -> str:
        if not path.exists():
            raise FileNotFoundError(path)
        return path.read_text(encoding="utf-8")

    def _read_json(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            raise FileNotFoundError(path)
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_json_atomic(self, path: Path, payload: dict[str, Any]) -> None:
        self._write_text_atomic(path, self._dump_json(payload) + "\n")

    def _write_text_atomic(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
            temp_path = Path(handle.name)
        temp_path.replace(path)
        directory_fd = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    def _append_jsonl(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._file_lock(path):
            with path.open("a", encoding="utf-8") as handle:
                handle.write(self._dump_json_line(payload) + "\n")
                handle.flush()
                os.fsync(handle.fileno())

    def _dump_json(self, payload: Any) -> str:
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def _dump_json_line(self, payload: Any) -> str:
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    def _new_object_id(self, prefix: str) -> str:
        return f"{prefix}-{uuid.uuid4().hex}"

    def _ensure_within(self, path: Path, root: Path) -> None:
        root = root.resolve()
        path = path.resolve()
        if root not in path.parents and path != root:
            raise ValueError(f"Path escapes project root: {path}")

    def _validate_id(self, value: str, label: str) -> None:
        if value != value.strip() or value in _RESERVED_IDS or not _ID_RE.match(value):
            raise ValueError(f"Invalid {label}: {value}")

    def _ensure_object_id_available(
        self, index_name: str, object_id: str, project_id: str
    ) -> None:
        matches = self._find_index_matches(index_name, object_id)
        for existing_project_id, _ in matches:
            if existing_project_id != project_id:
                singular = {
                    "runs": "run_id",
                    "candidates": "candidate_id",
                    "experiments": "experiment_id",
                }[index_name]
                raise ValueError(
                    f"{singular} must be globally unique across projects: {object_id}"
                )

    def _find_index_matches(
        self, index_name: str, object_id: str
    ) -> list[tuple[str, dict[str, Any]]]:
        matches: list[tuple[str, dict[str, Any]]] = []
        for project_id in self.list_project_ids():
            index = self._load_index(index_name, project_id)
            payload = index.get(object_id)
            if payload is not None:
                matches.append((project_id, payload))
        return matches

    def _lock_path(self, path: Path) -> Path:
        return path.with_name(f"{path.name}.lock")

    @contextmanager
    def _file_lock(self, path: Path):
        lock_path = self._lock_path(path)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = lock_path.open("w", encoding="utf-8")
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()
