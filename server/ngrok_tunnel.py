# server/ngrok_tunnel.py
# DevERP_WEB QR용 ngrok 터널 관리자
# v25: v18처럼 시작 시 URL을 확실히 확보하되, v19~v24의 상태 API/로그 기능 유지

import json
import logging
import os
import shutil
import subprocess
import re
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger(__name__)

_tunnel_url: str = ""
_tunnel_active: bool = False
_last_error: str = ""
_ngrok_process = None
_start_lock = threading.RLock()
_starting: bool = False
_last_started_at: str = ""
_last_finished_at: str = ""


def _root_dir() -> Path:
    try:
        return Path(__file__).resolve().parents[1]
    except Exception:
        return Path(os.getcwd()).resolve()


def _runtime_dir() -> Path:
    runtime = _root_dir() / ".runtime"
    runtime.mkdir(exist_ok=True)
    return runtime


def _log_path() -> Path:
    logs = _root_dir() / "logs"
    logs.mkdir(exist_ok=True)
    return logs / "ngrok_tunnel.log"


def _last_url_path() -> Path:
    return _runtime_dir() / "last_ngrok_url.txt"


def _write_log(message: str):
    try:
        with _log_path().open("a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S") + " " + str(message) + "\n")
    except Exception:
        pass
    try:
        logger.info(message)
    except Exception:
        pass


def _set_error(message: str):
    global _last_error
    _last_error = str(message or "").strip()
    if _last_error:
        _write_log("ERROR: " + _last_error)


def _save_last_url(url: str):
    url = _normalize_url(url)
    if not url:
        return
    try:
        _last_url_path().write_text(url, encoding="utf-8")
    except Exception:
        pass


def _load_last_url() -> str:
    try:
        return _normalize_url(_last_url_path().read_text(encoding="utf-8"))
    except Exception:
        return ""


def _load_settings() -> dict:
    exe_dir = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.getcwd()
    meipass = getattr(sys, "_MEIPASS", "")
    base = _root_dir()
    candidates = [
        base / "client" / "settings.json",
        Path(exe_dir) / "client" / "settings.json",
        Path(exe_dir) / "_internal" / "client" / "settings.json",
        Path(meipass) / "client" / "settings.json" if meipass else None,
        Path(os.getcwd()) / "client" / "settings.json",
        Path(os.getcwd()) / "_internal" / "client" / "settings.json",
    ]
    for p in candidates:
        try:
            if p and Path(p).exists():
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                data["_settings_path"] = str(p)
                return data
        except Exception:
            pass
    return {}


def _normalize_url(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    if url.startswith("http://"):
        url = url.replace("http://", "https://", 1)
    return url.rstrip("/")


def _extract_ngrok_url_from_text(text: str) -> str:
    """ngrok 오류/로그 문장 안의 https://...ngrok... 주소를 추출한다.

    ERR_NGROK_334처럼 'endpoint ... is already online'인 경우는 실제로
    고정 ngrok 주소가 이미 열려 있다는 뜻이므로, 시작 실패로 처리하지 않고
    그 주소를 QR/모바일 기준 주소로 사용한다.
    """
    text = str(text or "")
    if not text:
        return ""
    # pyngrok 오류는 escaped text(\r\n)로 들어오는 경우가 있어 그대로 정규식 처리한다.
    patterns = [
        r"endpoint ['\"]?(https://[^'\"\s,}]+ngrok[^'\"\s,}]*)['\"]?",
        r"(https://[A-Za-z0-9_.-]+\.ngrok(?:-free)?\.[A-Za-z0-9_.-]+)",
        r"(https://[A-Za-z0-9_.-]+\.ngrok-free\.dev)",
        r"(https://[A-Za-z0-9_.-]+\.ngrok-free\.app)",
        r"(https://[A-Za-z0-9_.-]+\.ngrok\.io)",
    ]
    for pat in patterns:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            return _normalize_url(m.group(1))
    return ""


def _read_text_tail(path: Path, max_chars: int = 12000) -> str:
    try:
        if path.exists():
            data = path.read_text(encoding="utf-8", errors="ignore")
            return data[-max_chars:]
    except Exception:
        pass
    return ""


def _extract_url_from_runtime_logs() -> str:
    runtime = _runtime_dir()
    logs = _root_dir() / "logs"
    texts = [
        _read_text_tail(runtime / "ngrok_stdout.log"),
        _read_text_tail(logs / "ngrok_tunnel.log"),
    ]
    for text in texts:
        url = _extract_ngrok_url_from_text(text)
        if url:
            return url
    return ""


def _set_tunnel_url(url: str, source: str = "") -> str:
    """확보/설정된 ngrok URL을 전역 상태와 shared.config에 즉시 반영한다."""
    global _tunnel_url, _tunnel_active, _last_error
    url = _normalize_url(url)
    if not url:
        return ""
    _tunnel_url = url
    _tunnel_active = True
    _last_error = ""
    _save_last_url(url)
    try:
        import shared.config as cfg
        cfg.PUBLIC_MOBILE_BASE = url.rstrip("/")
        cfg.MOBILE_BASE = cfg.PUBLIC_MOBILE_BASE
    except Exception:
        pass
    _write_log(f"ngrok URL 적용{(' (' + source + ')') if source else ''}: {url}")
    return url


LEGACY_NGROK_DOMAIN = "garment-dig-duress.ngrok-free.dev"


def _fixed_domain_from_settings() -> str:
    """client/settings.json/env의 고정 ngrok 도메인을 추출한다.

    이미 외부에 배포된 QR은 URL 자체가 고정되어 있으므로, 설정이 비어 있더라도
    기존 배포 QR 기준 도메인(LEGACY_NGROK_DOMAIN)을 기본값으로 사용한다.
    다른 ngrok 고정 도메인을 쓰려면 client/settings.json의 ngrok_domain 또는
    public_mobile_url, 또는 환경변수 DEVERP_NGROK_DOMAIN/DEVERP_PUBLIC_MOBILE_BASE로
    덮어쓴다.
    """
    s = _load_settings()
    raw = (
        os.getenv("DEVERP_NGROK_DOMAIN", "")
        or os.getenv("DEVERP_PUBLIC_MOBILE_BASE", "")
        or s.get("ngrok_domain")
        or s.get("public_mobile_url")
        or LEGACY_NGROK_DOMAIN
        or ""
    ).strip()
    if not raw:
        return ""
    if "://" not in raw:
        host = raw.strip().strip("/")
    else:
        host = urlparse(raw).netloc
    host = host.split("/")[0].strip()
    if host and "ngrok" in host.lower():
        return host
    return ""


def get_tunnel_url() -> str:
    return _tunnel_url


def is_active() -> bool:
    return _tunnel_active


def get_last_error() -> str:
    return _last_error


def is_starting() -> bool:
    return bool(_starting)


def _check_local_api(timeout: float = 1.2) -> str:
    """서버 PC의 ngrok local API에서 현재 public URL 확인."""
    try:
        import requests
        r = requests.get("http://127.0.0.1:4040/api/tunnels", timeout=timeout)
        data = r.json()
        tunnels = data.get("tunnels") or []
        for t in tunnels:
            url = _normalize_url(t.get("public_url", ""))
            if url.startswith("https://"):
                return url
        for t in tunnels:
            url = _normalize_url(t.get("public_url", ""))
            if url:
                return url
    except Exception:
        return ""
    return ""


def get_effective_tunnel_url(timeout: float = 0.7, allow_last_known: bool = True) -> str:
    """실제 ngrok URL을 반환한다.

    1) 현재 프로세스가 확보한 URL
    2) ngrok local API URL
    3) 설정의 고정 ngrok 도메인 또는 마지막 성공 URL

    3번은 고정 ngrok 도메인을 쓰는 환경에서 서버 재시작 직후 UI가 내부망으로
    떨어지는 것을 막기 위한 표시/QR 기준값이다. 실제 터널이 살아있는지는
    ngrok_active 값으로 별도 표시한다.
    """
    global _tunnel_url, _tunnel_active
    url = _normalize_url(_tunnel_url)
    if url:
        _tunnel_active = True
        return url
    url = _check_local_api(timeout=timeout)
    if url:
        _tunnel_url = url
        _tunnel_active = True
        _save_last_url(url)
        return url
    _tunnel_active = False
    if allow_last_known:
        # 1순위: settings/env에 고정해 둔 ngrok 주소
        domain = _fixed_domain_from_settings()
        if domain:
            return _set_tunnel_url(domain, "configured ngrok URL")

        # 2순위: ERR_NGROK_334 등 오류/로그에 찍힌 이미 온라인인 endpoint URL
        parsed = _extract_ngrok_url_from_text(_last_error) or _extract_url_from_runtime_logs()
        if parsed:
            return _set_tunnel_url(parsed, "detected existing ngrok endpoint")

        # 3순위: 마지막 성공 URL. 내부망 폴백 대신 ngrok 주소를 우선 유지한다.
        last = _load_last_url()
        if last:
            return _set_tunnel_url(last, "last known ngrok URL")
    return ""


def get_status(timeout: float = 0.25) -> dict:
    live = get_effective_tunnel_url(timeout=timeout, allow_last_known=False)
    display = live or get_effective_tunnel_url(timeout=0.05, allow_last_known=True)
    proc_alive = False
    try:
        proc_alive = bool(_ngrok_process and _ngrok_process.poll() is None)
    except Exception:
        proc_alive = False
    return {
        "starting": bool(_starting),
        "active": bool(live),
        "url": display,
        "live_url": live,
        "last_error": _last_error,
        "process_alive": proc_alive,
        "started_at": _last_started_at,
        "finished_at": _last_finished_at,
    }


def _kill_all_ngrok_processes():
    global _ngrok_process
    try:
        from pyngrok import ngrok
        try:
            ngrok.kill()
        except Exception:
            pass
    except Exception:
        pass

    try:
        if _ngrok_process and _ngrok_process.poll() is None:
            _ngrok_process.terminate()
            try:
                _ngrok_process.wait(timeout=4)
            except Exception:
                _ngrok_process.kill()
    except Exception:
        pass
    _ngrok_process = None

    if os.name == "nt":
        try:
            subprocess.run(["taskkill", "/F", "/T", "/IM", "ngrok.exe"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=8)
        except Exception:
            pass
    else:
        try:
            subprocess.run(["pkill", "-f", "ngrok"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=8)
        except Exception:
            pass
    time.sleep(1.0)


def _isolated_config_path(authtoken: str) -> str:
    cfg = _runtime_dir() / "ngrok_runtime.yml"
    lines = ["version: '2'"]
    if authtoken:
        lines.append(f"authtoken: {authtoken}")
    cfg.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(cfg)


def _find_ngrok_exe() -> str:
    candidates = []
    env = os.getenv("DEVERP_NGROK_EXE") or os.getenv("NGROK_PATH")
    if env:
        candidates.append(env)
    root = _root_dir()
    candidates.extend([
        str(root / "ngrok.exe"),
        str(root / "bin" / "ngrok.exe"),
        str(Path(os.getcwd()) / "ngrok.exe"),
        str(Path(os.getcwd()) / "bin" / "ngrok.exe"),
        str(Path(os.getenv("LOCALAPPDATA", "")) / "ngrok" / "ngrok.exe"),
        str(Path(os.path.expanduser("~")) / "AppData" / "Local" / "ngrok" / "ngrok.exe"),
    ])
    path_hit = shutil.which("ngrok") or shutil.which("ngrok.exe")
    if path_hit:
        candidates.append(path_hit)
    for c in candidates:
        if c and Path(c).exists():
            return str(Path(c).resolve())
    return ""


def _start_with_ngrok_exe(port: int, authtoken: str, wait_seconds: int = 35) -> str:
    """ngrok.exe 직접 실행. pyngrok보다 먼저 시도해서 connect 블로킹 문제를 피한다."""
    global _ngrok_process
    exe = _find_ngrok_exe()
    if not exe:
        _set_error("ngrok.exe를 찾지 못했습니다. pyngrok 방식으로 재시도합니다.")
        return ""

    config_path = _isolated_config_path(authtoken)
    stdout_path = _runtime_dir() / "ngrok_stdout.log"
    domain = _fixed_domain_from_settings()
    _write_log(f"ngrok.exe 직접 실행 시도: {exe} http {port}, domain={domain or '-'}")

    try:
        out = stdout_path.open("a", encoding="utf-8", errors="ignore")
        cmd = [exe, "http", str(port), "--config", config_path, "--log=stdout"]
        if domain:
            # ngrok v3 fixed Dev Domains are started with --url.
            # Some older builds accept --domain, but --url is the current form.
            cmd.append(f"--url=https://{domain}")
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        _ngrok_process = subprocess.Popen(
            cmd,
            stdout=out,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            cwd=str(_root_dir()),
            creationflags=creationflags,
        )
    except Exception as e:
        _set_error(f"ngrok.exe 실행 실패: {e}")
        return ""

    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        url = _check_local_api(timeout=1.0)
        if url:
            return url
        # 고정 도메인 사용 시 local API가 늦어도 URL은 확정 가능하다.
        if domain and time.time() > deadline - wait_seconds + 3:
            live = _normalize_url(domain)
            _write_log(f"고정 ngrok 도메인 기준 URL 사용: {live}")
            return live
        if _ngrok_process and _ngrok_process.poll() is not None:
            log_text = _read_text_tail(stdout_path)
            parsed = _extract_ngrok_url_from_text(log_text)
            if parsed:
                return _set_tunnel_url(parsed, "ngrok.exe already-online endpoint")
            _set_error(f"ngrok.exe가 조기 종료되었습니다. exit={_ngrok_process.returncode}, log={stdout_path}")
            return ""
        time.sleep(1.0)

    parsed = _extract_url_from_runtime_logs()
    if parsed:
        return _set_tunnel_url(parsed, "ngrok.exe log endpoint")
    _set_error(f"ngrok.exe 실행 후 {wait_seconds}초 안에 터널 URL을 받지 못했습니다. log={stdout_path}")
    return ""


def _start_with_pyngrok(port: int, authtoken: str) -> str:
    try:
        from pyngrok import ngrok, conf
    except ImportError as e:
        _set_error(f"pyngrok 미설치: {e}")
        return ""

    token = (authtoken or os.getenv("NGROK_AUTHTOKEN") or os.getenv("DEVERP_NGROK_AUTHTOKEN") or "").strip()
    config_path = _isolated_config_path(token)
    domain = _fixed_domain_from_settings()

    try:
        pycfg = conf.PyngrokConfig(config_path=config_path, auth_token=token or None)
        if token:
            os.environ["NGROK_AUTHTOKEN"] = token
            try:
                conf.get_default().auth_token = token
                ngrok.set_auth_token(token)
            except Exception:
                pass
        _write_log(f"pyngrok 터널 시작 시도: localhost:{port}, domain={domain or '-'}")
        kwargs = {"addr": str(port), "proto": "http", "bind_tls": True, "pyngrok_config": pycfg}
        if domain:
            kwargs["domain"] = domain
        tunnel = ngrok.connect(**kwargs)
        return _normalize_url(getattr(tunnel, "public_url", ""))
    except Exception as e:
        msg = str(e)
        parsed = _extract_ngrok_url_from_text(msg)
        if parsed:
            return _set_tunnel_url(parsed, "pyngrok already-online endpoint")
        _set_error(f"pyngrok 터널 시작 실패: {e}")
        return ""


def start_ngrok_tunnel(port: int = 8001, authtoken: str = "", wait_seconds: int = 35) -> str:
    global _tunnel_url, _tunnel_active, _starting, _last_started_at, _last_finished_at

    with _start_lock:
        # IMPORTANT:
        # Do NOT trust _tunnel_url / configured / last-known URL here.
        # Existing deployed QR codes point to the legacy ngrok URL, but ERR_NGROK_3200
        # happens when no live tunnel is actually bound to that URL.
        # Therefore startup must check only the live local ngrok API, then force-start ngrok.
        existing = _check_local_api(timeout=0.8)
        if existing:
            return _set_tunnel_url(existing, "live local ngrok API")

        # Even when a fixed ngrok URL is configured, always start the real tunnel process.
        # Otherwise the app only prints/applies the URL while the public endpoint remains offline.

        _starting = True
        _last_started_at = time.strftime("%Y-%m-%d %H:%M:%S")
        _last_finished_at = ""
        _set_error("")
        token = (authtoken or os.getenv("NGROK_AUTHTOKEN") or os.getenv("DEVERP_NGROK_AUTHTOKEN") or "").strip()

        try:
            print("🧹 기존 ngrok.exe 정리 중...")
            _write_log("기존 ngrok 프로세스 정리 중...")
            _kill_all_ngrok_processes()

            print(f"🌐 ngrok 터널 시작: localhost:{port}")
            _write_log(f"ngrok 시작 요청: port={port}, token={'yes' if token else 'no'}")

            # v25: ngrok.exe가 있으면 먼저 사용한다. pyngrok.connect가 멈춰 서버 UI가 대기 중으로 고정되는 문제를 피한다.
            url = _start_with_ngrok_exe(port, token, wait_seconds=wait_seconds)
            if not url:
                url = _start_with_pyngrok(port, token)
            if not url:
                url = _check_local_api(timeout=1.0)
            if not url:
                url = _extract_ngrok_url_from_text(_last_error) or _extract_url_from_runtime_logs()

            url = _normalize_url(url)
            if url:
                _set_tunnel_url(url, "ngrok start result")
                print(f"✅ ngrok 터널 URL: {_tunnel_url}")
                _write_log(f"ngrok 터널 시작 성공/적용: {_tunnel_url} -> localhost:{port}")
            else:
                _tunnel_url = ""
                _tunnel_active = False
                print(f"⚠ ngrok 터널 실패: {_last_error}")
                _write_log("ngrok 터널 시작 실패")
            return _tunnel_url
        finally:
            _starting = False
            _last_finished_at = time.strftime("%Y-%m-%d %H:%M:%S")


def stop_ngrok_tunnel():
    global _tunnel_url, _tunnel_active
    _kill_all_ngrok_processes()
    _tunnel_url = ""
    _tunnel_active = False
    _set_error("")
    _write_log("ngrok 터널 종료됨")


def start_in_background(port: int = 8001, authtoken: str = "", wait_seconds: int = 35) -> str:
    """이름은 기존 호환을 유지하지만, v18처럼 제한 시간 안에서 URL을 확보해서 반환한다."""
    result = {"url": "", "error": ""}

    def _run():
        try:
            url = start_ngrok_tunnel(port, authtoken, wait_seconds=wait_seconds)
            result["url"] = url
            if url:
                try:
                    import shared.config as cfg
                    cfg.PUBLIC_MOBILE_BASE = url.rstrip("/")
                    cfg.MOBILE_BASE = cfg.PUBLIC_MOBILE_BASE
                    _write_log(f"PUBLIC_MOBILE_BASE 업데이트: {url}")
                except Exception:
                    pass
        except Exception as e:
            result["error"] = str(e)
            _set_error(str(e))

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=max(10, wait_seconds + 5))
    if t.is_alive():
        _set_error(f"ngrok 시작이 {wait_seconds}초 이상 지연되고 있습니다. 백그라운드에서 계속 확인 중입니다.")
    return result["url"]
