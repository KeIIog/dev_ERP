# -*- mode: python ; coding: utf-8 -*-
# DevERP Server PyInstaller spec - v2.2.5 cleaned build
# - no UPX
# - skip missing optional data files instead of failing silently
# - keep explicit hidden imports for FastAPI/Uvicorn/Selenium/ngrok/reportlab stack
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules


def _safe_collect(pkg):
    try:
        print(f"[SPEC] collect_submodules: {pkg}")
        return collect_submodules(pkg)
    except Exception as e:
        print(f"[SPEC][WARN] collect_submodules failed: {pkg}: {e}")
        return []


def _data(src, dst):
    p = Path(src)
    if p.exists():
        print(f"[SPEC] add-data: {src} -> {dst}")
        return [(src, dst)]
    print(f"[SPEC][WARN] missing data skipped: {src}")
    return []


hiddenimports = [
    'passlib.handlers.bcrypt',
    'bcrypt',
    'jose',
    'jose.jwt',
    'multipart',
    'multipart.multipart',
    'openpyxl',
    'xlrd',
    'docx',
    'pdfminer.high_level',
    'pdfminer',
    'pdfplumber',
    'client.estimate_parser',
    'PIL',
    'PIL.Image',
    'qrcode',
    'schedule',
    'requests',
    'pyngrok',
    'pyngrok.ngrok',
    'pyngrok.conf',
    'pyngrok.installer',
    'selenium',
    'selenium.webdriver',
    'selenium.webdriver.chrome.options',
    'selenium.webdriver.chrome.service',
    'selenium.webdriver.common.by',
    'selenium.webdriver.support.ui',
    'selenium.webdriver.support.expected_conditions',
    'selenium.webdriver.common.keys',
    'webdriver_manager',
    'webdriver_manager.chrome',
    'bs4',
    'reportlab',
    'reportlab.pdfgen.canvas',
    'reportlab.lib.pagesizes',
    'reportlab.lib.units',
    'reportlab.lib.colors',
    'reportlab.pdfbase.pdfmetrics',
    'reportlab.pdfbase.ttfonts',
    'pythoncom',
    'pywintypes',
    'win32com',
    'win32com.client',
]


# FastAPI/Uvicorn/SQLAlchemy and auth stacks use dynamic imports. Keep these collected.
for _pkg in ['fastapi', 'starlette', 'uvicorn', 'sqlalchemy', 'passlib', 'jose']:
    hiddenimports += _safe_collect(_pkg)

# Selenium/ngrok/webdriver-manager are mostly used by client-agent files and server fallback.
# Collecting entire packages can be slow on some PCs, so keep them explicit above.

_datas = []
_datas += _data('server', 'server')
_datas += _data('shared', 'shared')
_datas += _data('database', 'database')
_datas += _data('client\\settings.json', 'client')
_datas += _data('client_web_agent.py', '.')
_datas += _data('start_client_agent.bat', '.')
_datas += _data('run_client_agent_hidden.bat', '.')
_datas += _data('run_client_agent_hidden.ps1', '.')
_datas += _data('run_client_agent_hidden.vbs', '.')
_datas += _data('run_client_agent_console.bat', '.')
_datas += _data('register_client_agent_startup.ps1', '.')
_datas += _data('stop_client_agent.bat', '.')
_datas += _data('remove_client_agent_startup.bat', '.')
_datas += _data('check_client_agent.bat', '.')
_datas += _data('requirements_client_agent.txt', '.')
_datas += _data('bundled_client_agent\\DevERP_Client_Agent', 'bundled_client_agent\\DevERP_Client_Agent')

block_cipher = None

a = Analysis(
    ['server\\main_server.py'],
    pathex=[],
    binaries=[],
    datas=_datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PySide6', 'PyQt5', 'tkinter', 'matplotlib', 'numpy', 'pandas'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='DevERP_Server',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='DevERP_Server',
)
