# server/routers/mobile.py
#
# 모바일 웹앱 서빙 + QR URL 라우터
# QR 코드 안에 URL: http://서버IP:8000/m/QR코드값
# 스마트폰으로 QR 스캔 → 브라우저에서 바로 열림 → 로그인 → 처리
#
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
import os

router = APIRouter()

# HTML 파일 경로
_TEMPLATE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates", "mobile.html")


def _get_html() -> str:
    with open(_TEMPLATE_PATH, encoding="utf-8") as f:
        return f.read()


@router.get("/m", response_class=HTMLResponse)
@router.get("/m/", response_class=HTMLResponse)
async def mobile_home():
    """모바일 앱 메인 페이지"""
    return HTMLResponse(_get_html())


@router.get("/m/{qr_code:path}", response_class=HTMLResponse)
async def mobile_scan(qr_code: str):
    """
    QR 코드 스캔 시 바로 이 URL로 접속됨
    예: http://192.168.0.100:8000/m/QR_ITEM_A1B2C3
    → HTML 페이지 로딩 후 JS에서 qr_code 값 추출하여 자동 처리
    """
    return HTMLResponse(_get_html())
