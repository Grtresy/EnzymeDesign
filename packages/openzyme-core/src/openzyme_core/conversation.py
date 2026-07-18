from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from .repositories import CoreRepositories
from .repositories import EngineDocumentRecord


def _new_message_document_id() -> str:
    return f"msgdoc_{uuid4().hex[:12]}"


@dataclass(frozen=True, slots=True)
class ConversationEntry:
    message_id: str
    role: str
    content: str
    created_at: str
    sender: str
    recipient: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "role": self.role,
            "content": self.content,
            "created_at": self.created_at,
            "sender": self.sender,
            "recipient": self.recipient,
        }


def persist_conversation_message(
    repositories: CoreRepositories,
    *,
    session_id: str,
    message_id: str,
    role: str,
    content: str,
    created_at: str,
    skill_keys: tuple[str, ...] | None = None,
) -> str:
    document_id = _new_message_document_id()
    repositories.engine_documents.save(
        EngineDocumentRecord(
            document_id=document_id,
            session_id=session_id,
            invocation_id=None,
            document_kind="conversation_message",
            payload={
                "message_id": message_id,
                "role": role,
                "content": content,
                **({} if skill_keys is None else {"skill_keys": list(skill_keys)}),
            },
            created_at=created_at,
            updated_at=created_at,
        )
    )
    return document_id


def build_conversation_projection(repositories: CoreRepositories, session_id: str) -> tuple[ConversationEntry, ...]:
    entries: list[ConversationEntry] = []
    for message in repositories.inbox.list_by_session(session_id):
        if message.message_type not in {"user_message", "assistant_message"}:
            continue
        if message.payload_ref is None:
            continue
        document = repositories.engine_documents.get(message.payload_ref)
        if document is None:
            continue
        content = str(document.payload.get("content") or "")
        role = str(document.payload.get("role") or ("user" if message.message_type == "user_message" else "assistant"))
        entries.append(
            ConversationEntry(
                message_id=message.message_id,
                role=role,
                content=content,
                created_at=message.created_at,
                sender=message.sender,
                recipient=message.recipient,
            )
        )
    return tuple(entries)


def load_recent_conversation(
    repositories: CoreRepositories,
    session_id: str,
    *,
    limit: int = 12,
    after_created_at: str | None = None,
) -> tuple[ConversationEntry, ...]:
    conversation = build_conversation_projection(repositories, session_id)
    if after_created_at is not None:
        conversation = tuple(
            entry for entry in conversation if entry.created_at > after_created_at
        )
    if limit <= 0:
        return ()
    return conversation[-limit:]


__all__ = [
    "ConversationEntry",
    "build_conversation_projection",
    "load_recent_conversation",
    "persist_conversation_message",
]
