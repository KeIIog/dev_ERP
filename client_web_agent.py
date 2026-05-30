# client_web_agent.py
# DevERP 웹 접속 PC에서 Bizbox Selenium 자동화를 실행하기 위한 로컬 에이전트
# v10: 표준 라이브러리 로컬 에이전트. 웹 자동 설치 패키지/Run registry 실행 안정화

from __future__ import annotations

import json
import os
import re
import sys
import time
import tempfile
import traceback
import platform
import threading
import subprocess
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

APP_VERSION = "client-agent-20260529-v42-black-log-click-notifications"
AGENT_HOST = os.getenv("DEVERP_CLIENT_AGENT_HOST", "127.0.0.1")
AGENT_PORT = int(os.getenv("DEVERP_CLIENT_AGENT_PORT", "8765"))
DOWNLOAD_ROOT = Path(tempfile.gettempdir()) / "deverp_client_agent"
LOG_DIR = ROOT_DIR / "logs"
DOWNLOAD_ROOT.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)
STARTED_AT = time.strftime("%Y-%m-%d %H:%M:%S")
SETTINGS_PATH = ROOT_DIR / "client_agent_settings.json"
NOTIFICATION_STATE_PATH = LOG_DIR / "notification_state.json"
NOTIFICATION_DEFAULT_INTERVAL = int(os.getenv("DEVERP_AGENT_NOTIFY_INTERVAL", "10") or "10")
_notification_worker_started = False
_notification_worker_lock = threading.Lock()


def _agent_health_payload() -> Dict[str, Any]:
    """브라우저가 로컬 프로세스 실행 여부를 확인할 때 쓰는 상태값."""
    exe = str(Path(sys.executable).resolve())
    script = str(Path(__file__).resolve())
    return {
        "status": "ok",
        "success": True,
        "version": APP_VERSION,
        "pid": os.getpid(),
        "process_name": Path(exe).name,
        "executable": exe,
        "script": script,
        "root": str(ROOT_DIR),
        "frozen": bool(getattr(sys, "frozen", False)),
        "started_at": STARTED_AT,
        "host": AGENT_HOST,
        "port": AGENT_PORT,
        "platform": platform.platform(),
        "notifications": _notification_status_payload(),
    }


def _log(message: str) -> None:
    try:
        with (LOG_DIR / "client_agent.log").open("a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S") + " " + str(message) + "\n")
    except Exception:
        pass


def _log_exception(prefix: str = "ERROR") -> str:
    tb = traceback.format_exc()
    try:
        with (LOG_DIR / "client_agent_error.log").open("a", encoding="utf-8") as f:
            f.write("\n" + "=" * 80 + "\n")
            f.write(time.strftime("%Y-%m-%d %H:%M:%S") + f" {prefix}\n")
            f.write(tb)
            f.write("\n")
    except Exception:
        pass
    return tb


def _load_json_file(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def _write_json_file(path: Path, data: Any) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        _log_exception(f"write json failed: {path}")


def _load_agent_settings() -> Dict[str, Any]:
    data = _load_json_file(SETTINGS_PATH, {})
    if not isinstance(data, dict):
        data = {}
    env_base = (os.getenv("DEVERP_SERVER_BASE") or "").strip().rstrip("/")
    if env_base:
        data["server_base"] = env_base
    return data


def _save_agent_settings(**kwargs: Any) -> None:
    data = _load_agent_settings()
    changed = False
    for k, v in kwargs.items():
        if v is None:
            continue
        if isinstance(v, str):
            v = v.strip()
        if v != "" and data.get(k) != v:
            data[k] = v
            changed = True
    if changed:
        data["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _write_json_file(SETTINGS_PATH, data)


def _notification_status_payload() -> Dict[str, Any]:
    settings = _load_agent_settings()
    state = _load_json_file(NOTIFICATION_STATE_PATH, {})
    return {
        "enabled": True,
        "server_base": settings.get("server_base") or settings.get("server_base_fallback") or "",
        "poll_interval_seconds": int(settings.get("poll_interval_seconds") or NOTIFICATION_DEFAULT_INTERVAL),
        "initialized": bool(isinstance(state, dict) and state.get("initialized")),
        "last_poll_at": state.get("last_poll_at", "") if isinstance(state, dict) else "",
        "last_error": state.get("last_error", "") if isinstance(state, dict) else "",
        "state_path": str(NOTIFICATION_STATE_PATH),
        "settings_path": str(SETTINGS_PATH),
    }


def _powershell_quote(value: str) -> str:
    return "'" + str(value or "").replace("'", "''") + "'"


def _show_desktop_notification(title: str, message: str, duration_ms: int = 15000, click_url: str = "") -> None:
    """Windows 우측 하단에 검은 배경 알림을 띄우고, 클릭 시 서버 알림 로그 화면을 연다."""
    title = str(title or "DevERP 알림").strip()[:100]
    message = str(message or "").strip()[:3000]
    click_url = str(click_url or "").strip()
    if not message:
        return
    if os.name != "nt":
        _log(f"notification(non-windows): {title} - {message}")
        return
    try:
        ps_lines = [
            "Add-Type -AssemblyName PresentationFramework",
            "Add-Type -AssemblyName PresentationCore",
            "Add-Type -AssemblyName WindowsBase",
            "$title = " + _powershell_quote(title),
            "$msg = " + _powershell_quote(message),
            "$clickUrl = " + _powershell_quote(click_url),
            "$duration = " + str(int(duration_ms)),
            "$screen = [System.Windows.SystemParameters]::WorkArea",
            "$width = [Math]::Min(760, [Math]::Max(560, [int]($screen.Width * 0.42)))",
            "$height = [Math]::Min(520, [Math]::Max(300, [int]($screen.Height * 0.36)))",
            "$window = New-Object System.Windows.Window",
            "$window.Title = $title",
            "$window.WindowStyle = [System.Windows.WindowStyle]::None",
            "$window.ResizeMode = [System.Windows.ResizeMode]::NoResize",
            "$window.ShowInTaskbar = $false",
            "$window.Topmost = $true",
            "$window.Width = $width",
            "$window.Height = $height",
            "$window.Left = $screen.Right - $width - 18",
            "$window.Top = $screen.Bottom - $height - 18",
            "$window.Background = [System.Windows.Media.Brushes]::Black",
            "$window.Foreground = [System.Windows.Media.Brushes]::White",
            "$window.Cursor = [System.Windows.Input.Cursors]::Hand",
            "$border = New-Object System.Windows.Controls.Border",
            "$border.Background = [System.Windows.Media.Brushes]::Black",
            "$borderBrush = New-Object System.Windows.Media.SolidColorBrush -ArgumentList ([System.Windows.Media.Color]::FromRgb(80,80,80))",
            "$border.BorderBrush = $borderBrush",
            "$border.BorderThickness = New-Object System.Windows.Thickness -ArgumentList 1",
            "$border.Padding = New-Object System.Windows.Thickness -ArgumentList 16,14,16,12",
            "$grid = New-Object System.Windows.Controls.Grid",
            "$row0 = New-Object System.Windows.Controls.RowDefinition; $row0.Height = [System.Windows.GridLength]::Auto",
            "$row1 = New-Object System.Windows.Controls.RowDefinition; $row1.Height = New-Object System.Windows.GridLength -ArgumentList 1, ([System.Windows.GridUnitType]::Star)",
            "$row2 = New-Object System.Windows.Controls.RowDefinition; $row2.Height = [System.Windows.GridLength]::Auto",
            "$grid.RowDefinitions.Add($row0); $grid.RowDefinitions.Add($row1); $grid.RowDefinitions.Add($row2)",
            "$titleBlock = New-Object System.Windows.Controls.TextBlock",
            "$titleBlock.Text = $title",
            "$titleBlock.FontFamily = 'Malgun Gothic'",
            "$titleBlock.FontSize = 16",
            "$titleBlock.FontWeight = [System.Windows.FontWeights]::Bold",
            "$titleBlock.Foreground = [System.Windows.Media.Brushes]::White",
            "$titleBlock.TextWrapping = [System.Windows.TextWrapping]::Wrap",
            "$titleBlock.Margin = New-Object System.Windows.Thickness -ArgumentList 0,0,0,10",
            "[System.Windows.Controls.Grid]::SetRow($titleBlock, 0)",
            "$grid.Children.Add($titleBlock) | Out-Null",
            "$scroll = New-Object System.Windows.Controls.ScrollViewer",
            "$scroll.VerticalScrollBarVisibility = [System.Windows.Controls.ScrollBarVisibility]::Auto",
            "$scroll.HorizontalScrollBarVisibility = [System.Windows.Controls.ScrollBarVisibility]::Disabled",
            "$msgBlock = New-Object System.Windows.Controls.TextBlock",
            "$msgBlock.Text = $msg",
            "$msgBlock.FontFamily = 'Malgun Gothic'",
            "$msgBlock.FontSize = 14",
            "$msgBlock.LineHeight = 21",
            "$msgBlock.Foreground = [System.Windows.Media.Brushes]::White",
            "$msgBlock.TextWrapping = [System.Windows.TextWrapping]::Wrap",
            "$msgBlock.Padding = New-Object System.Windows.Thickness -ArgumentList 0,0,6,0",
            "$scroll.Content = $msgBlock",
            "[System.Windows.Controls.Grid]::SetRow($scroll, 1)",
            "$grid.Children.Add($scroll) | Out-Null",
            "$hint = New-Object System.Windows.Controls.TextBlock",
            "$hint.Text = if($clickUrl){ '클릭하면 알림 로그를 엽니다' } else { '클릭하면 닫습니다' }",
            "$hint.FontFamily = 'Malgun Gothic'",
            "$hint.FontSize = 12",
            "$hintBrush = New-Object System.Windows.Media.SolidColorBrush -ArgumentList ([System.Windows.Media.Color]::FromRgb(190,190,190))",
            "$hint.Foreground = $hintBrush",
            "$hint.Margin = New-Object System.Windows.Thickness -ArgumentList 0,10,0,0",
            "[System.Windows.Controls.Grid]::SetRow($hint, 2)",
            "$grid.Children.Add($hint) | Out-Null",
            "$border.Child = $grid",
            "$window.Content = $border",
            "$openLog = { if($clickUrl){ try { Start-Process $clickUrl } catch {} }; $window.Close() }",
            "$window.Add_MouseLeftButtonUp($openLog)",
            "$timer = New-Object System.Windows.Threading.DispatcherTimer",
            "$timer.Interval = [TimeSpan]::FromMilliseconds($duration)",
            "$timer.Add_Tick({ $timer.Stop(); $window.Close() })",
            "$timer.Start()",
            "$null = $window.ShowDialog()",
        ]
        ps = "\n".join(ps_lines) + "\n"
        script = DOWNLOAD_ROOT / f"notify_{os.getpid()}_{int(time.time()*1000)}.ps1"
        script.write_text(ps, encoding="utf-8-sig")
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen([
            "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-STA", "-WindowStyle", "Hidden", "-File", str(script)
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=creationflags)
    except Exception:
        _log_exception("desktop notification failed")


def _post_notification_logs(base: str, events: List[Dict[str, Any]], displayed: bool = True) -> None:
    """클라이언트에서 실제 표시한 알림을 서버 로그 파일에도 남긴다."""
    if not events:
        return
    base = str(base or "").strip().rstrip("/")
    if not base:
        return
    try:
        payload = {
            "displayed": bool(displayed),
            "client": f"{platform.node()} / PID {os.getpid()} / {APP_VERSION}",
            "events": events,
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            base + "/api/system/client_agent/notification_logs",
            data=body,
            headers={"Content-Type": "application/json", "User-Agent": f"DevERPClientAgent/{APP_VERSION}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=3) as res:
            res.read(256)
    except Exception as e:
        _log(f"notification log post failed: {e}")

def _event_sort_key(ev: Dict[str, Any]) -> str:
    return str(ev.get("changed_at") or ev.get("sort_at") or "")


def _process_notification_feed(feed: Dict[str, Any], base: str = "") -> None:
    events = feed.get("events") or []
    if not isinstance(events, list):
        events = []
    state = _load_json_file(NOTIFICATION_STATE_PATH, {})
    if not isinstance(state, dict):
        state = {}
    prev = state.get("signatures") if isinstance(state.get("signatures"), dict) else {}
    initialized = bool(state.get("initialized"))
    new_signatures: Dict[str, str] = {}
    changed: List[Dict[str, Any]] = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        key = str(ev.get("key") or "").strip()
        sig = str(ev.get("signature") or "").strip()
        if not key or not sig:
            continue
        new_signatures[key] = sig
        old = prev.get(key)
        if not initialized:
            continue
        if old is None:
            if ev.get("notify_on_new", True):
                changed.append(ev)
        elif old != sig:
            changed.append(ev)

    state.update({
        "initialized": True,
        "last_poll_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "last_error": "",
        "signatures": new_signatures,
    })
    _write_json_file(NOTIFICATION_STATE_PATH, state)

    if not changed:
        return
    log_url = str(feed.get("log_url") or "").strip()
    if not log_url and base:
        log_url = str(base).rstrip("/") + "/api/system/client_agent/notification_log_page"
    # 버튼/모바일 QR 처리 이벤트가 같이 들어온 경우 상태 diff 알림은 중복될 수 있으므로
    # 사용자 액션 이벤트를 우선 표시한다. 액션 로그가 없을 때는 기존 상태 diff 알림을 그대로 사용한다.
    action_changed = [ev for ev in changed if str(ev.get("key") or "").startswith("action:")]
    if action_changed:
        changed = action_changed
    changed = sorted(changed, key=_event_sort_key)[-8:]
    if len(changed) > 3:
        title = "DevERP 변경 알림"
        head = changed[-1]
        message = f"입고/진행상태 변경 {len(changed)}건이 감지되었습니다.\n최근: {head.get('message') or head.get('title') or ''}"
        _post_notification_logs(base, changed, displayed=True)
        _show_desktop_notification(title, message, click_url=log_url)
        return
    _post_notification_logs(base, changed, displayed=True)
    for ev in changed:
        _show_desktop_notification(str(ev.get("title") or "DevERP 변경 알림"), str(ev.get("message") or ""), click_url=log_url)
        time.sleep(0.35)


def _poll_notification_once() -> int:
    settings = _load_agent_settings()
    base = str(settings.get("server_base") or settings.get("server_base_fallback") or "").strip().rstrip("/")
    interval = int(settings.get("poll_interval_seconds") or NOTIFICATION_DEFAULT_INTERVAL)
    interval = max(5, min(interval, 300))
    if not base:
        return interval
    url = base + "/api/system/client_agent/notifications"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": f"DevERPClientAgent/{APP_VERSION}"})
        with urllib.request.urlopen(req, timeout=8) as res:
            data = json.loads(res.read().decode("utf-8"))
        _process_notification_feed(data if isinstance(data, dict) else {}, base=base)
        server_interval = int((data or {}).get("poll_interval_seconds") or interval) if isinstance(data, dict) else interval
        return max(5, min(server_interval, 300))
    except Exception as e:
        state = _load_json_file(NOTIFICATION_STATE_PATH, {})
        if not isinstance(state, dict):
            state = {}
        state["last_poll_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        state["last_error"] = str(e)
        state.setdefault("signatures", {})
        _write_json_file(NOTIFICATION_STATE_PATH, state)
        _log(f"notification poll failed: {e}")
        return min(max(interval * 2, 10), 120)


def _notification_worker() -> None:
    time.sleep(4)
    interval = NOTIFICATION_DEFAULT_INTERVAL
    while True:
        try:
            interval = _poll_notification_once()
        except Exception:
            _log_exception("notification worker failed")
            interval = max(interval, 30)
        time.sleep(interval)


def _start_notification_worker() -> None:
    global _notification_worker_started
    with _notification_worker_lock:
        if _notification_worker_started:
            return
        _notification_worker_started = True
        th = threading.Thread(target=_notification_worker, name="DevERPNotificationPoller", daemon=True)
        th.start()
        _log("notification worker started")


def _safe_filename(name: str, fallback: str = "download.bin") -> str:
    name = (name or fallback).strip().replace("\\", "_").replace("/", "_")
    name = re.sub(r'[<>:"|?*\x00-\x1f]', "_", name)
    return name or fallback


def _content_disposition_filename(cd: str) -> str:
    cd = cd or ""
    m = re.search(r"filename\*=UTF-8''([^;]+)", cd, re.I)
    if m:
        return urllib.parse.unquote(m.group(1))
    m = re.search(r'filename="?([^";]+)"?', cd, re.I)
    if m:
        return m.group(1)
    return ""


def _absolute_url(url: str, server_base: str) -> str:
    url = str(url or "").strip()
    if url.startswith("http://") or url.startswith("https://"):
        return url
    base = (server_base or "").strip().rstrip("/")
    if not base:
        raise ValueError(f"상대경로 URL을 절대 URL로 바꿀 서버 주소가 없습니다: {url}")
    if not url.startswith("/"):
        url = "/" + url
    return base + url


def _download_files(items: List[Any], server_base: str, token: str = "") -> List[str]:
    """서버가 넘긴 attachment_urls를 현재 PC 임시 폴더로 다운로드한다. requests 미사용."""
    if not items:
        return []
    work = DOWNLOAD_ROOT / time.strftime("%Y%m%d_%H%M%S")
    work.mkdir(parents=True, exist_ok=True)

    local_paths: List[str] = []
    for idx, item in enumerate(items):
        if isinstance(item, str):
            raw_url = item
            filename_hint = ""
        else:
            raw_url = item.get("absolute_url") or item.get("download_url") or item.get("url") or ""
            filename_hint = item.get("filename") or ""
        if not raw_url:
            continue
        url = _absolute_url(raw_url, server_base)
        req = urllib.request.Request(url)
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(req, timeout=60) as res:
            content = res.read()
            headers = res.headers
        filename = (
            _content_disposition_filename(headers.get("content-disposition", ""))
            or filename_hint
            or Path(urllib.parse.urlparse(url).path).name
            or f"file_{idx + 1}.bin"
        )
        filename = _safe_filename(filename, f"file_{idx + 1}.bin")
        out = work / filename
        if out.exists():
            stem, suffix = out.stem, out.suffix
            n = 2
            while out.exists():
                out = work / f"{stem}_{n}{suffix}"
                n += 1
        out.write_bytes(content)
        local_paths.append(str(out))
    return local_paths


def _purchase_request(payload: Dict[str, Any]) -> Dict[str, Any]:
    biz_id = str(payload.get("bizbox_id") or "").strip()
    biz_pw = str(payload.get("bizbox_pw") or "")
    if not biz_id or not biz_pw:
        return {"success": False, "message": "Bizbox 아이디/비밀번호가 없습니다."}

    request_data = dict(payload.get("request_data") or {})
    server_base = str(payload.get("server_base") or "").rstrip("/")
    token = str(payload.get("token") or "")
    attachment_urls = payload.get("attachment_urls") or []
    if server_base:
        _save_agent_settings(server_base=server_base, poll_interval_seconds=payload.get("poll_interval_seconds") or "10")

    local_files = _download_files(attachment_urls, server_base, token)
    if local_files:
        request_data["attach_files"] = local_files

    try:
        from server.bizbox_selenium import auto_upload_purchase_request
    except Exception:
        tb = _log_exception("import server.bizbox_selenium failed")
        return {
            "success": False,
            "message": "server.bizbox_selenium 모듈을 불러오지 못했습니다. client_web_agent.py를 DevERP_WEB 루트 폴더에서 실행해야 합니다.",
            "traceback": tb,
        }

    result = auto_upload_purchase_request(request_data, biz_id, biz_pw)
    return {
        "success": bool(result.get("success")),
        "message": result.get("message") or "",
        "result": result,
        "downloaded_files": local_files,
    }


def _order_mail(payload: Dict[str, Any]) -> Dict[str, Any]:
    biz_id = str(payload.get("bizbox_id") or "").strip()
    biz_pw = str(payload.get("bizbox_pw") or "")
    if not biz_id or not biz_pw:
        return {"success": False, "message": "Bizbox 아이디/비밀번호가 없습니다."}

    server_base = str(payload.get("server_base") or "").rstrip("/")
    token = str(payload.get("token") or "")
    mail_jobs = list(payload.get("mail_jobs") or [])
    if server_base:
        _save_agent_settings(server_base=server_base, poll_interval_seconds=payload.get("poll_interval_seconds") or "10")

    prepared_jobs = []
    downloaded: List[str] = []
    for job in mail_jobs:
        j = dict(job or {})
        urls = j.get("attachment_urls") or []
        local_files = _download_files(urls, server_base, token)
        downloaded.extend(local_files)
        j["attachments"] = local_files
        prepared_jobs.append(j)

    try:
        from server.bizbox_order_mail import auto_open_order_mail_windows
    except Exception:
        tb = _log_exception("import server.bizbox_order_mail failed")
        return {
            "success": False,
            "message": "server.bizbox_order_mail 모듈을 불러오지 못했습니다. client_web_agent.py를 DevERP_WEB 루트 폴더에서 실행해야 합니다.",
            "traceback": tb,
        }

    result = auto_open_order_mail_windows(prepared_jobs, biz_id, biz_pw)
    return {
        "success": bool(result.get("success")),
        "message": result.get("message") or "",
        "result": result,
        "downloaded_files": downloaded,
    }


class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True


class Handler(BaseHTTPRequestHandler):
    server_version = "DevERPClientAgent/" + APP_VERSION

    def log_message(self, fmt: str, *args: Any) -> None:
        _log("HTTP " + (fmt % args))

    def _send_json(self, status: int, data: Dict[str, Any]) -> None:
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()
        self.wfile.write(raw)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path = urllib.parse.urlparse(self.path).path
        if path == "/health":
            self._send_json(200, _agent_health_payload())
            return
        if path == "/notifications/status":
            self._send_json(200, {"success": True, **_notification_status_payload()})
            return
        self._send_json(404, {"success": False, "message": "not found", "path": path})

    def _read_payload(self) -> Tuple[bool, Dict[str, Any] | str]:
        try:
            length = int(self.headers.get("Content-Length") or "0")
            raw = self.rfile.read(length) if length > 0 else b"{}"
            if not raw:
                return True, {}
            return True, json.loads(raw.decode("utf-8"))
        except Exception as e:
            return False, str(e)

    def do_POST(self) -> None:  # noqa: N802
        path = urllib.parse.urlparse(self.path).path
        ok, payload_or_error = self._read_payload()
        if not ok:
            self._send_json(400, {"success": False, "message": "JSON 파싱 실패", "error": str(payload_or_error)})
            return
        payload = payload_or_error if isinstance(payload_or_error, dict) else {}
        try:
            if path == "/bizbox/purchase_request":
                self._send_json(200, _purchase_request(payload))
                return
            if path == "/bizbox/order_mail":
                self._send_json(200, _order_mail(payload))
                return
            if path == "/notifications/configure":
                _save_agent_settings(
                    server_base=str(payload.get("server_base") or "").rstrip("/"),
                    server_base_fallback=str(payload.get("server_base_fallback") or "").rstrip("/"),
                    poll_interval_seconds=payload.get("poll_interval_seconds") or "10",
                )
                self._send_json(200, {"success": True, **_notification_status_payload()})
                return
            self._send_json(404, {"success": False, "message": "not found", "path": path})
        except Exception as e:
            tb = _log_exception(f"endpoint failed: {path}")
            self._send_json(200, {"success": False, "message": str(e), "traceback": tb})


def main() -> int:
    _log(f"starting {APP_VERSION} at http://{AGENT_HOST}:{AGENT_PORT}, root={ROOT_DIR}")
    _start_notification_worker()
    print("=" * 70, flush=True)
    print(" DevERP Client Automation Agent", flush=True)
    print(f" Version: {APP_VERSION}", flush=True)
    print(f" URL    : http://{AGENT_HOST}:{AGENT_PORT}/health", flush=True)
    print(f" Root   : {ROOT_DIR}", flush=True)
    print(" 이 창은 웹 접속 PC에서 Bizbox Selenium 자동화를 실행하기 위해 필요합니다.", flush=True)
    print(" 중지하려면 Ctrl+C", flush=True)
    print("=" * 70, flush=True)
    try:
        httpd = ReusableThreadingHTTPServer((AGENT_HOST, AGENT_PORT), Handler)
    except OSError as e:
        _log_exception("bind failed")
        print(f"[오류] {AGENT_HOST}:{AGENT_PORT} 포트를 열 수 없습니다: {e}", flush=True)
        return 10
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n종료합니다.", flush=True)
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
