# server/routers/system.py
# 시스템 설정 관련 API (런타임 외부 URL 조회/변경, ngrok 터널 제어)

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from server.database import get_db
from pydantic import BaseModel
import os, sys, threading, time, socket, urllib.parse, ipaddress
from pathlib import Path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import shared.config as cfg

router = APIRouter()

_ngrok_job_lock = threading.RLock()
_ngrok_job = {"status": "idle", "message": "", "started_at": "", "finished_at": "", "qr": None}



def _load_client_settings_for_ngrok() -> dict:
    """서버 소스/EXE 실행 위치에서 client/settings.json을 찾아 ngrok 설정을 읽는다."""
    import json
    exe_dir = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.getcwd()
    meipass = getattr(sys, "_MEIPASS", "")
    base = Path(__file__).resolve().parents[2]
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


def _configured_ngrok_token(override: str = "") -> str:
    s = _load_client_settings_for_ngrok()
    return (override or os.getenv("DEVERP_NGROK_AUTHTOKEN", "") or os.getenv("NGROK_AUTHTOKEN", "") or s.get("ngrok_authtoken", "") or getattr(cfg, "NGROK_AUTHTOKEN", "") or "").strip()


def _regenerate_all_qr_internal(db: Session) -> dict:
    from server.database import ReceiptItem, PurchaseOrder
    from server.qr_generator import generate_qr_for_item
    count = 0
    skipped = 0
    errors = []
    for item in db.query(ReceiptItem).filter(ReceiptItem.qr_code != None).all():
        try:
            order = getattr(item, "order", None) or db.query(PurchaseOrder).filter(PurchaseOrder.id == item.order_id).first()
            if not order:
                skipped += 1
                continue
            generate_qr_for_item(item, order, db)
            count += 1
        except Exception as e:
            skipped += 1
            errors.append(str(e))
    return {"regenerated": count, "skipped": skipped, "errors": errors[:10]}



def _set_ngrok_job(**kwargs):
    with _ngrok_job_lock:
        _ngrok_job.update(kwargs)


def _get_ngrok_job() -> dict:
    with _ngrok_job_lock:
        return dict(_ngrok_job)


def _start_ngrok_server_background(token: str, regenerate_qr: bool):
    """ngrok은 클라이언트가 아니라 서버 PC 프로세스에서 백그라운드로 시작한다."""
    from server.ngrok_tunnel import is_starting, get_effective_tunnel_url
    if is_starting():
        _set_ngrok_job(status="starting", message="ngrok 서버 시작이 이미 진행 중입니다.", started_at=time.strftime("%Y-%m-%d %H:%M:%S"))
        return False

    with _ngrok_job_lock:
        if _ngrok_job.get("status") == "starting":
            return False
        _ngrok_job.update({
            "status": "starting",
            "message": "서버 PC에서 ngrok 터널 시작 중입니다.",
            "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "finished_at": "",
            "qr": None,
        })

    def _run():
        try:
            from server.ngrok_tunnel import start_ngrok_tunnel, get_last_error
            from server.database import SessionLocal
            url = start_ngrok_tunnel(port=cfg.MOBILE_PORT, authtoken=token, wait_seconds=60)
            if url:
                cfg.PUBLIC_MOBILE_BASE = url.rstrip("/")
                cfg.MOBILE_BASE = cfg.PUBLIC_MOBILE_BASE
                qr = {"regenerated": 0, "skipped": 0, "errors": []}
                if regenerate_qr:
                    db2 = SessionLocal()
                    try:
                        qr = _regenerate_all_qr_internal(db2)
                    finally:
                        db2.close()
                _set_ngrok_job(
                    status="running",
                    message="ngrok 터널이 서버 PC에서 실행 중입니다.",
                    finished_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                    qr=qr,
                )
            else:
                _set_ngrok_job(
                    status="failed",
                    message=get_last_error() or "ngrok 터널 시작 실패",
                    finished_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                )
        except Exception as e:
            _set_ngrok_job(
                status="failed",
                message=str(e),
                finished_at=time.strftime("%Y-%m-%d %H:%M:%S"),
            )

    threading.Thread(target=_run, daemon=True).start()
    return True




class PublicUrlUpdate(BaseModel):
    url: str          # 수동 외부 URL (빈 문자열이면 초기화)
    save_to_env: bool = False


class NgrokStartRequest(BaseModel):
    authtoken: str = ""
    regenerate_qr: bool = True


@router.get("/public_url")
def get_public_url():
    """현재 런타임 외부 URL 반환"""
    from server.ngrok_tunnel import get_effective_tunnel_url, get_last_error
    s = _load_client_settings_for_ngrok()
    ngrok_url = get_effective_tunnel_url(timeout=0.5)
    if ngrok_url:
        cfg.PUBLIC_MOBILE_BASE = ngrok_url.rstrip("/")
        cfg.MOBILE_BASE = cfg.PUBLIC_MOBILE_BASE
    public_mobile = cfg.PUBLIC_MOBILE_BASE if not bool(s.get("use_ngrok", True)) else (ngrok_url or "")
    return {
        "public_mobile_base": public_mobile,
        "local_mobile_base": getattr(cfg, "LOCAL_MOBILE_BASE", ""),
        "qr_mobile_base": getattr(cfg, "LOCAL_MOBILE_BASE", "") if bool(s.get("qr_prefer_lan", True)) else public_mobile,
        "qr_prefer_lan": qr_prefer_lan,
        "public_server_base": cfg.PUBLIC_SERVER_BASE,
        "ngrok_active": bool(ngrok_url),
        "ngrok_url": ngrok_url,
        "ngrok_last_error": get_last_error(),
        "use_ngrok": bool(s.get("use_ngrok", True)),
        "ngrok_token_set": bool(_configured_ngrok_token()),
        "settings_path": s.get("_settings_path", ""),
        "ngrok_job": _get_ngrok_job(),
    }


@router.post("/public_url")
def set_public_url(body: PublicUrlUpdate):
    """외부 모바일 URL을 수동으로 런타임 변경 (QR 재생성 시 반영됨)"""
    url = body.url.strip().rstrip("/")
    if url and not url.startswith(('http://', 'https://')):
        url = 'http://' + url
    cfg.PUBLIC_MOBILE_BASE = url if url else ""
    cfg.MOBILE_BASE = cfg.PUBLIC_MOBILE_BASE
    return {"success": True, "public_mobile_base": cfg.PUBLIC_MOBILE_BASE}


@router.post("/ngrok/start")
def start_ngrok(body: NgrokStartRequest, db: Session = Depends(get_db)):
    """서버 PC에서 ngrok 터널을 시작하고 URL을 즉시 확보한다.

    v25: 백그라운드 job 상태만 남기고 UI가 계속 '시작 중'으로 멈추던 구조를 제거했다.
    이 API는 최대 약 40초 동안 URL을 기다린 뒤 성공/실패를 명확히 반환한다.
    """
    from server.ngrok_tunnel import start_ngrok_tunnel, get_effective_tunnel_url, get_last_error, get_status
    import shared.config as cfg2

    token = _configured_ngrok_token(body.authtoken.strip())
    _set_ngrok_job(
        status="starting",
        message="서버 PC에서 ngrok 터널 시작 중입니다.",
        started_at=time.strftime("%Y-%m-%d %H:%M:%S"),
        finished_at="",
        qr=None,
    )
    # 내부망 주소보다 ngrok 주소를 우선한다. 이미 온라인인 reserved endpoint/설정 URL/마지막 성공 URL이 있으면 먼저 사용한다.
    url = (get_effective_tunnel_url(timeout=0.6, allow_last_known=True) or "").strip().rstrip("/")
    if not url:
        url = (start_ngrok_tunnel(port=cfg2.MOBILE_PORT, authtoken=token, wait_seconds=35) or "").strip().rstrip("/")
    if not url:
        url = (get_effective_tunnel_url(timeout=0.5, allow_last_known=True) or "").strip().rstrip("/")

    if url:
        cfg2.PUBLIC_MOBILE_BASE = url
        cfg2.MOBILE_BASE = cfg2.PUBLIC_MOBILE_BASE
        regen = {"regenerated": 0, "skipped": 0, "errors": []}
        if body.regenerate_qr:
            regen = _regenerate_all_qr_internal(db)
        _set_ngrok_job(
            status="running",
            message="ngrok 주소가 적용되었습니다.",
            finished_at=time.strftime("%Y-%m-%d %H:%M:%S"),
            qr=regen,
        )
        return {"success": True, "starting": False, "url": cfg2.PUBLIC_MOBILE_BASE, "qr": regen, "status": get_status(timeout=0.1)}

    msg = get_last_error() or "ngrok URL을 확보하지 못했습니다. logs/ngrok_tunnel.log 와 .runtime/ngrok_stdout.log를 확인하세요."
    _set_ngrok_job(status="failed", message=msg, finished_at=time.strftime("%Y-%m-%d %H:%M:%S"), qr=None)
    return {"success": False, "starting": False, "url": "", "message": msg, "last_error": msg, "status": get_status(timeout=0.1)}


@router.get("/ngrok/status")
def ngrok_status():
    """서버 PC ngrok 상태 조회."""
    from server.ngrok_tunnel import get_effective_tunnel_url, get_last_error, get_status
    url = get_effective_tunnel_url(timeout=0.4)
    if url:
        cfg.PUBLIC_MOBILE_BASE = url.rstrip("/")
        cfg.MOBILE_BASE = cfg.PUBLIC_MOBILE_BASE
        if _get_ngrok_job().get("status") in ("idle", "starting", "failed"):
            _set_ngrok_job(status="running", message="ngrok 터널이 서버 PC에서 실행 중입니다.", finished_at=time.strftime("%Y-%m-%d %H:%M:%S"))
    return {
        "success": True,
        "ngrok_active": bool(url),
        "ngrok_url": url,
        "public_mobile_base": url or "",
        "ngrok_last_error": "" if url else get_last_error(),
        "ngrok_status": get_status(timeout=0.1),
        "job": _get_ngrok_job(),
        "token_set": bool(_configured_ngrok_token()),
    }


@router.post("/ngrok/stop")
def stop_ngrok():
    """ngrok 터널 종료"""
    from server.ngrok_tunnel import stop_ngrok_tunnel
    import shared.config as cfg2
    stop_ngrok_tunnel()
    cfg2.PUBLIC_MOBILE_BASE = ""
    cfg2.MOBILE_BASE = ""
    _set_ngrok_job(status="idle", message="ngrok 터널을 종료했습니다.", finished_at=time.strftime("%Y-%m-%d %H:%M:%S"), qr=None)
    return {"success": True}


class QrRegenRequest(BaseModel):
    pass


@router.post("/qr/regenerate_all")
def regenerate_all_qr(db: Session = Depends(get_db)):
    """
    현재 PUBLIC_MOBILE_BASE URL로 모든 QR 코드 재생성.
    ngrok URL 변경 후 호출하면 기존 QR도 새 URL로 교체됨.
    """
    from server.database import ReceiptItem, PurchaseOrder
    from server.qr_generator import generate_qr_for_item
    import shared.config as cfg2

    items = db.query(ReceiptItem).filter(ReceiptItem.qr_code != None).all()
    count = 0
    skipped = 0
    errors = []
    for item in items:
        try:
            order = getattr(item, "order", None) or db.query(PurchaseOrder).filter(PurchaseOrder.id == item.order_id).first()
            if not order:
                skipped += 1
                continue
            generate_qr_for_item(item, order, db)
            count += 1
        except Exception as e:
            skipped += 1
            errors.append(str(e))
    return {
        "success": True,
        "regenerated": count,
        "skipped": skipped,
        "new_base_url": cfg2.PUBLIC_MOBILE_BASE,
        "local_mobile_base": getattr(cfg2, "LOCAL_MOBILE_BASE", ""),
        "qr_prefer_lan": False,
        "errors": errors[:10],
    }


# ── 웹 접속 PC 클라이언트 자동화 에이전트 설치 패키지 ─────────────────────────────
CLIENT_AGENT_VERSION = "client-agent-20260529-v42-black-log-click-notifications"
CLIENT_AGENT_INSTALL_DIR_NAME = "DevERP_Client_Agent"
CLIENT_AGENT_INSTALL_DIR = r"%USERPROFILE%\Documents\DevERP_Client_Agent"
CLIENT_AGENT_SETUP_FILENAME = "install_client_agent_to_Documents_autorun.bat"
CLIENT_AGENT_EXE_FILENAME = "DevERP_Client_Agent_EXE_Package.zip"
CLIENT_AGENT_TASK_NAME = "DevERP_Client_Agent"


def _is_lan_or_loopback_host(host: str) -> bool:
    host = (host or '').strip().lower().split(':')[0].strip('[]')
    if host in {'localhost', '127.0.0.1', '::1'}:
        return True
    try:
        ip = ipaddress.ip_address(host)
        return bool(ip.is_private or ip.is_loopback or ip.is_link_local)
    except Exception:
        return False


def _detect_lan_ip() -> str:
    """Return the server PC LAN IPv4 address for fast internal downloads."""
    env_ip = (os.getenv('DEVERP_LAN_IP') or os.getenv('SERVER_LAN_IP') or '').strip()
    if env_ip:
        return env_ip
    # UDP connect does not send packets, but lets Windows choose the active NIC.
    for target in [('8.8.8.8', 80), ('1.1.1.1', 80), ('192.168.0.1', 80)]:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.settimeout(0.2)
                sock.connect(target)
                ip = sock.getsockname()[0]
                if ip and not ip.startswith('127.'):
                    return ip
        except Exception:
            pass
    try:
        ip = socket.gethostbyname(socket.gethostname())
        if ip and not ip.startswith('127.'):
            return ip
    except Exception:
        pass
    return ''


def _server_base_from_request(request: Request) -> str:
    """Current browser-facing base URL."""
    try:
        return str(request.base_url).rstrip('/')
    except Exception:
        return cfg.API_SERVER_BASE.rstrip('/')


def _server_lan_base_from_request(request: Request) -> str:
    """LAN base URL used by client PC setup BAT so large EXE ZIPs do not go through ngrok."""
    current = _server_base_from_request(request)
    try:
        u = urllib.parse.urlparse(current)
        host = u.hostname or ''
        port = u.port
        scheme = 'http'  # LAN download should stay plain HTTP for speed and certificate-free access.
        if _is_lan_or_loopback_host(host):
            return current
        lan_ip = _detect_lan_ip()
        if lan_ip:
            return f'{scheme}://{lan_ip}' + (f':{port}' if port else '')
    except Exception:
        pass
    return current


def _agent_root() -> Path:
    """소스 실행/빌드 실행 모두에서 클라이언트 에이전트 배포 기준 폴더를 찾는다."""
    candidates = []
    try:
        candidates.append(Path(__file__).resolve().parents[2])
    except Exception:
        pass
    try:
        exe_dir = Path(sys.executable).resolve().parent
        candidates.append(exe_dir)
        candidates.append(exe_dir / '_internal')
    except Exception:
        pass
    try:
        meipass = getattr(sys, '_MEIPASS', '')
        if meipass:
            candidates.append(Path(meipass))
    except Exception:
        pass
    candidates.append(Path.cwd())
    candidates.append(Path.cwd() / '_internal')
    for base in candidates:
        if base and (base / 'client_web_agent.py').exists():
            return base
    return Path(__file__).resolve().parents[2]



def _find_client_agent_exe() -> Path | None:
    """서버가 배포할 수 있는 DevERP_Client_Agent.exe 위치를 찾는다."""
    base = _agent_root()
    candidates = [
        base / 'bundled_client_agent' / 'DevERP_Client_Agent' / 'DevERP_Client_Agent.exe',
        base / 'dist' / 'DevERP_Client_Agent' / 'DevERP_Client_Agent.exe',
        base / 'DevERP_Client_Agent' / 'DevERP_Client_Agent.exe',
        base / 'DevERP_Client_Agent.exe',
    ]
    for fp in candidates:
        try:
            if fp.exists() and fp.is_file():
                return fp
        except Exception:
            pass
    return None

def _agent_package_files():
    """클라이언트 PC의 내 문서\\DevERP_Client_Agent 폴더에 복사될 파일 목록.

    v32부터는 Python이 없는 클라이언트 PC에서도 실행되도록 PyInstaller로 빌드한
    DevERP_Client_Agent.exe 폴더를 패키지에 우선 포함한다. EXE가 없을 때만
    이전처럼 Python 소스 모드로도 진단/실행할 수 있게 소스 파일을 함께 담는다.
    """
    base = _agent_root()
    root_files = [
        'client_web_agent.py',
        'start_client_agent.bat',
        'run_client_agent_hidden.bat',
        'run_client_agent_hidden.ps1',
        'run_client_agent_hidden.vbs',
        'run_client_agent_console.bat',
        'register_client_agent_startup.ps1',
        'stop_client_agent.bat',
        'remove_client_agent_startup.bat',
        'check_client_agent.bat',
        'requirements_client_agent.txt',
    ]
    skip_dirs = {'__pycache__', '.git', '.idea', '.vscode', 'build', 'build_client_agent', 'logs', '.runtime'}
    skip_suffixes = {'.pyc', '.pyo'}
    emitted = set()

    def emit(fp: Path, rel: str):
        key = rel.replace('\\', '/')
        if key in emitted:
            return
        emitted.add(key)
        yield fp, key

    def emit_tree(src: Path, rel_prefix: str):
        if not src.exists():
            return
        for fp in src.rglob('*'):
            if not fp.is_file():
                continue
            rel_parts = fp.relative_to(src).parts
            if any(part in skip_dirs for part in rel_parts):
                continue
            if fp.suffix.lower() in skip_suffixes:
                continue
            rel = (Path(rel_prefix) / fp.relative_to(src)).as_posix()
            yield from emit(fp, rel)

    # 1) Standalone EXE runtime. setup BAT extracts this to
    #    Documents\DevERP_Client_Agent\dist\DevERP_Client_Agent\DevERP_Client_Agent.exe
    #    and run_client_agent_hidden.ps1 starts it before trying Python.
    built_agent_dirs = [
        base / 'bundled_client_agent' / 'DevERP_Client_Agent',
        base / 'dist' / 'DevERP_Client_Agent',
        base / 'DevERP_Client_Agent',
    ]
    for src in built_agent_dirs:
        if (src / 'DevERP_Client_Agent.exe').exists():
            yield from emit_tree(src, 'dist/DevERP_Client_Agent')
            break

    # 2) Keep source-mode files as fallback/diagnostics.
    for name in root_files:
        fp = base / name
        if fp.exists() and fp.is_file():
            yield from emit(fp, name)

    for folder in ['server', 'shared']:
        src = base / folder
        if not src.exists():
            continue
        for fp in src.rglob('*'):
            if not fp.is_file():
                continue
            rel_parts = fp.relative_to(base).parts
            if any(part in skip_dirs for part in rel_parts):
                continue
            if fp.suffix.lower() in skip_suffixes:
                continue
            rel = fp.relative_to(base).as_posix()
            yield from emit(fp, rel)


@router.get('/client_agent/status')
def client_agent_status(request: Request):
    """웹 UI가 30초마다 호출해서 설치파일 URL/버전을 확인한다."""
    base = _server_base_from_request(request)
    lan_base = _server_lan_base_from_request(request)
    exe_fp = _find_client_agent_exe()
    return {
        'success': True,
        'version': CLIENT_AGENT_VERSION,
        'health_url': 'http://127.0.0.1:8765/health',
        # setup_url intentionally prefers LAN. If the web page was opened through ngrok,
        # large EXE downloads still come from the internal server IP.
        'setup_url': f'{lan_base}/api/system/client_agent/setup_bat',
        'setup_url_current': f'{base}/api/system/client_agent/setup_bat',
        'setup_filename': CLIENT_AGENT_SETUP_FILENAME,
        'exe_url': f'{lan_base}/api/system/client_agent/exe',
        'exe_url_current': f'{base}/api/system/client_agent/exe',
        'exe_filename': CLIENT_AGENT_EXE_FILENAME,
        'exe_available': bool(exe_fp),
        'package_url': f'{lan_base}/api/system/client_agent/package',
        'server_base': base,
        'server_lan_base': lan_base,
        'install_dir': CLIENT_AGENT_INSTALL_DIR,
        'install_dir_note': 'The setup BAT resolves this to the current user Documents folder using [Environment]::GetFolderPath([Environment+SpecialFolder]::MyDocuments).',
        'task_name': CLIENT_AGENT_TASK_NAME,
        'check_interval_seconds': 30,
    }



def _notify_dt(value) -> str:
    if not value:
        return ''
    try:
        if hasattr(value, 'strftime'):
            return value.strftime('%Y-%m-%d %H:%M:%S')
        return str(value)[:19]
    except Exception:
        return str(value or '')


def _notify_latest(*values) -> str:
    vals = [_notify_dt(v) for v in values if _notify_dt(v)]
    return max(vals) if vals else ''


def _notify_item_stage(item) -> str:
    if getattr(item, 'manufacture_recv_at', None) or getattr(item, 'manufacture_recv_by', None):
        return '생산팀입고'
    if getattr(item, 'quality_recv_at', None) or getattr(item, 'quality_recv_by', None):
        return '품질검수/출고'
    if getattr(item, 'purchase_recv_at', None) or getattr(item, 'purchase_recv_by', None):
        return '구매팀입고'
    return '미입고'


@router.get('/client_agent/notifications')
def client_agent_notifications(request: Request, db: Session = Depends(get_db)):
    """클라이언트 PC 상주 에이전트가 웹페이지 없이도 입고/진행상태 변경을 감지할 수 있게 하는 상태 피드."""
    from server.database import PurchaseOrder, ReceiptItem

    events = []
    orders = db.query(PurchaseOrder).order_by(PurchaseOrder.id.asc()).all()
    for order in orders:
        status = str(getattr(order, 'status', '') or '').strip()
        if status in {'', '삭제', '취소'}:
            continue
        pr = getattr(order, 'purchase_request', None)
        req_no = (getattr(pr, 'request_no', '') or getattr(order, 'order_no', '') or '').strip()
        title = (getattr(pr, 'title_full', '') or getattr(pr, 'project_name', '') or '').strip()
        vendor = str(getattr(order, 'vendor_name', '') or '미정업체').strip()
        changed_at = _notify_latest(getattr(order, 'order_completed_at', None), getattr(order, 'tax_docs_completed_at', None), getattr(order, 'order_date', None))
        sig = '|'.join([
            status,
            _notify_dt(getattr(order, 'order_completed_at', None)),
            _notify_dt(getattr(order, 'tax_docs_completed_at', None)),
            _notify_dt(getattr(order, 'delivery_date', None)),
            str(getattr(order, 'email_sent', '') or ''),
        ])
        label = f"{req_no} / {vendor}" if req_no else vendor
        detail = f"\n{title}" if title else ''
        events.append({
            'key': f'order_status:{order.id}',
            'signature': sig,
            'kind': 'order_status',
            'title': 'DevERP 진행상태 알림',
            'message': f"{label}\n진행상태가 '{status}'로 변경되었습니다.{detail}",
            'changed_at': changed_at,
            'notify_on_new': status not in {'작성완료', '상신완료'},
        })

    items = db.query(ReceiptItem).order_by(ReceiptItem.id.asc()).all()
    for item in items:
        order = getattr(item, 'order', None)
        pr = getattr(order, 'purchase_request', None) if order else None
        req_no = (getattr(pr, 'request_no', '') or getattr(order, 'order_no', '') if order else '').strip()
        vendor = str(getattr(order, 'vendor_name', '') or '미정업체').strip() if order else ''
        stage = _notify_item_stage(item)
        changed_at = _notify_latest(
            getattr(item, 'purchase_recv_at', None),
            getattr(item, 'quality_recv_at', None),
            getattr(item, 'manufacture_recv_at', None),
            getattr(item, 'created_at', None),
        )
        actor = getattr(item, 'manufacture_recv_by', None) or getattr(item, 'quality_recv_by', None) or getattr(item, 'purchase_recv_by', None) or ''
        sig = '|'.join([
            stage,
            _notify_dt(getattr(item, 'purchase_recv_at', None)), str(getattr(item, 'purchase_recv_by', '') or ''),
            _notify_dt(getattr(item, 'quality_recv_at', None)), str(getattr(item, 'quality_recv_by', '') or ''),
            _notify_dt(getattr(item, 'manufacture_recv_at', None)), str(getattr(item, 'manufacture_recv_by', '') or ''),
        ])
        item_name = str(getattr(item, 'item_name', '') or '품목').strip()
        qty = str(getattr(item, 'quantity', '') or '').strip()
        unit = str(getattr(item, 'unit', '') or '').strip()
        qty_text = f" ({qty}{unit})" if qty or unit else ''
        head = ' / '.join([x for x in [req_no, vendor] if x])
        actor_text = f"\n처리자: {actor}" if actor else ''
        events.append({
            'key': f'receipt_item:{item.id}',
            'signature': sig,
            'kind': 'receipt_item',
            'title': 'DevERP 입고 알림',
            'message': f"{head}\n{item_name}{qty_text} → {stage}{actor_text}",
            'changed_at': changed_at,
            'notify_on_new': stage != '미입고',
        })

    # 버튼 클릭, 모바일 QR 처리처럼 상태값이 이미 같아도 사용자 액션 자체를 알려야 하는 이벤트를 추가한다.
    try:
        from server.notification_events import recent_notification_events
        events.extend(recent_notification_events(200))
    except Exception:
        pass

    base_url = str(request.base_url).rstrip('/')
    return {
        'success': True,
        'server_time': time.strftime('%Y-%m-%d %H:%M:%S'),
        'poll_interval_seconds': 5,
        'log_url': base_url + '/api/system/client_agent/notification_log_page',
        'log_endpoint': base_url + '/api/system/client_agent/notification_logs',
        'events': events,
    }


class ClientNotificationLogRequest(BaseModel):
    displayed: bool = True
    client: str = ''
    events: list[dict] = []


@router.post('/client_agent/notification_logs')
def client_agent_notification_logs_save(data: ClientNotificationLogRequest):
    from server.notification_events import append_notification_log
    saved = []
    for ev in data.events or []:
        try:
            row = append_notification_log(ev, source='client-agent', displayed=bool(data.displayed), client=data.client)
            if row:
                saved.append(row)
        except Exception:
            pass
    return {'success': True, 'saved': len(saved)}


@router.get('/client_agent/notification_logs')
def client_agent_notification_logs(limit: int = 300):
    from server.notification_events import recent_notification_logs
    return {'success': True, 'logs': list(reversed(recent_notification_logs(limit)))}


def _notification_log_html_escape(value) -> str:
    import html
    return html.escape(str(value or ''), quote=True)


@router.get('/client_agent/notification_log_page')
def client_agent_notification_log_page(limit: int = 300):
    from fastapi.responses import HTMLResponse
    from server.notification_events import recent_notification_logs
    logs = list(reversed(recent_notification_logs(limit)))
    rows = []
    for i, row in enumerate(logs, 1):
        title = _notification_log_html_escape(row.get('title'))
        msg = _notification_log_html_escape(row.get('message')).replace('\n', '<br>')
        changed_at = _notification_log_html_escape(row.get('changed_at'))
        logged_at = _notification_log_html_escape(row.get('logged_at'))
        last_seen = _notification_log_html_escape(row.get('last_seen_at'))
        kind = _notification_log_html_escape(row.get('kind'))
        source = _notification_log_html_escape(row.get('source'))
        displayed = '표시됨' if row.get('displayed') else '서버기록'
        rows.append(f'''<tr>
<td>{i}</td><td>{changed_at}</td><td>{logged_at}</td><td>{last_seen}</td><td>{displayed}</td><td>{kind}<br><small>{source}</small></td><td><b>{title}</b><div class="msg">{msg}</div></td>
</tr>''')
    body = '\n'.join(rows) or '<tr><td colspan="7" class="empty">저장된 알림 로그가 없습니다.</td></tr>'
    html = f'''<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>DevERP 알림 로그</title>
<style>
body{{font-family:Malgun Gothic,Arial,sans-serif;margin:0;background:#f3f4f6;color:#111827}}
header{{background:#111827;color:white;padding:16px 22px;display:flex;justify-content:space-between;align-items:center}}
h1{{font-size:22px;margin:0}}
a.btn{{color:white;background:#2563eb;text-decoration:none;padding:8px 12px;border-radius:8px}}
main{{padding:18px 22px}}
table{{width:100%;border-collapse:collapse;background:white;border-radius:10px;overflow:hidden;box-shadow:0 1px 6px rgba(0,0,0,.12)}}
th,td{{border-bottom:1px solid #e5e7eb;padding:10px 12px;text-align:left;vertical-align:top;font-size:14px}}
th{{background:#e5e7eb;position:sticky;top:0;z-index:1}}
.msg{{margin-top:6px;line-height:1.45;white-space:normal}}
small{{color:#6b7280}}
.empty{{text-align:center;color:#6b7280;padding:40px}}
</style></head><body>
<header><h1>DevERP 알림 로그</h1><a class="btn" href="/api/system/client_agent/notification_log_page">새로고침</a></header>
<main><table><thead><tr><th>No</th><th>변경시각</th><th>저장시각</th><th>표시/확인시각</th><th>상태</th><th>구분</th><th>내용</th></tr></thead><tbody>{body}</tbody></table></main>
</body></html>'''
    return HTMLResponse(html)


@router.get('/client_agent/exe')
def client_agent_exe():
    """웹 UI에서 받을 수 있는 DevERP_Client_Agent.exe 실행 패키지 ZIP.

    현재 빌드는 PyInstaller onedir 방식이므로 EXE 단독 파일만 복사하면 일부 PC에서
    DLL/라이브러리 누락으로 실행되지 않을 수 있다. 따라서 EXE가 포함된 폴더 전체를 ZIP으로 내려준다.
    """
    from fastapi import HTTPException
    from fastapi.responses import StreamingResponse
    import io, zipfile, time, json
    fp = _find_client_agent_exe()
    if not fp:
        raise HTTPException(
            status_code=404,
            detail='DevERP_Client_Agent.exe가 아직 빌드되지 않았습니다. 서버 PC에서 build.bat을 다시 실행하면 생성됩니다.'
        )
    root = fp.parent
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, 'w', zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
        if root.name == 'DevERP_Client_Agent':
            for item in root.rglob('*'):
                if item.is_file():
                    zf.write(item, (Path('DevERP_Client_Agent') / item.relative_to(root)).as_posix())
        else:
            zf.write(fp, 'DevERP_Client_Agent.exe')
        zf.writestr('client_agent_exe_manifest.json', json.dumps({
            'app': 'DevERP Client Agent',
            'version': CLIENT_AGENT_VERSION,
            'exe': 'DevERP_Client_Agent/DevERP_Client_Agent.exe' if root.name == 'DevERP_Client_Agent' else 'DevERP_Client_Agent.exe',
            'note': 'PyInstaller onedir EXE runtime package. EXE 단독 복사보다 이 ZIP 전체를 압축 해제해서 실행하세요.',
        }, ensure_ascii=False, indent=2))
    bio.seek(0)
    headers = {'Content-Disposition': f'attachment; filename={CLIENT_AGENT_EXE_FILENAME}', 'Cache-Control': 'no-store'}
    return StreamingResponse(bio, media_type='application/zip', headers=headers)


@router.get('/client_agent/package')
def client_agent_package():
    """설치 BAT가 내려받는 실제 클라이언트 에이전트 ZIP."""
    import io, zipfile, json, time
    from fastapi.responses import StreamingResponse
    bio = io.BytesIO()
    files = list(_agent_package_files())
    has_built_exe = any(rel.replace('\\', '/').lower().endswith('deverp_client_agent.exe') for _fp, rel in files)
    with zipfile.ZipFile(bio, 'w', zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
        for fp, rel in sorted(files, key=lambda x: x[1]):
            zf.write(fp, rel)
        zf.writestr('client_agent_manifest.json', json.dumps({
            'app': 'DevERP Client Agent',
            'version': CLIENT_AGENT_VERSION,
            'install_dir': CLIENT_AGENT_INSTALL_DIR,
        'install_dir_note': 'The setup BAT resolves this to the current user Documents folder using [Environment]::GetFolderPath([Environment+SpecialFolder]::MyDocuments).',
            'task_name': CLIENT_AGENT_TASK_NAME,
            'created_at': time.strftime('%Y-%m-%d %H:%M:%S'),
            'file_count': len(files),
            'has_built_exe': has_built_exe,
            'note': 'has_built_exe=true이면 클라이언트 PC에 Python이 없어도 실행됩니다. setup BAT는 현재 사용자 내 문서\\DevERP_Client_Agent 폴더에 설치하고 로그인 자동실행을 등록합니다.',
        }, ensure_ascii=False, indent=2))
    bio.seek(0)
    headers = {'Content-Disposition': 'attachment; filename=DevERP_Client_Agent_Package.zip', 'Cache-Control': 'no-store'}
    return StreamingResponse(bio, media_type='application/zip', headers=headers)


@router.get('/client_agent/setup_bat')
def client_agent_setup_bat(request: Request):
    """Download-only setup BAT for client PCs without Python."""
    from fastapi.responses import Response
    base = _server_base_from_request(request)
    lan_base = _server_lan_base_from_request(request)
    lines = [
        '@echo off',
        'chcp 65001 >nul',
        'setlocal EnableExtensions',
        'title DevERP Client Agent LAN EXE Auto Install v39',
        f'set "SERVER_BASE={lan_base}"',
        f'set "SERVER_BASE_FALLBACK={base}"',
        'set "TASK_NAME=DevERP_Client_Agent"',
        "for /f \"usebackq delims=\" %%D in (`powershell -NoProfile -ExecutionPolicy Bypass -Command \"[Environment]::GetFolderPath([Environment+SpecialFolder]::MyDocuments)\"`) do set \"DOCS_DIR=%%D\"",
        'if not defined DOCS_DIR set "DOCS_DIR=%USERPROFILE%\\Documents"',
        'set "INSTALL_DIR=%DOCS_DIR%\\DevERP_Client_Agent"',
        'set "ZIP_FILE=%TEMP%\\DevERP_Client_Agent_EXE_Package.zip"',
        'set "TMP_EXTRACT=%TEMP%\\DevERP_Client_Agent_EXE_extract"',
        'set "EXE_PATH=%INSTALL_DIR%\\DevERP_Client_Agent.exe"',
        'echo ========================================',
        'echo DevERP Client Agent LAN EXE Auto Install v39',
        'echo ========================================',
        f'echo Version: {CLIENT_AGENT_VERSION}',
        'echo Server LAN : %SERVER_BASE%',
        'echo Fallback   : %SERVER_BASE_FALLBACK%',
        'echo Target : %INSTALL_DIR%',
        'echo.',
        'echo [0/10] Run as current Windows user...',
        'echo [INFO] Administrator permission is not required. This keeps Documents and startup registration under the current login account.',
        'echo [1/10] Stop old local agent processes...',
        'taskkill /F /T /IM DevERP_Client_Agent.exe >nul 2>nul',
        "for /f \"tokens=5\" %%P in ('netstat -ano ^| findstr /R /C:\":8765 .*LISTENING\"') do taskkill /F /T /PID %%P >nul 2>nul",
        'for /L %%I in (1,1,10) do (',
        '    tasklist /FI "IMAGENAME eq DevERP_Client_Agent.exe" 2^>nul ^| find /I "DevERP_Client_Agent.exe" >nul',
        '    if errorlevel 1 goto OLD_AGENT_STOPPED',
        '    timeout /t 1 /nobreak >nul',
        ')',
        ':OLD_AGENT_STOPPED',
        'echo [2/10] Prepare clean folders...',
        'if exist "%TMP_EXTRACT%" rmdir /s /q "%TMP_EXTRACT%" >nul 2>nul',
        'mkdir "%TMP_EXTRACT%" >nul 2>nul',
        'if exist "%INSTALL_DIR%" rmdir /s /q "%INSTALL_DIR%" >nul 2>nul',
        'if exist "%INSTALL_DIR%" (',
        '    echo [ERROR] Cannot remove old install folder. Close DevERP_Client_Agent.exe or Explorer windows in that folder and retry.',
        '    echo Folder: %INSTALL_DIR%',
        '    pause',
        '    exit /b 5',
        ')',
        'mkdir "%INSTALL_DIR%" >nul 2>nul',
        'mkdir "%INSTALL_DIR%\\logs" >nul 2>nul',
        'echo [3/10] Download EXE package from LAN server...',
        'echo [INFO] This installer tries LAN first. Ngrok/current URL is only used as fallback.',
        'if exist "%ZIP_FILE%" del /f /q "%ZIP_FILE%" >nul 2>nul',
        'where curl.exe >nul 2>nul',
        'if not errorlevel 1 (',
        '    curl.exe -fL --connect-timeout 5 --retry 1 -o "%ZIP_FILE%" "%SERVER_BASE%/api/system/client_agent/exe"',
        ') else (',
        '    powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference=\'SilentlyContinue\'; $ErrorActionPreference=\'Stop\'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -UseBasicParsing -Uri \'%SERVER_BASE%/api/system/client_agent/exe\' -OutFile \'%ZIP_FILE%\'"',
        ')',
        'if errorlevel 1 (',
        '    echo [WARN] LAN download failed. Trying fallback URL...',
        '    if exist "%ZIP_FILE%" del /f /q "%ZIP_FILE%" >nul 2>nul',
        '    where curl.exe >nul 2>nul',
        '    if not errorlevel 1 (',
        '        curl.exe -fL --connect-timeout 10 --retry 1 -o "%ZIP_FILE%" "%SERVER_BASE_FALLBACK%/api/system/client_agent/exe"',
        '    ) else (',
        '        powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference=\'SilentlyContinue\'; $ErrorActionPreference=\'Stop\'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -UseBasicParsing -Uri \'%SERVER_BASE_FALLBACK%/api/system/client_agent/exe\' -OutFile \'%ZIP_FILE%\'"',
        '    )',
        ')',
        'if errorlevel 1 (',
        '    echo.',
        '    echo [ERROR] EXE package download failed.',
        '    echo LAN URL     : %SERVER_BASE%',
        '    echo Fallback URL: %SERVER_BASE_FALLBACK%',
        '    echo Server PC must run build.bat first so DevERP_Client_Agent.exe exists.',
        '    pause',
        '    exit /b 1',
        ')',
        'echo [4/10] Extract EXE package...',
        "powershell -NoProfile -ExecutionPolicy Bypass -Command \"$ErrorActionPreference='Stop'; Expand-Archive -Path '%ZIP_FILE%' -DestinationPath '%TMP_EXTRACT%' -Force\"",
        'if errorlevel 1 (',
        '    echo.',
        '    echo [ERROR] Extract failed.',
        '    pause',
        '    exit /b 2',
        ')',
        'echo [5/10] Copy EXE runtime to Documents folder...',
        'if exist "%TMP_EXTRACT%\\DevERP_Client_Agent\\DevERP_Client_Agent.exe" (',
        '    xcopy /e /y /i "%TMP_EXTRACT%\\DevERP_Client_Agent" "%INSTALL_DIR%" >nul',
        ') else if exist "%TMP_EXTRACT%\\DevERP_Client_Agent.exe" (',
        '    copy /y "%TMP_EXTRACT%\\DevERP_Client_Agent.exe" "%EXE_PATH%" >nul',
        ') else (',
        '    echo [ERROR] DevERP_Client_Agent.exe was not found inside downloaded ZIP.',
        '    echo This installer cannot run without the EXE package.',
        '    pause',
        '    exit /b 3',
        ')',
        'if not exist "%EXE_PATH%" (',
        '    echo [ERROR] Install failed. EXE missing: %EXE_PATH%',
        '    pause',
        '    exit /b 3',
        ')',
        'echo client-agent-20260529-v42-black-log-click-notifications > "%INSTALL_DIR%\\installed_version.txt"',
        'echo {"server_base":"%SERVER_BASE%","server_base_fallback":"%SERVER_BASE_FALLBACK%","poll_interval_seconds":10} > "%INSTALL_DIR%\\client_agent_settings.json"',
        'echo [OK] Standalone EXE installed. Python is NOT required on this PC.',
        'echo [6/10] Create local launcher and diagnostic files...',
        '> "%INSTALL_DIR%\\run_client_agent_hidden.vbs" echo Set sh = CreateObject("WScript.Shell")',
        '>> "%INSTALL_DIR%\\run_client_agent_hidden.vbs" echo sh.CurrentDirectory = "%INSTALL_DIR%"',
        '>> "%INSTALL_DIR%\\run_client_agent_hidden.vbs" echo sh.Run """%EXE_PATH%""", 0, False',
        '> "%INSTALL_DIR%\\run_client_agent_console.bat" echo @echo off',
        '>> "%INSTALL_DIR%\\run_client_agent_console.bat" echo cd /d "%%~dp0"',
        '>> "%INSTALL_DIR%\\run_client_agent_console.bat" echo "%%~dp0DevERP_Client_Agent.exe"',
        '>> "%INSTALL_DIR%\\run_client_agent_console.bat" echo pause',
        '> "%INSTALL_DIR%\\stop_client_agent.bat" echo @echo off',
        ">> \"%INSTALL_DIR%\\stop_client_agent.bat\" echo for /f \"tokens=5\" %%%%P in ('netstat -ano ^^| findstr /R /C:\":8765 .*LISTENING\"') do taskkill /F /PID %%%%P",
        '> "%INSTALL_DIR%\\check_client_agent.bat" echo @echo off',
        '>> "%INSTALL_DIR%\\check_client_agent.bat" echo echo Install path: %INSTALL_DIR%',
        '>> "%INSTALL_DIR%\\check_client_agent.bat" echo echo EXE path: %EXE_PATH%',
        '>> "%INSTALL_DIR%\\check_client_agent.bat" echo netstat -ano ^^| findstr /R /C:":8765 .*LISTENING"',
        ">> \"%INSTALL_DIR%\\check_client_agent.bat\" echo powershell -NoProfile -ExecutionPolicy Bypass -Command \"try{ $r=Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8765/health' -TimeoutSec 2; Write-Host $r.Content }catch{ Write-Host $_.Exception.Message }\"",
        'echo [7/10] Register Windows login auto-start...',
        "reg add \"HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run\" /v \"%TASK_NAME%\" /t REG_SZ /d \"wscript.exe //B ^\"%INSTALL_DIR%\\run_client_agent_hidden.vbs^\"\" /f >nul 2>nul",
        'if not exist "%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Startup" mkdir "%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Startup" >nul 2>nul',
        'copy /y "%INSTALL_DIR%\\run_client_agent_hidden.vbs" "%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Startup\\DevERP_Client_Agent.vbs" >nul 2>nul',
        "schtasks /Create /TN \"%TASK_NAME%\" /SC ONLOGON /TR \"wscript.exe //B ^\"%INSTALL_DIR%\\run_client_agent_hidden.vbs^\"\" /RL LIMITED /F >nul 2>nul",
        'echo [8/10] Start agent now...',
        'wscript.exe //B "%INSTALL_DIR%\\run_client_agent_hidden.vbs"',
        'echo [9/10] Health/version check...',
        "powershell -NoProfile -ExecutionPolicy Bypass -Command \"$expected='client-agent-20260529-v42-black-log-click-notifications'; for($i=1;$i -le 30;$i++){ try{ $r=Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8765/health' -TimeoutSec 1; $txt=[string]$r.Content; if($r.StatusCode -eq 200){ Write-Host $txt; if($txt -like ('*' + $expected + '*')){ exit 0 } else { Write-Host ('[VERSION_MISMATCH] expected=' + $expected); exit 2 } } }catch{}; Start-Sleep -Seconds 1 }; exit 1\"",
        'if errorlevel 1 (',
        '    echo.',
        '    echo [FAIL] Client agent did not respond with the expected version.',
        '    echo Expected version: client-agent-20260529-v42-black-log-click-notifications',
        '    echo This usually means the old EXE was still running or the server EXE package was not rebuilt.',
        '    echo A visible console test window will open now. Check its error message.',
        '    start "DevERP Client Agent Console" "%INSTALL_DIR%\\run_client_agent_console.bat"',
        '    echo Run this for diagnostics : "%INSTALL_DIR%\\check_client_agent.bat"',
        '    echo Install path: %INSTALL_DIR%',
        '    pause',
        '    exit /b 4',
        ')',
        'echo [10/10] Auto-start registration check...',
        'reg query "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run" /v "%TASK_NAME%" >nul 2>nul && echo   HKCU Run: OK || echo   HKCU Run: missing',
        'if exist "%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Startup\\DevERP_Client_Agent.vbs" (echo   Startup folder: OK) else (echo   Startup folder: missing)',
        'schtasks /Query /TN "%TASK_NAME%" >nul 2>nul && echo   Task Scheduler: OK || echo   Task Scheduler: not registered, HKCU/Startup fallback will be used.',
        'echo.',
        'echo ========================================',
        'echo Install complete - Client Agent is running',
        'echo ========================================',
        'echo Health: http://127.0.0.1:8765/health',
        'echo EXE   : %EXE_PATH%',
        'echo Path  : %INSTALL_DIR%',
        'echo Login : registered',
        'echo.',
        'timeout /t 10 /nobreak >nul',
        'exit /b 0',
    ]
    bat = '\r\n'.join(lines) + '\r\n'
    headers = {'Content-Disposition': f'attachment; filename={CLIENT_AGENT_SETUP_FILENAME}', 'Cache-Control': 'no-store'}
    return Response(content=bat.encode('ascii', errors='replace'), media_type='application/octet-stream', headers=headers)


@router.get('/client_agent/setup.bat')
def client_agent_setup_bat_alias(request: Request):
    return client_agent_setup_bat(request)


@router.get('/client_agent/package.zip')
def client_agent_package_alias():
    return client_agent_package()

