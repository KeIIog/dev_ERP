# server/mobile_qr_app.py
# DevERP 모바일 QR 입고 화면
# QR 조회는 반드시 query 방식(/scan?qr=...)을 우선 사용한다.

import os
import sys
import re
import requests
import uvicorn
from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.responses import JSONResponse, Response
from urllib.parse import unquote

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shared.config import SERVER_HOST, MOBILE_PORT

MOBILE_APP = FastAPI(title="DevERP Mobile QR")


def _extract_qr(raw: str) -> str:
    val = unquote(str(raw or "").strip())
    if '%' in val:
        try:
            val = unquote(val)
        except Exception:
            pass
    if not val:
        return ""
    m = re.search(r"(?:^|[?&])qr=([^&\s]+)", val, re.I)
    if m:
        val = unquote(m.group(1))
    elif "QR:" in val.upper() or "QR：" in val.upper():
        m = re.search(r"QR\s*[:：]\s*([A-Za-z0-9_-]+)", val, re.I)
        if m:
            val = m.group(1)
    elif "/m/" in val:
        val = val.rstrip('/').split('/m/')[-1]
    elif "/item/" in val:
        val = val.rstrip('/').split('/item/')[-1]
    elif "/scan/" in val:
        val = val.rstrip('/').split('/scan/')[-1]
    elif '/' in val and val.lower().startswith(('http://','https://')):
        val = val.rstrip('/').split('/')[-1]
    if '&' in val:
        val = val.split('&', 1)[0]
    if '?' in val:
        val = val.split('?', 1)[0]
    val = re.sub(r"[^A-Za-z0-9_-]", "", val.strip())
    return val.upper()


def _json_response(resp):
    try:
        body = resp.json()
    except Exception:
        body = {"success": False, "detail": resp.text or "server error"}
    return JSONResponse(content=body, status_code=resp.status_code)


ITEM_PAGE = r'''<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>DevERP 입고처리</title>
<style>
*{box-sizing:border-box;margin:0;padding:0} body{font-family:Arial,'Noto Sans KR',sans-serif;background:#f5f5f7;color:#1d1d1f;min-height:100vh}.header{background:#1c1c1e;color:white;padding:14px 16px;display:flex;align-items:center;justify-content:space-between}.header h1{font-size:16px}.name-chip{background:#2c2c2e;border-radius:18px;padding:6px 10px;font-size:12px;cursor:pointer}.card{margin:14px;background:white;border-radius:16px;padding:18px;box-shadow:0 1px 2px rgba(0,0,0,.05)}.row{display:flex;justify-content:space-between;gap:12px;border-bottom:1px solid #eee;padding:8px 0}.row:last-child{border-bottom:0}.lbl{color:#6e6e73;font-size:12px}.val{font-size:13px;font-weight:700;text-align:right}.badge{display:inline-block;border-radius:20px;padding:4px 10px;font-size:12px;font-weight:700}.red{background:#fff0ef;color:#ff3b30}.orange{background:#fff6ec;color:#ff9500}.blue{background:#eaf4ff;color:#0071e3}.green{background:#e8faf0;color:#34c759}.btn{width:100%;border:0;border-radius:14px;background:#34c759;color:white;font-size:16px;font-weight:800;padding:15px;margin-top:12px}.btn:disabled{background:#aaa}.subbtn{border:0;border-radius:10px;padding:11px;background:#eaf4ff;color:#0071e3;font-weight:700}.grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:10px 0}.warn{background:#fff6ec;border:1px solid #ffd5a0;border-radius:12px;padding:10px;font-size:13px;color:#ff6b00;line-height:1.45}.photos{display:flex;gap:8px;overflow-x:auto;margin-top:8px}.thumb{position:relative;flex:0 0 74px;height:74px;border-radius:10px;overflow:hidden;background:#eee}.thumb img{width:100%;height:100%;object-fit:cover}.thumb button{position:absolute;top:2px;right:2px;border:0;border-radius:50%;background:rgba(0,0,0,.7);color:white;width:22px;height:22px}.overlay{position:fixed;inset:0;background:rgba(0,0,0,.75);display:none;align-items:center;justify-content:center;padding:20px;z-index:99}.modal{background:white;border-radius:20px;padding:22px;width:100%;max-width:340px}.modal input{width:100%;border:2px solid #0071e3;border-radius:12px;padding:13px;font-size:16px;margin:14px 0}.toast{position:fixed;left:50%;bottom:26px;transform:translateX(-50%);background:#1c1c1e;color:white;border-radius:20px;padding:10px 18px;opacity:0;transition:.2s;z-index:100;white-space:nowrap}.toast.show{opacity:1}.err{color:#ff3b30}.small{font-size:11px;color:#8e8e93;word-break:break-all;margin-top:8px}input[type=file]{display:none}
</style>
</head>
<body>
<div class="header"><h1>📦 DevERP 입고처리</h1><div class="name-chip" onclick="openNameModal()">처리자: <b id="headerName">미설정</b></div></div>
<div id="content"><div class="card">품목 정보를 불러오는 중...</div></div>
<div class="overlay" id="nameOverlay"><div class="modal"><h2>처리자 이름 입력</h2><input id="nameInput" placeholder="예: 고성훈" onkeydown="if(event.key==='Enter')saveName()"><button class="btn" onclick="saveName()">저장</button></div></div>
<div class="toast" id="toast"></div>
<input type="file" id="camera" accept="image/*" capture="environment" onchange="addPhotos(this)">
<input type="file" id="uploader" accept="image/*" multiple onchange="addPhotos(this)">
<script>
const NAME_KEY='deverp_user_name';
function extractQR(){
  const p=new URLSearchParams(location.search);
  let q=p.get('qr')||p.get('qr_code')||'';
  if(!q && location.pathname.startsWith('/m/')) q=decodeURIComponent(location.pathname.split('/m/')[1]||'');
  if(!q && location.pathname.startsWith('/scan/')) q=decodeURIComponent(location.pathname.split('/scan/')[1]||'');
  q=(q||'').trim();
  if(q.includes('qr=')){ try{ q=new URL(q).searchParams.get('qr') || q; }catch(e){ q=(q.match(/[?&]qr=([^&]+)/)||[])[1]||q; } }
  q=q.split('&')[0].split('?')[0].replace(/[^A-Za-z0-9_-]/g,'').toUpperCase();
  return q;
}
const ACTIVE_QR=extractQR();
let itemData=null, photoFiles=[], savedName=localStorage.getItem(NAME_KEY)||'';
function toast(m,ms=2400){const t=document.getElementById('toast');t.textContent=m;t.classList.add('show');setTimeout(()=>t.classList.remove('show'),ms)}
function loadName(){document.getElementById('headerName').textContent=savedName||'미설정';document.getElementById('nameInput').value=savedName||'';}
function openNameModal(){document.getElementById('nameOverlay').style.display='flex';setTimeout(()=>document.getElementById('nameInput').focus(),100)}
function saveName(){let v=document.getElementById('nameInput').value.trim();if(!v){toast('이름을 입력하세요');return;} savedName=v;localStorage.setItem(NAME_KEY,v);document.getElementById('headerName').textContent=v;document.getElementById('nameOverlay').style.display='none';renderAction();}
async function loadItem(){
  if(!ACTIVE_QR){showError('QR 코드 정보가 없습니다','현재 주소에 qr 값이 없습니다.');return;}
  try{
    const r=await fetch(`/mobile_api/inventory/scan?qr=${encodeURIComponent(ACTIVE_QR)}&_=${Date.now()}`,{cache:'no-store'});
    const data=await r.json().catch(()=>({detail:'응답 JSON 파싱 실패'}));
    if(!r.ok) throw new Error(data.detail||data.message||'품목을 찾을 수 없습니다');
    itemData=data; if(!savedName) openNameModal(); renderItem();
  }catch(e){showError('품목을 찾을 수 없습니다',`${e.message}<br><div class="small">스캔 QR: ${ACTIVE_QR}</div>`)}
}
function renderItem(){const d=itemData; const col={'미입고':'red','구매팀입고':'orange','품질검수':'blue','생산팀입고':'green','제조입고':'green','완료':'green'}[d.stage]||'blue';document.getElementById('content').innerHTML=`<div class="card"><h3>품목 정보</h3><div class="row"><span class="lbl">품명</span><span class="val">${d.item_name||'-'}</span></div><div class="row"><span class="lbl">규격</span><span class="val">${d.spec||'-'}</span></div><div class="row"><span class="lbl">수량</span><span class="val">${d.quantity||0} ${d.unit||''}</span></div><div class="row"><span class="lbl">업체</span><span class="val">${d.vendor||'-'}</span></div><div class="row"><span class="lbl">현재 단계</span><span class="badge ${col}">${d.stage}</span></div><div class="row"><span class="lbl">QR</span><span class="val">${ACTIVE_QR}</span></div></div><div id="action"></div>`;renderAction();}
function renderAction(){const a=document.getElementById('action'); if(!a||!itemData)return; if(['생산팀입고','제조입고','완료'].includes(itemData.stage)){a.innerHTML='<div class="card"><h3>✅ 처리 완료</h3><p>이 품목은 입고 단계가 완료되었습니다.</p></div>';return;} const roleMap={'미입고':['purchase','구매팀 입고'],'구매팀입고':['quality','품질검수/출고'],'품질검수':['manufacture','생산팀 입고']}; const r=roleMap[itemData.stage]||['purchase','입고 처리']; a.innerHTML=`<div class="card"><h3>입고 처리</h3><div class="warn">사진은 여러 장 업로드 가능합니다. 카메라는 1장씩 추가, 파일 선택은 여러 장 선택 가능합니다.</div><div class="grid"><button class="subbtn" onclick="document.getElementById('camera').click()">📷 촬영 추가</button><button class="subbtn" onclick="document.getElementById('uploader').click()">🖼 여러 장 선택</button></div><div class="photos" id="photos"></div><button class="btn" id="submitBtn" onclick="submitReceipt('${r[0]}')">✅ ${r[1]}</button></div>`;renderPhotos();}
function addPhotos(inp){const fs=Array.from(inp.files||[]).filter(f=>f.type.startsWith('image/'));photoFiles=photoFiles.concat(fs);inp.value='';renderPhotos();}
function removePhoto(i){photoFiles.splice(i,1);renderPhotos();}
function renderPhotos(){const el=document.getElementById('photos');if(!el)return;el.innerHTML='';photoFiles.forEach((f,i)=>{const box=document.createElement('div');box.className='thumb';box.innerHTML='<img><button>×</button>';box.querySelector('button').onclick=()=>removePhoto(i);el.appendChild(box);const rd=new FileReader();rd.onload=e=>box.querySelector('img').src=e.target.result;rd.readAsDataURL(f);});}
async function submitReceipt(role){if(!savedName){openNameModal();toast('처리자 이름을 입력하세요');return;} const btn=document.getElementById('submitBtn');btn.disabled=true;btn.textContent='처리 중...';try{let r;if(photoFiles.length){const fd=new FormData();fd.append('qr_code',ACTIVE_QR);fd.append('scanned_by',savedName);photoFiles.forEach(f=>fd.append('photos',f));r=await fetch('/mobile_api/inventory/scan_with_photo',{method:'POST',body:fd});}else{r=await fetch('/mobile_api/inventory/scan',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({qr_code:ACTIVE_QR,role,scanned_by:savedName})});}const data=await r.json().catch(()=>({detail:'응답 오류'}));if(r.ok&&data.success){document.getElementById('content').innerHTML=`<div class="card"><h2>✅ 입고 처리 완료</h2><p>${data.message||''}</p><p class="small">처리자: ${savedName}</p></div>`;}else{throw new Error(data.message||data.detail||'처리 실패');}}catch(e){btn.disabled=false;btn.textContent='✅ 입고 처리';alert('입고 처리 실패: '+e.message);}}
function showError(t,m){document.getElementById('content').innerHTML=`<div class="card"><h2 class="err">❌ ${t}</h2><p>${m}</p><div class="small">현재 주소: ${location.href}</div></div>`;}
window.onload=()=>{loadName();loadItem();};
</script></body></html>'''


@MOBILE_APP.get("/item")
async def item_page():
    return Response(content=ITEM_PAGE, media_type="text/html; charset=utf-8", headers={"ngrok-skip-browser-warning": "true", "Cache-Control": "no-store"})

@MOBILE_APP.get("/scan")
async def scan_page():
    return Response(content=ITEM_PAGE, media_type="text/html; charset=utf-8", headers={"ngrok-skip-browser-warning": "true", "Cache-Control": "no-store"})

@MOBILE_APP.get("/m/{qr_code:path}")
async def m_page(qr_code: str):
    return Response(content=ITEM_PAGE, media_type="text/html; charset=utf-8", headers={"ngrok-skip-browser-warning": "true", "Cache-Control": "no-store"})

@MOBILE_APP.get("/mobile_api/inventory/scan")
async def proxy_scan_get_query(qr: str = "", qr_code: str = ""):
    code = _extract_qr(qr or qr_code)
    resp = requests.get("http://127.0.0.1:8000/api/inventory/scan", params={"qr": code}, timeout=15)
    return _json_response(resp)


@MOBILE_APP.get("/mobile_api/inventory/scan")
async def proxy_scan_get_query(qr: str = "", qr_code: str = ""):
    q = qr or qr_code
    resp = requests.get(
        "http://127.0.0.1:8000/api/inventory/scan",
        params={"qr": q},
        timeout=15,
    )
    try:
        body = resp.json()
    except Exception:
        body = {"detail": resp.text or "server error"}
    return JSONResponse(content=body, status_code=resp.status_code)


@MOBILE_APP.get("/mobile_api/inventory/scan/{qr_code:path}")
async def proxy_scan_get(qr_code: str):
    resp = requests.get(
        "http://127.0.0.1:8000/api/inventory/scan",
        params={"qr": qr_code},
        timeout=15,
    )
    try:
        body = resp.json()
    except Exception:
        body = {"detail": resp.text or "server error"}
    return JSONResponse(content=body, status_code=resp.status_code)

@MOBILE_APP.post("/mobile_api/inventory/scan")
async def proxy_scan_post(request: Request):
    payload = await request.json()
    payload["qr_code"] = _extract_qr(payload.get("qr_code", ""))
    resp = requests.post("http://127.0.0.1:8000/api/inventory/scan", json=payload, timeout=30)
    return _json_response(resp)

@MOBILE_APP.post("/mobile_api/inventory/scan_with_photo")
async def proxy_scan_with_photo(qr_code: str = Form(...), scanned_by: str = Form(...), photos: list[UploadFile] = File(default=[]), photo: UploadFile | None = File(default=None)):
    files = []
    upload_list = []
    if photos:
        upload_list.extend([p for p in photos if p])
    if photo:
        upload_list.append(photo)
    for up in upload_list:
        files.append(("photos", (up.filename or "photo.jpg", await up.read(), up.content_type or "application/octet-stream")))
    data = {"qr_code": _extract_qr(qr_code), "scanned_by": scanned_by}
    resp = requests.post("http://127.0.0.1:8000/api/inventory/scan_with_photo", data=data, files=files, timeout=60)
    return _json_response(resp)

@MOBILE_APP.get("/")
async def root():
    return {"item_url": f"http://{SERVER_HOST}:{MOBILE_PORT}/item?qr=QR코드값"}

def start_mobile_server():
    uvicorn.run(MOBILE_APP, host="0.0.0.0", port=MOBILE_PORT)

if __name__ == "__main__":
    start_mobile_server()
