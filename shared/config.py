import os
import sys
import json
import socket
import ipaddress
import shutil

# 패키지 내부 리소스 위치와 실제 실행 데이터 저장 위치를 분리한다.
# PyInstaller onedir 실행 시 __file__은 _internal/shared 쪽을 가리킬 수 있어
# DB가 _internal 안에 저장되면 업데이트 때 비밀번호/업무 데이터가 사라지기 쉽다.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNTIME_BASE_DIR = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else BASE_DIR


def _load_client_settings() -> dict:
    """client/settings.json을 찾아 읽는다.
    주의: 웹/API 주소는 서버 실행 PC IP를 자동 감지하므로 api_server_url 고정값은 기본적으로 무시한다.
    QR 외부접속용 public_mobile_url/use_ngrok/ngrok_authtoken은 유지한다.
    """
    exe_dir = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.getcwd()
    meipass = getattr(sys, "_MEIPASS", "")
    candidates = [
        os.path.join(BASE_DIR, "client", "settings.json"),
        os.path.join(exe_dir, "client", "settings.json"),
        os.path.join(exe_dir, "_internal", "client", "settings.json"),
        os.path.join(meipass, "client", "settings.json") if meipass else "",
        os.path.join(os.getcwd(), "client", "settings.json"),
        os.path.join(os.getcwd(), "_internal", "client", "settings.json"),
    ]
    for path in candidates:
        try:
            if path and os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    data["_settings_path"] = path
                    return data
        except Exception:
            pass
    return {}


_CLIENT_SETTINGS = _load_client_settings()

# ngrok 자동 실행용 토큰. 보안상 환경변수 사용 권장.
NGROK_AUTHTOKEN = os.getenv("DEVERP_NGROK_AUTHTOKEN", _CLIENT_SETTINGS.get("ngrok_authtoken", "")).strip()



def _abs_path(value: str, default_rel: str) -> str:
    raw = os.getenv(value, default_rel)
    if os.path.isabs(raw):
        return raw
    return os.path.abspath(os.path.join(RUNTIME_BASE_DIR, raw))


def _is_usable_lan_ip(ip: str) -> bool:
    try:
        obj = ipaddress.ip_address(ip)
        # 회사 내부망에서 접속 가능한 사설 IP만 우선 사용한다.
        return obj.is_private and not obj.is_loopback and not obj.is_link_local
    except Exception:
        return False


def _detect_lan_ip() -> str:
    """서버 실행 PC의 사내 LAN IP 자동 감지.
    기존 socket(8.8.8.8) 방식이 공인 IP를 잡는 환경이 있어,
    hostname 기반 사설 IP를 먼저 찾고, 마지막에만 socket 방식을 사용한다.
    """
    candidates = []

    try:
        hostname = socket.gethostname()
        for ip in socket.gethostbyname_ex(hostname)[2]:
            if ip not in candidates:
                candidates.append(ip)
    except Exception:
        pass

    # Windows 환경에서 getaddrinfo가 gethostbyname_ex보다 더 잘 잡히는 경우 보완
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in candidates:
                candidates.append(ip)
    except Exception:
        pass

    # 사설 IP 우선 반환
    for ip in candidates:
        if _is_usable_lan_ip(ip):
            return ip

    # 보조: 실제 라우팅 인터페이스 확인
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if _is_usable_lan_ip(ip):
            return ip
        # 사설 IP가 전혀 없을 때만 공인 IP를 마지막 폴백으로 허용
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass

    return "127.0.0.1"


DETECTED_LAN_IP = _detect_lan_ip()

# ─────────────────────────────────────────────────────────────
# 서버 주소 구조
# 1) 웹/API 서버: 서버 실행 PC의 사내 IP 자동 반영
# 2) QR 모바일 서버: ngrok 우선, 실패 시 사내 IP:8001
# ─────────────────────────────────────────────────────────────
LOCAL_SERVER_HOST = os.getenv("DEVERP_LOCAL_SERVER_HOST", DETECTED_LAN_IP)
LOCAL_SERVER_PORT = int(os.getenv("DEVERP_LOCAL_SERVER_PORT", "8000"))
LOCAL_MOBILE_PORT = int(os.getenv("DEVERP_LOCAL_MOBILE_PORT", "8001"))

LOCAL_SERVER_BASE = os.getenv(
    "DEVERP_LOCAL_SERVER_BASE",
    f"http://{LOCAL_SERVER_HOST}:{LOCAL_SERVER_PORT}"
).rstrip("/")

LOCAL_MOBILE_BASE = os.getenv(
    "DEVERP_LOCAL_MOBILE_BASE",
    f"http://{LOCAL_SERVER_HOST}:{LOCAL_MOBILE_PORT}"
).rstrip("/")

# 중요:
# client/settings.json의 api_server_url에 예전 192.168.100.72 또는 공인 IP가 남아 있어도
# 서버 자체 웹/API 주소는 항상 현재 서버 PC IP를 사용한다.
# 단, 환경변수 DEVERP_API_SERVER_BASE를 주면 수동 고정 가능.
API_SERVER_BASE = os.getenv("DEVERP_API_SERVER_BASE", LOCAL_SERVER_BASE).rstrip("/")
API_BASE_URL = f"{API_SERVER_BASE}/api"

PUBLIC_SERVER_BASE = os.getenv("DEVERP_PUBLIC_SERVER_BASE", API_SERVER_BASE).rstrip("/")

LEGACY_QR_PUBLIC_BASE = "https://garment-dig-duress.ngrok-free.dev"

PUBLIC_MOBILE_BASE = os.getenv(
    "DEVERP_PUBLIC_MOBILE_BASE",
    _CLIENT_SETTINGS.get("public_mobile_url")
    or _CLIENT_SETTINGS.get("ngrok_domain")
    or LEGACY_QR_PUBLIC_BASE
    or LOCAL_MOBILE_BASE,
).rstrip("/")

ROLES = {
    "dev":          "개발그룹",
    "purchase":     "구매그룹",
    "general":      "일반사용자",
    "quality":      "품질팀",
    "manufacture":  "제조팀",
    "admin":        "관리자"
}

MENU_PERMISSIONS = {
    "dev": ["dashboard", "purchase_request", "receipt_status", "settings"],
    "purchase": ["dashboard", "purchase_order", "receipt_status", "settings"],
    "general": ["dashboard", "receipt_status", "settings"],
    "quality": ["dashboard", "receipt_status", "settings"],
    "manufacture": ["dashboard", "receipt_status", "settings"],
    "admin": ["dashboard", "purchase_request", "purchase_order", "receipt_status", "settings"],
}


BIZBOX_URL      = os.getenv("DEVERP_BIZBOX_URL", "http://gwa.innorobotics.co.kr")
BIZBOX_LOGIN_ID = os.getenv("DEVERP_BIZBOX_LOGIN_ID", "")
BIZBOX_LOGIN_PW = os.getenv("DEVERP_BIZBOX_LOGIN_PW", "")

EMAIL_HOST     = os.getenv("DEVERP_EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT     = int(os.getenv("DEVERP_EMAIL_PORT", "587"))
EMAIL_USER     = os.getenv("DEVERP_EMAIL_USER", "")
EMAIL_PASSWORD = os.getenv("DEVERP_EMAIL_PASSWORD", "")

DB_PATH = _abs_path("DEVERP_DB_PATH", "database/dev_erp.db")

# v40 DB 보존 보정:
# 이전 빌드에서 _internal/database/dev_erp.db에 저장되던 DB가 있고,
# 새 외부 database/dev_erp.db가 아직 없으면 자동으로 복사한다.
try:
    _legacy_internal_db = os.path.join(BASE_DIR, "database", "dev_erp.db")
    if getattr(sys, "frozen", False) and not os.path.exists(DB_PATH) and os.path.exists(_legacy_internal_db):
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        shutil.copy2(_legacy_internal_db, DB_PATH)
except Exception:
    pass

QR_SAVE_PATH = _abs_path("DEVERP_QR_SAVE_PATH", "qr_codes")
QR_SCHEDULER_INTERVAL = int(os.getenv("DEVERP_QR_SCHEDULER_INTERVAL", "10"))

# 하위 호환용 별칭
SERVER_HOST = LOCAL_SERVER_HOST
SERVER_PORT = LOCAL_SERVER_PORT
MOBILE_PORT = LOCAL_MOBILE_PORT
SERVER_BASE = API_SERVER_BASE
MOBILE_BASE = PUBLIC_MOBILE_BASE
