from __future__ import annotations

import json
import os
import threading
import time
import uuid
from typing import Any, Dict, List

try:
    from shared.config import RUNTIME_BASE_DIR
except Exception:
    RUNTIME_BASE_DIR = os.getcwd()

_EVENT_LOCK = threading.Lock()
_EVENT_DIR = os.path.join(RUNTIME_BASE_DIR, "logs")
_EVENT_PATH = os.path.join(_EVENT_DIR, "client_notification_events.json")
_LOG_PATH = os.path.join(_EVENT_DIR, "client_notification_logs.json")
_MAX_EVENTS = 300
_MAX_LOGS = 1000


def _now_text() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _read_events() -> List[Dict[str, Any]]:
    try:
        if os.path.exists(_EVENT_PATH):
            with open(_EVENT_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return [x for x in data if isinstance(x, dict)]
    except Exception:
        pass
    return []


def _write_events(events: List[Dict[str, Any]]) -> None:
    os.makedirs(_EVENT_DIR, exist_ok=True)
    tmp = _EVENT_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(events[-_MAX_EVENTS:], f, ensure_ascii=False, indent=2)
    os.replace(tmp, _EVENT_PATH)



def _read_logs() -> List[Dict[str, Any]]:
    try:
        if os.path.exists(_LOG_PATH):
            with open(_LOG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return [x for x in data if isinstance(x, dict)]
    except Exception:
        pass
    return []


def _write_logs(logs: List[Dict[str, Any]]) -> None:
    os.makedirs(_EVENT_DIR, exist_ok=True)
    tmp = _LOG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(logs[-_MAX_LOGS:], f, ensure_ascii=False, indent=2)
    os.replace(tmp, _LOG_PATH)


def append_notification_log(event: Dict[str, Any], source: str = "server", displayed: bool = False, client: str = "") -> Dict[str, Any]:
    """알림 로그 목록 화면용 서버 저장 로그를 누적한다.

    action event는 생성 즉시 기록하고, 클라이언트 에이전트가 실제로 표시한 알림은
    POST 로그로 한 번 더 갱신한다. 같은 event key/signature 조합은 중복 추가하지 않고
    displayed/client/last_seen_at 값만 갱신한다.
    """
    if not isinstance(event, dict):
        event = {}
    key = str(event.get("key") or "").strip()
    sig = str(event.get("signature") or "").strip()
    title = str(event.get("title") or "DevERP 알림").strip()[:120]
    message = str(event.get("message") or "").strip()[:4000]
    kind = str(event.get("kind") or "notification").strip()
    changed_at = str(event.get("changed_at") or event.get("sort_at") or _now_text()).strip()
    if not message:
        return {}
    log_id = f"{key}|{sig}" if key or sig else f"manual|{int(time.time() * 1000)}|{uuid.uuid4().hex[:8]}"
    now = _now_text()
    row = {
        "id": log_id,
        "key": key,
        "signature": sig,
        "kind": kind,
        "title": title,
        "message": message,
        "changed_at": changed_at,
        "logged_at": now,
        "last_seen_at": now,
        "source": str(source or "server"),
        "displayed": bool(displayed),
        "client": str(client or "")[:200],
    }
    with _EVENT_LOCK:
        logs = _read_logs()
        for i, old in enumerate(logs):
            if str(old.get("id") or "") == log_id:
                merged = dict(old)
                merged.update({
                    "title": title,
                    "message": message,
                    "kind": kind,
                    "changed_at": changed_at,
                    "last_seen_at": now,
                    "source": str(source or old.get("source") or "server"),
                    "displayed": bool(displayed) or bool(old.get("displayed")),
                    "client": str(client or old.get("client") or "")[:200],
                })
                logs[i] = merged
                _write_logs(logs)
                return merged
        logs.append(row)
        _write_logs(logs)
    return row


def recent_notification_logs(limit: int = 300) -> List[Dict[str, Any]]:
    limit = max(1, min(int(limit or 300), _MAX_LOGS))
    with _EVENT_LOCK:
        logs = _read_logs()
    return logs[-limit:]


def append_notification_event(kind: str, title: str, message: str, entity_key: str = "", changed_at: str | None = None) -> Dict[str, Any]:
    """클라이언트 에이전트 폴링용 이벤트를 파일 로그에 추가한다.

    DB 상태값이 이미 같은 값인 품목을 다시 QR 처리하거나, 버튼 클릭 자체를 알림으로 남겨야 하는 경우
    상태 diff만으로는 감지하기 어렵다. 이 함수는 사용자 액션 1회당 고유 이벤트를 남긴다.
    """
    ts = changed_at or _now_text()
    event_id = f"{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}"
    ev = {
        "key": f"action:{kind}:{entity_key}:{event_id}",
        "signature": event_id,
        "kind": str(kind or "action"),
        "title": str(title or "DevERP 알림")[:80],
        "message": str(message or "").strip()[:1200],
        "changed_at": ts,
        "sort_at": ts,
        "notify_on_new": True,
    }
    if not ev["message"]:
        return ev
    with _EVENT_LOCK:
        events = _read_events()
        events.append(ev)
        _write_events(events)
    try:
        append_notification_log(ev, source="server-action", displayed=False)
    except Exception:
        pass
    return ev


def recent_notification_events(limit: int = 200) -> List[Dict[str, Any]]:
    limit = max(1, min(int(limit or 200), _MAX_EVENTS))
    with _EVENT_LOCK:
        events = _read_events()
    return events[-limit:]
