import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from datetime import datetime
import threading, sys, os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.database import init_db
from server.scheduler import start_scheduler
from server.mobile_qr_app import start_mobile_server
from server.routers import purchase, inventory, users
from server.routers import system as system_router
import shared.config as cfg

app = FastAPI(title="DevERP Server", version="1.0.0")
app.include_router(users.router,         prefix="/api/users",     tags=["users"])
app.include_router(purchase.router,      prefix="/api/purchase",  tags=["purchase"])
app.include_router(inventory.router,     prefix="/api/inventory", tags=["inventory"])
app.include_router(system_router.router, prefix="/api/system",    tags=["system"])


def _web_root_dir():
    """소스 실행/빌드 실행 모두에서 웹 UI 폴더를 찾는다."""
    candidates = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "web"),
        os.path.join(os.getcwd(), "server", "web"),
        os.path.join(os.getcwd(), "_internal", "server", "web"),
        os.path.join(getattr(sys, "_MEIPASS", ""), "server", "web") if getattr(sys, "_MEIPASS", "") else "",
    ]
    for p in candidates:
        if p and os.path.exists(os.path.join(p, "index.html")):
            return p
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")


_WEB_DIR = _web_root_dir()
try:
    app.mount("/web_static", StaticFiles(directory=_WEB_DIR), name="web_static")
except Exception as e:
    print(f"⚠ 웹 정적 폴더 연결 실패: {e}")


@app.get("/")
def root():
    """브라우저 기본 접속 시 JSON이 아니라 웹 화면을 연다."""
    index_path = os.path.join(_WEB_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path, media_type="text/html; charset=utf-8")
    return {
        "status": "DevERP 서버 실행중",
        "version": "1.0.0",
        "message": "server/web/index.html 파일을 찾지 못했습니다.",
        "public_server": cfg.PUBLIC_SERVER_BASE,
        "public_mobile": cfg.PUBLIC_MOBILE_BASE,
    }


@app.get("/web")
def web_app():
    index_path = os.path.join(_WEB_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path, media_type="text/html; charset=utf-8")
    return RedirectResponse("/")


def _ngrok_current_url() -> str:
    try:
        from server.ngrok_tunnel import get_effective_tunnel_url
        url = get_effective_tunnel_url(timeout=0.35)
        if url:
            cfg.PUBLIC_MOBILE_BASE = url.rstrip("/")
            cfg.MOBILE_BASE = cfg.PUBLIC_MOBILE_BASE
        return url
    except Exception:
        return ""


def _ngrok_is_active() -> bool:
    try:
        return bool(_ngrok_current_url())
    except Exception:
        return False


def _settings_use_ngrok() -> bool:
    try:
        import json
        path = _find_settings_path()
        if path:
            with open(path, "r", encoding="utf-8") as f:
                return bool(json.load(f).get("use_ngrok", True))
    except Exception:
        pass
    return True


def _effective_mobile_url() -> str:
    ng = _ngrok_current_url()
    if ng:
        return ng.rstrip("/")
    if _settings_use_ngrok():
        current = str(getattr(cfg, "PUBLIC_MOBILE_BASE", "") or "").strip().rstrip("/")
        if current.startswith("https://") and "ngrok" in current.lower():
            return current
        return ""
    return cfg.PUBLIC_MOBILE_BASE


def _ngrok_last_error() -> str:
    try:
        from server.ngrok_tunnel import get_last_error
        return get_last_error()
    except Exception:
        return ""


def _ngrok_job_status() -> dict:
    try:
        if hasattr(system_router, "_get_ngrok_job"):
            return system_router._get_ngrok_job()
    except Exception:
        pass
    return {}


@app.get("/api/health")
def health():
    ngrok_url = _ngrok_current_url()
    qr_url = _effective_mobile_url()
    return {
        "status": "ok",
        "time": datetime.now().isoformat(),
        "public_server": cfg.PUBLIC_SERVER_BASE,
        "public_mobile": qr_url,
        "server_ip": cfg.DETECTED_LAN_IP,
        "web_url": cfg.API_SERVER_BASE,
        "qr_url": qr_url,
        "ngrok_active": bool(ngrok_url),
        "ngrok_url": ngrok_url,
        "ngrok_last_error": _ngrok_last_error(),
        "ngrok_job": _ngrok_job_status(),
        "use_ngrok": _settings_use_ngrok(),
        "ngrok_required": _settings_use_ngrok(),
    }


@app.get("/api/system/network_info")
def network_info():
    return {
        "server_ip": cfg.DETECTED_LAN_IP,
        "web_url": cfg.API_SERVER_BASE,
        "api_url": cfg.API_BASE_URL,
        "qr_mobile_url": _effective_mobile_url(),
        "server_port": cfg.SERVER_PORT,
        "mobile_port": cfg.MOBILE_PORT,
    }


# ── ngrok/수동URL/LAN IP 자동 적용 ────────────────────────────
def _find_settings_path():
    """서버 exe/소스 실행 모두에서 client/settings.json 탐색"""
    exe_dir = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.getcwd()
    meipass = getattr(sys, "_MEIPASS", "")
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates = [
        os.path.join(base, "client", "settings.json"),
        os.path.join(exe_dir, "client", "settings.json"),
        os.path.join(exe_dir, "_internal", "client", "settings.json"),
        os.path.join(meipass, "client", "settings.json") if meipass else "",
        os.path.join(os.getcwd(), "client", "settings.json"),
        os.path.join(os.getcwd(), "_internal", "client", "settings.json"),
    ]
    for path in candidates:
        if path and os.path.exists(path):
            return path
    return ""


def _start_ngrok_background(authtoken: str):
    """서버 시작을 막지 않고 ngrok을 백그라운드에서 시작한다.

    v19에서 ngrok을 서버 시작 전에 60초까지 동기 대기하면서 start_web_clean.bat가
    멈춘 것처럼 보일 수 있었다. v21에서는 서버를 먼저 띄우고, ngrok URL이
    확보되면 런타임 QR/모바일 주소와 기존 QR 이미지를 즉시 갱신한다.
    """

    def _run():
        try:
            from server.ngrok_tunnel import start_ngrok_tunnel, get_last_error
            url = start_ngrok_tunnel(port=cfg.MOBILE_PORT, authtoken=authtoken, wait_seconds=60)
            if url:
                cfg.PUBLIC_MOBILE_BASE = url.rstrip("/")
                cfg.MOBILE_BASE = cfg.PUBLIC_MOBILE_BASE
                print(f"✅ ngrok 터널 URL: {cfg.PUBLIC_MOBILE_BASE}")
                try:
                    _regenerate_qr_after_public_url_set()
                except Exception as e:
                    print(f"⚠ ngrok URL 기준 QR 재생성 실패: {e}")
            else:
                print(f"⚠ ngrok 터널 실패: {get_last_error()}")
        except Exception as e:
            print(f"⚠ ngrok 백그라운드 시작 오류: {e}")

    t = threading.Thread(target=_run, daemon=True)
    t.start()


def _try_auto_ngrok():
    """QR/모바일 주소는 서버 PC ngrok URL을 우선 사용한다.

    v25: v18에서 정상 동작하던 방식처럼 서버 시작 중 제한 시간 안에서
    ngrok URL을 실제로 확보한 뒤 PUBLIC_MOBILE_BASE에 넣는다.
    단, 실패 시 내부망 주소로 자동 폴백하지 않는다. 외부망 QR이 내부망으로
    생성되는 문제를 막기 위함이다.
    """
    import json

    settings_path = _find_settings_path()
    s = {}
    if settings_path:
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                s = json.load(f)
            print(f"✅ QR 설정 파일 로드: {settings_path}")
        except Exception as e:
            print(f"⚠ QR 설정 파일 읽기 실패: {e}")
    else:
        print("⚠ client/settings.json을 찾지 못했습니다. ngrok 토큰 없이 시도합니다.")

    use_ngrok = bool(s.get("use_ngrok", True))
    manual_url = (
        os.getenv("DEVERP_PUBLIC_MOBILE_BASE", "")
        or os.getenv("DEVERP_NGROK_DOMAIN", "")
        or s.get("public_mobile_url", "")
        or s.get("ngrok_domain", "")
        or "https://garment-dig-duress.ngrok-free.dev"
    ).strip().rstrip("/")
    if manual_url and not manual_url.startswith(("http://", "https://")):
        manual_url = "https://" + manual_url

    if use_ngrok:
        # 기존 배포 QR은 이 고정 ngrok 주소를 바라보고 있으므로 기준 URL은 먼저 고정한다.
        # 단, 여기서 return하지 않고 실제 ngrok 터널도 반드시 시작한다.
        if manual_url and "ngrok" in manual_url.lower():
            cfg.PUBLIC_MOBILE_BASE = manual_url.rstrip("/")
            cfg.MOBILE_BASE = cfg.PUBLIC_MOBILE_BASE
            print(f"✅ QR/모바일 URL (기존 배포 QR 고정 주소): {cfg.PUBLIC_MOBILE_BASE}")

        authtoken = (s.get("ngrok_authtoken", "") or os.getenv("DEVERP_NGROK_AUTHTOKEN", "") or getattr(cfg, "NGROK_AUTHTOKEN", "") or "").strip()
        print("🌐 ngrok 터널 시작 중... 서버 PC에서 모바일/QR용 터널을 엽니다.")
        try:
            from server.ngrok_tunnel import start_in_background, get_effective_tunnel_url, get_last_error
            url = start_in_background(port=cfg.MOBILE_PORT, authtoken=authtoken, wait_seconds=35)
            url = (url or get_effective_tunnel_url(timeout=1.0, allow_last_known=True) or "").strip().rstrip("/")
            if url:
                cfg.PUBLIC_MOBILE_BASE = url
                cfg.MOBILE_BASE = cfg.PUBLIC_MOBILE_BASE
                print(f"✅ ngrok 터널 URL/우선 URL: {cfg.PUBLIC_MOBILE_BASE}")
                return
            print(f"⚠ ngrok 터널 실패: {get_last_error()}")
        except Exception as e:
            print(f"⚠ ngrok 오류: {e}")

        # ngrok 모드에서는 실패해도 내부망으로 폴백하지 않는다.
        cfg.PUBLIC_MOBILE_BASE = ""
        cfg.MOBILE_BASE = cfg.PUBLIC_MOBILE_BASE
        print("⏳ QR/모바일 URL: ngrok URL 미확보 - 내부망 주소로 폴백하지 않음")
        return

    if manual_url:
        cfg.PUBLIC_MOBILE_BASE = manual_url
        cfg.MOBILE_BASE = cfg.PUBLIC_MOBILE_BASE
        print(f"✅ QR/모바일 URL (수동): {cfg.PUBLIC_MOBILE_BASE}")
        return

    cfg.PUBLIC_MOBILE_BASE = f"http://{cfg.DETECTED_LAN_IP}:{cfg.MOBILE_PORT}"
    cfg.MOBILE_BASE = cfg.PUBLIC_MOBILE_BASE
    print(f"✅ QR/모바일 URL (내부망 폴백): {cfg.PUBLIC_MOBILE_BASE}")

def _regenerate_qr_after_public_url_set():
    """서버 시작 시 현재 PUBLIC_MOBILE_BASE 기준으로 기존 QR 이미지를 재생성한다."""
    try:
        from server.database import SessionLocal, ReceiptItem, PurchaseOrder
        from server.qr_generator import generate_qr_for_item
        db = SessionLocal()
        try:
            items = db.query(ReceiptItem).filter(ReceiptItem.qr_code != None).all()
            count = 0
            for item in items:
                order = getattr(item, "order", None) or db.query(PurchaseOrder).filter(PurchaseOrder.id == item.order_id).first()
                if order:
                    generate_qr_for_item(item, order, db)
                    count += 1
            if count:
                print(f"✅ QR 코드 재생성 완료: {count}개 / 기준 URL={cfg.PUBLIC_MOBILE_BASE}")
        finally:
            db.close()
    except Exception as e:
        print(f"⚠ QR 재생성 생략: {e}")


if __name__ == "__main__":
    print("=" * 60)
    print("  DevERP 서버 시작중...")
    print(f"  서버 바인딩: 0.0.0.0:{cfg.SERVER_PORT}")
    print(f"  내부망 웹/API 주소: {cfg.API_SERVER_BASE}")
    print(f"  QR/모바일 주소(초기): {cfg.PUBLIC_MOBILE_BASE}")
    print("=" * 60)

    init_db()

    t = threading.Thread(target=start_scheduler, daemon=True)
    t.start()
    print("✅ 스케줄러 시작 (10분 주기)")

    mt = threading.Thread(target=start_mobile_server, daemon=True)
    mt.start()
    print("✅ 모바일 QR 서버 시작")

    _try_auto_ngrok()
    print(f"✅ 최종 내부망 웹/API 주소: {cfg.API_SERVER_BASE}")
    print(f"✅ 현재 QR/모바일 주소: {_effective_mobile_url() or 'ngrok 준비 중'}")

    # ngrok 모드에서 URL이 아직 없으면 여기서 내부망 기준으로 QR을 재생성하지 않는다.
    if _effective_mobile_url():
        _regenerate_qr_after_public_url_set()
    else:
        print("⏳ ngrok URL 확보 전이므로 초기 QR 재생성은 보류합니다.")

    uvicorn.run(app, host="0.0.0.0", port=cfg.SERVER_PORT, reload=False)
