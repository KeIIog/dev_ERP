# server/qr_generator.py
import qrcode
import os
import hashlib
import sys
from typing import List

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:  # Pillow는 qrcode[pil] 설치 시 일반적으로 함께 설치됨
    Image = ImageDraw = ImageFont = None

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shared.config import QR_SAVE_PATH
import shared.config as _cfg



def _label_text_for_item(item) -> str:
    """QR 이미지 하단에 표시할 품목명 + 도번/규격."""
    name = str(getattr(item, "item_name", "") or "").strip()
    spec = str(getattr(item, "spec", "") or "").strip()
    if name and spec:
        return f"{name}\n{spec}"
    return name or spec


def _font_candidates(bold: bool = False) -> List[str]:
    names = [
        "C:/Windows/Fonts/malgunbd.ttf" if bold else "C:/Windows/Fonts/malgun.ttf",
        "C:/Windows/Fonts/NanumGothicBold.ttf" if bold else "C:/Windows/Fonts/NanumGothic.ttf",
        "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf" if bold else "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    return [x for x in names if x]


def _load_label_font(size: int, bold: bool = False):
    if ImageFont is None:
        return None
    for fp in _font_candidates(bold):
        try:
            if fp and os.path.exists(fp):
                return ImageFont.truetype(fp, size)
        except Exception:
            pass
    try:
        return ImageFont.load_default()
    except Exception:
        return None


def _text_width(draw, text: str, font) -> int:
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        return int(bbox[2] - bbox[0])
    except Exception:
        try:
            return int(draw.textlength(text, font=font))
        except Exception:
            return len(str(text)) * 10


def _text_height(draw, text: str, font) -> int:
    try:
        bbox = draw.textbbox((0, 0), text or "가", font=font)
        return int(bbox[3] - bbox[1])
    except Exception:
        return 18


def _wrap_label(draw, text: str, font, max_width: int, max_lines: int = 2) -> List[str]:
    """한글 품목명도 깨지지 않도록 글자 단위로 최대 2줄까지 줄바꿈."""
    text = " ".join(str(text or "").split())
    if not text:
        return []
    lines: List[str] = []
    cur = ""
    for ch in text:
        test = cur + ch
        if cur and _text_width(draw, test, font) > max_width:
            lines.append(cur.rstrip())
            cur = ch.lstrip()
            if len(lines) >= max_lines:
                break
        else:
            cur = test
    if len(lines) < max_lines and cur:
        lines.append(cur.rstrip())
    # 너무 긴 마지막 줄은 말줄임 처리
    if len(lines) > max_lines:
        lines = lines[:max_lines]
    if lines:
        last = lines[-1]
        if _text_width(draw, last, font) > max_width:
            while last and _text_width(draw, last + "…", font) > max_width:
                last = last[:-1]
            lines[-1] = (last + "…") if last else "…"
        elif len("".join(lines)) < len(text.replace(" ", "")) and not lines[-1].endswith("…"):
            last = lines[-1]
            while last and _text_width(draw, last + "…", font) > max_width:
                last = last[:-1]
            lines[-1] = (last + "…") if last else "…"
    return [ln for ln in lines if ln]


def _compose_qr_with_item_name(qr_img, item_name: str):
    """QR 코드 이미지 아래에 품명과 도번/규격 라벨을 합성한다."""
    if not item_name or Image is None or ImageDraw is None:
        return qr_img
    try:
        img = qr_img.convert("RGB") if hasattr(qr_img, "convert") else qr_img
        width, height = img.size
        tmp = Image.new("RGB", (width, height), "white")
        draw = ImageDraw.Draw(tmp)

        raw_lines = [ln.strip() for ln in str(item_name or "").splitlines() if ln.strip()]
        if not raw_lines:
            raw_lines = [" ".join(str(item_name or "").split())]
        max_width = max(80, width - 24)
        best_font = None
        best_lines: List[str] = []
        # 품명 1줄 + 도번/규격 1줄이 기본이며, 너무 길면 각 줄 끝을 말줄임 처리한다.
        for size in range(22, 10, -1):
            font = _load_label_font(size, bold=True)
            lines: List[str] = []
            for raw in raw_lines[:3]:
                wrapped = _wrap_label(draw, raw, font, max_width=max_width, max_lines=1)
                lines.extend(wrapped or [])
            if lines and len(lines) <= 3 and all(_text_width(draw, line, font) <= max_width for line in lines):
                best_font = font
                best_lines = lines
                break
        if not best_font:
            best_font = _load_label_font(12, bold=True)
            best_lines = []
            for raw in raw_lines[:3]:
                best_lines.extend(_wrap_label(draw, raw, best_font, max_width=max_width, max_lines=1) or [])

        if not best_lines:
            return img

        line_h = max(16, _text_height(draw, "가", best_font) + 6)
        top_gap = 8
        bottom_gap = 10
        label_h = top_gap + line_h * len(best_lines) + bottom_gap
        canvas = Image.new("RGB", (width, height + label_h), "white")
        canvas.paste(img, (0, 0))
        draw = ImageDraw.Draw(canvas)
        y = height + top_gap
        for line in best_lines:
            tw = _text_width(draw, line, best_font)
            draw.text(((width - tw) / 2, y), line, fill="black", font=best_font)
            y += line_h
        return canvas
    except Exception:
        # 라벨 합성 실패 시 기존 QR 생성은 막지 않는다.
        return qr_img

def ensure_qr_image_has_item_name(path: str, item) -> bool:
    """기존 QR 이미지에도 품명 + 도번/규격 라벨을 저장 반영한다.

    기존 이미지가 품명만 포함한 구버전 라벨이면, 상단 QR 정사각 영역만 잘라 새 라벨로 다시 저장한다.
    """
    item_name = _label_text_for_item(item)
    if not path or not item_name or Image is None or not os.path.exists(path):
        return False
    try:
        img = Image.open(path).convert("RGB")
        width, height = img.size
        # 이미 라벨이 붙은 이미지는 상단 QR 정사각 영역을 기준으로 다시 합성하여
        # 품명만 있던 과거 QR도 도번/규격이 포함된 최신 상태로 저장한다.
        base_img = img.crop((0, 0, width, min(width, height))) if height > width + 24 else img
        labeled = _compose_qr_with_item_name(base_img, item_name)
        if labeled:
            labeled.save(path)
            return True
    except Exception:
        return False
    return False


def _load_ngrok_settings() -> dict:
    try:
        import json
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        candidates = [
            os.path.join(base_dir, "client", "settings.json"),
            os.path.join(os.getcwd(), "client", "settings.json"),
            os.path.join(os.getcwd(), "_internal", "client", "settings.json"),
        ]
        for path in candidates:
            if path and os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
    except Exception:
        pass
    return {}


def _setting_bool(settings: dict, key: str, default: bool = False) -> bool:
    val = settings.get(key, default)
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() in ("1", "true", "yes", "y", "on")


def _normalize_base_url(base: str, default_scheme: str = "http") -> str:
    base = str(base or "").strip().rstrip("/")
    if base and not base.startswith(("http://", "https://")):
        base = f"{default_scheme}://" + base
    return base.rstrip("/")


def _get_lan_mobile_base() -> str:
    base = getattr(_cfg, "LOCAL_MOBILE_BASE", "") or "http://127.0.0.1:8001"
    return _normalize_base_url(base, "http")


LEGACY_QR_PUBLIC_BASE = "https://garment-dig-duress.ngrok-free.dev"


def _legacy_public_base_from_settings(settings: dict) -> str:
    raw = (
        os.getenv("DEVERP_PUBLIC_MOBILE_BASE", "")
        or os.getenv("DEVERP_NGROK_DOMAIN", "")
        or settings.get("public_mobile_url", "")
        or settings.get("ngrok_domain", "")
        or LEGACY_QR_PUBLIC_BASE
    )
    return _normalize_base_url(raw, "https")


def _get_mobile_base() -> str:
    """QR 이미지에 들어갈 모바일 주소를 결정한다.

    이미 협력사에 배포된 QR은 기존 ngrok 도메인을 포함하고 있으므로
    기본값은 내부망이 아니라 기존 ngrok 고정 주소를 사용한다.
    내부망 QR을 새로 만들 때만 client/settings.json에서 qr_url_mode='lan' 또는
    qr_prefer_lan=true로 설정한다.
    """
    settings = _load_ngrok_settings()
    # env가 있으면 최우선. env가 없으면 이전 LAN 패치에서 남은 qr_url_mode='lan'은 무시하고 ngrok을 기본값으로 되돌린다.
    env_mode = str(os.getenv("DEVERP_QR_URL_MODE", "")).strip().lower()
    mode = env_mode or str(settings.get("qr_url_mode", "") or "").strip().lower()
    prefer_lan = _setting_bool(settings, "qr_prefer_lan", False)
    if env_mode in ("lan", "local", "internal"):
        prefer_lan = True
    elif mode in ("ngrok", "public", "external"):
        prefer_lan = False
    elif mode in ("lan", "local", "internal"):
        # 기존 배포 QR 보호를 위해 설정 파일에 남은 LAN 모드는 기본적으로 무시한다.
        prefer_lan = False

    lan = _get_lan_mobile_base()
    if prefer_lan:
        _cfg.PUBLIC_MOBILE_BASE = lan
        _cfg.MOBILE_BASE = lan
        return lan

    use_ngrok = bool(settings.get("use_ngrok", True))
    if use_ngrok:
        # 기존 배포 QR과 같은 고정 주소를 QR 생성 기준으로 먼저 사용한다.
        manual = _legacy_public_base_from_settings(settings)
        if manual and "ngrok" in manual.lower():
            _cfg.PUBLIC_MOBILE_BASE = manual
            _cfg.MOBILE_BASE = manual
            return manual

        try:
            from server.ngrok_tunnel import get_effective_tunnel_url, is_starting
            ngrok_url = get_effective_tunnel_url(timeout=0.8, allow_last_known=True)
            if ngrok_url:
                _cfg.PUBLIC_MOBILE_BASE = ngrok_url.rstrip("/")
                _cfg.MOBILE_BASE = _cfg.PUBLIC_MOBILE_BASE
                return _cfg.PUBLIC_MOBILE_BASE
            if is_starting():
                raise RuntimeError("ngrok URL이 아직 준비 중입니다. 설정 화면에서 ngrok 주소가 표시된 뒤 다시 시도하세요.")
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"ngrok URL 확인 실패: {e}")

        raise RuntimeError("ngrok URL이 아직 준비되지 않았습니다. 설정 화면에서 ngrok 시작/갱신을 먼저 실행하세요.")

    base = (
        getattr(_cfg, "PUBLIC_MOBILE_BASE", "")
        or getattr(_cfg, "MOBILE_BASE", "")
        or lan
    )
    return _normalize_base_url(base, "http")


def _make_qr_value(item, order) -> str:
    if getattr(item, "qr_code", None):
        return str(item.qr_code).strip().upper()

    unique = f"{getattr(order, 'order_no', '')}_{getattr(item, 'id', '')}_{getattr(item, 'item_name', '')}"
    return hashlib.md5(unique.encode("utf-8")).hexdigest()[:12].upper()


def generate_qr_for_item(item, order, db) -> str:
    os.makedirs(QR_SAVE_PATH, exist_ok=True)

    qr_value = _make_qr_value(item, order)
    base = _get_mobile_base()

    url = f"{base}/m/{qr_value}"

    qr = qrcode.QRCode(
        version=1,
        box_size=8,
        border=2,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
    )
    qr.add_data(url)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    img = _compose_qr_with_item_name(img, _label_text_for_item(item))

    order_no = getattr(order, "order_no", "ORDER") or "ORDER"
    safe_order_no = "".join(c for c in str(order_no) if c.isalnum() or c in ("-", "_"))
    path = os.path.join(QR_SAVE_PATH, f"QR_{safe_order_no}_{qr_value}.png")
    img.save(path)

    item.qr_code = qr_value
    item.qr_code_path = path
    db.add(item)
    db.commit()
    db.refresh(item)
    return path
