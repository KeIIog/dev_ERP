# server/purchase_order_generator.py
# 발주서 PDF 자동 생성 - 이노로보틱스 발주서 양식 기준
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import os, qrcode
from datetime import datetime


def _register_fonts():
    regular = None; bold = None
    for fp in [
        'C:/Windows/Fonts/malgun.ttf',
        'C:/Windows/Fonts/malgunbd.ttf',
        '/usr/share/fonts/truetype/nanum/NanumGothic.ttf',
        '/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf',
    ]:
        if os.path.exists(fp):
            if 'bd' in fp.lower() or 'bold' in fp.lower(): bold = fp
            else: regular = fp
    try:
        if regular: pdfmetrics.registerFont(TTFont('Kor', regular))
        if bold: pdfmetrics.registerFont(TTFont('KorB', bold))
        return ('Kor' if regular else 'Helvetica'), ('KorB' if bold else ('Kor' if regular else 'Helvetica-Bold'))
    except Exception:
        return 'Helvetica', 'Helvetica-Bold'


def _num(v):
    try: return int(float(v or 0))
    except Exception: return 0


def _date_ko(s):
    try:
        d = datetime.strptime(str(s)[:10], '%Y-%m-%d')
    except Exception:
        try: d = datetime.strptime(str(s)[:10].replace('/', '-'), '%Y-%m-%d')
        except Exception: d = datetime.now()
    return f'{d.year}년  {d.month}월  {d.day}일'





def _clean_spec_unit_values(spec, unit):
    """발주서 출력 기준: 단위 칼럼에 잘못 들어온 규격/도번은 규격으로 보존하고 단위는 항상 EA로 통일."""
    known_units = {'EA','EACH','개','PCS','PC','SET','SETS','BOX','ROLL','M','MM','CM','KG','G','L','ML','식','본','매','조','대'}
    spec_txt = str(spec or '').strip()
    unit_txt = str(unit or '').strip()
    if unit_txt and unit_txt.upper() != 'EA':
        token = unit_txt.upper().replace('.', '').replace(' ', '')
        if token not in known_units and unit_txt not in spec_txt:
            spec_txt = (spec_txt + ' ' + unit_txt).strip() if spec_txt else unit_txt
    return spec_txt, 'EA'


def _normalize_order_item(item):
    d = dict(item or {})
    d['spec'], d['unit'] = _clean_spec_unit_values(d.get('spec', ''), d.get('unit', ''))
    return d

def _asset_path(name: str) -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, 'assets', name)


def _draw_img(c, path, x, y, w, h):
    try:
        if path and os.path.exists(path):
            c.drawImage(ImageReader(path), x, y, width=w, height=h, mask='auto', preserveAspectRatio=True, anchor='c')
            return True
    except Exception:
        pass
    return False


def _fit_text(c, text, x, y, max_w, font, size, min_size=5.5, align='left'):
    text = '' if text is None else str(text)
    cur = size
    while cur > min_size and c.stringWidth(text, font, cur) > max_w:
        cur -= 0.4
    c.setFont(font, cur)
    if align == 'center': c.drawCentredString(x + max_w/2, y, text)
    elif align == 'right': c.drawRightString(x + max_w, y, text)
    else: c.drawString(x, y, text)


def generate_purchase_order_pdf(order_data: dict, output_path: str) -> str:
    """발주서 PDF 생성.

    기존에는 품목 표를 1페이지 15행 고정으로만 출력해서 16개 이상 품목이
    잘렸습니다. 이 버전은 품목 수에 맞춰 PDF 내부에 페이지를 추가하고,
    마지막 페이지에만 소계/부가세/총합계 및 하단 조건을 출력합니다.
    """
    FONT_R, FONT_B = _register_fonts()
    W, H = A4
    c = canvas.Canvas(output_path, pagesize=A4)

    def setf(b=False, size=9): c.setFont(FONT_B if b else FONT_R, size)
    def txt(x,y,s,b=False,size=9,align='left'):
        setf(b,size); s='' if s is None else str(s)
        if align=='center': c.drawCentredString(x,y,s)
        elif align=='right': c.drawRightString(x,y,s)
        else: c.drawString(x,y,s)
    def line(x1,y1,x2,y2,w=0.7): c.setStrokeColor(colors.black); c.setLineWidth(w); c.line(x1,y1,x2,y2)
    def rect(x,y,w,h,fill=None,lw=0.7):
        c.setStrokeColor(colors.black); c.setLineWidth(lw)
        if fill: c.setFillColor(fill); c.rect(x,y,w,h,fill=1,stroke=1); c.setFillColor(colors.black)
        else: c.rect(x,y,w,h,fill=0,stroke=1)

    L=15*mm; R=W-15*mm; TOP=H-12*mm
    blue=colors.Color(0.74,0.91,0.93); peach=colors.Color(1.0,0.86,0.72)

    vendor=order_data.get('vendor_name','')
    contact=order_data.get('vendor_contact','') or order_data.get('contact','')
    v_phone=order_data.get('vendor_phone','')
    v_fax=order_data.get('vendor_fax','')
    order_no=order_data.get('order_no','')
    sap_no=order_data.get('sap_no','') or ''
    request_no=order_data.get('request_no','')
    project_code=order_data.get('project_code','')
    order_date=order_data.get('order_date') or datetime.now().strftime('%Y-%m-%d')

    headers=['No.','품명','규격','단위','납기일','발주수량','단가','금액']
    widths=[12,38,38,12,22,18,22,28]
    scale=(R-L)/sum(widths); widths=[w*scale for w in widths]
    rowh=7*mm
    ITEMS_PER_PAGE = 15

    items=[_normalize_order_item(it) for it in (order_data.get('items') or [])]
    # 품목이 0개여도 발주서 기본 양식 1페이지는 생성한다.
    page_count = max(1, (len(items) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)

    # 총계는 첫 페이지 15개가 아니라 전체 품목 기준으로 계산한다.
    total_qty = 0
    total_amt = 0
    for it in items:
        qty=_num(it.get('quantity'))
        price=_num(it.get('unit_price'))
        total_qty += qty
        total_amt += qty * price

    def draw_page_header(page_no: int) -> float:
        """페이지 상단 고정 영역 및 품목 표 헤더를 그리고, 본문 시작 y를 반환."""
        # 로고/제목: 제공된 발주서 PDF에서 추출한 원본 이미지 사용
        logo = _asset_path('order_logo.png')
        stamp = _asset_path('order_stamp.png')
        if not _draw_img(c, logo, L+2*mm, TOP-16*mm, 22*mm, 20*mm):
            txt(L+8*mm, TOP-7*mm, 'INNO', True, 14, 'center')
            txt(L+8*mm, TOP-12*mm, 'ROBOTICS', False, 7, 'center')
        txt(W/2, TOP-5*mm, '발   주   서', True, 20, 'center')
        line(W/2-35*mm, TOP-8*mm, W/2+35*mm, TOP-8*mm, 1.8)
        if page_count > 1:
            txt(R, TOP-5*mm, f'{page_no}/{page_count}', False, 7, 'right')

        y=TOP-20*mm
        txt(L, y, f'{vendor}귀중', True, 10)
        txt(L, y-6*mm, f'전화번호 : {v_phone}', True, 8)
        txt(L, y-11*mm, f'팩스번호 : {v_fax}', True, 8)
        txt(L, y-16*mm, f'{contact}귀하', True, 8)
        txt(L, y-21*mm, f'발주번호 : {order_no}', True, 8)

        x2=W/2+8*mm
        txt(x2, y, '사 업 장 : 이노로보틱스 주식회사', True, 8)
        txt(x2, y-6*mm, '대 표 자 : 이 현 철', True, 8)
        txt(x2, y-11*mm, '주    소 : 화성시 정남면 정남산단로 80', True, 8)
        txt(x2, y-16*mm, '전화번호 : 070-4848-2326', True, 8)
        txt(x2, y-21*mm, '팩스번호 : 031-376-5107', True, 8)
        # 직인: 제공된 발주서 PDF에서 추출한 원본 이미지 사용
        if not _draw_img(c, stamp, R-24*mm, y-18*mm, 22*mm, 22*mm):
            c.setStrokeColor(colors.red); c.circle(R-12*mm, y-6*mm, 9*mm, stroke=1, fill=0); c.setStrokeColor(colors.black)
            txt(R-12*mm, y-7*mm, '직인', True, 8, 'center')

        y-=29*mm
        for n in ['※ 거래명세표 컬러 직인 필수.', '※ 세금계산서 발행일(작성일자)은 거래명세표 일자와 동일 일자로 발행.', '※ 현품표 부착하여 납품 진행 요청드리며 납품 전 사전 연락바랍니다.']:
            txt(L, y, n, True, 8); y-=5*mm

        # 비고
        rect(L,y-rowh,R-L,rowh,None,1.4)
        rect(L,y-rowh,28*mm,rowh,blue,1.0)
        txt(L+14*mm,y-4.8*mm,'비  고',True,8,'center')
        remark_suffix = '' if page_count == 1 else f'  (품목 {len(items)}건 / {page_no}페이지)'
        txt(L+31*mm,y-4.8*mm,f'[{project_code}] {request_no} 납품 시 세금계산서 발행 바랍니다.{remark_suffix}',True,7)
        y-=rowh

        x=L
        for h,wid in zip(headers,widths):
            rect(x,y-rowh,wid,rowh,blue,0.8); txt(x+wid/2,y-4.7*mm,h,True,7,'center'); x+=wid
        y-=rowh
        return y

    def draw_item_row(idx: int, item: dict, y: float) -> float:
        qty=_num(item.get('quantity'))
        price=_num(item.get('unit_price'))
        amt=qty*price
        vals=[str(idx+1), item.get('item_name',''), item.get('spec',''), 'EA', item.get('due_date',''), str(qty), f'{price:,}', f'{amt:,}']
        x=L
        for ci,(val,wid) in enumerate(zip(vals,widths)):
            rect(x,y-rowh,wid,rowh,None,0.55)
            align='center' if ci in [0,3,4,5] else ('right' if ci in [6,7] else 'left')
            tx=x+wid/2 if align=='center' else (x+wid-1*mm if align=='right' else x+1*mm)
            if ci in [1,2]:
                _fit_text(c, val, x+1*mm, y-4.8*mm, max(wid-2*mm, 5*mm), FONT_R, 6.3, 4.8, 'left')
            else:
                txt(tx,y-4.8*mm,val,False,6.5,align)
            x+=wid
        return y-rowh

    def draw_blank_row(y: float) -> float:
        x=L
        for wid in widths:
            rect(x,y-rowh,wid,rowh,None,0.55); x+=wid
        return y-rowh

    def draw_footer(y: float) -> None:
        rect(L,y-rowh,R-L,rowh,peach,0.8)
        txt(L+60*mm,y-4.8*mm,'소        계',True,8,'center')
        txt(R-widths[-1]-widths[-2]+widths[-2]-1*mm,y-4.8*mm,f'{total_qty:,}',True,8,'right')
        txt(R-1*mm,y-4.8*mm,f'{total_amt:,}',True,8,'right')
        y-=rowh

        vat=int(total_amt*0.1); grand=total_amt+vat
        cols=[('공급가액 합계',f'{total_amt:,} 원'),('부가세 합계',f'{vat:,} 원'),('총 합 계',f'{grand:,} 원')]
        cw=(R-L)/3
        for i,(a,b) in enumerate(cols):
            x=L+i*cw; rect(x,y-rowh,cw,rowh,None,0.8); rect(x,y-rowh,27*mm,rowh,blue,0.8); txt(x+13.5*mm,y-4.8*mm,a,True,7,'center'); txt(x+cw-2*mm,y-4.8*mm,b,True,7,'right')
        y-=rowh

        # 하단 정보: 설계담당자 값은 기재하지 않음
        half=(R-L)/2
        fields=[
            ('납 품 장 소', order_data.get('delivery_address','경기도 화성시 정남면 정남산단로 80'), '납품 시 연락처', f"{order_data.get('receiver_name','원영상 대리')} ({order_data.get('receiver_phone','010-2724-3075')})"),
            ('설계 담당자', '', '전 달 사 항', '거래명세표 및 현품표 부착하여 납품 할 것.'),
            ('지 불 조 건', '(납품완료 후) 별도 지불', '운 반 조 건', '납품 시 사전 연락하여 장소 및 시간 확인 할 것.'),
        ]
        for lk,lv,rk,rv in fields:
            rect(L,y-rowh,half,rowh,None,0.8); rect(L,y-rowh,30*mm,rowh,blue,0.8)
            rect(L+half,y-rowh,half,rowh,None,0.8); rect(L+half,y-rowh,30*mm,rowh,blue,0.8)
            txt(L+15*mm,y-4.8*mm,lk,True,7,'center'); txt(L+32*mm,y-4.8*mm,lv,False,6.5)
            txt(L+half+15*mm,y-4.8*mm,rk,True,7,'center'); txt(L+half+32*mm,y-4.8*mm,rv,False,6.5)
            y-=rowh

        y-=3*mm
        txt(W/2,y,'위와 같이 발주하오니 계약조건을 준수하여 납품하여 주시기 바랍니다.',True,9,'center'); y-=7*mm
        txt(W/2,y,_date_ko(order_date),True,10,'center'); y-=6*mm
        orderer_txt = f"발주자명: {order_data.get('orderer_name','')}"
        if order_data.get('orderer_phone'):
            orderer_txt += f" ({order_data.get('orderer_phone')})"
        txt(W/2,y,orderer_txt,True,8,'center'); y-=6*mm
        txt(L,y,'부가세구분:  매입과세',True,7)
        txt(W/2,y,f'**내부 구매의뢰서NO. {request_no}',True,7)

    for page_idx in range(page_count):
        if page_idx > 0:
            c.showPage()
        y = draw_page_header(page_idx + 1)
        start = page_idx * ITEMS_PER_PAGE
        end = min(start + ITEMS_PER_PAGE, len(items))
        page_items = items[start:end]
        for off, item in enumerate(page_items):
            y = draw_item_row(start + off, item, y)
        # 마지막 페이지는 기존 양식처럼 15행까지 빈칸을 채우고 합계/하단을 출력한다.
        # 중간 페이지도 15행 프레임을 유지해서 다음 페이지 품목과 겹치지 않게 한다.
        for _ in range(ITEMS_PER_PAGE - len(page_items)):
            y = draw_blank_row(y)
        if page_idx < page_count - 1:
            txt(R, y-4*mm, '다음 페이지 계속', True, 7, 'right')
        else:
            draw_footer(y)

    c.save()
    return output_path


def generate_all_orders_for_request(request_data: dict, output_dir: str = './purchase_orders') -> list:
    os.makedirs(output_dir, exist_ok=True)
    paths=[]
    for v in request_data.get('vendors', []):
        order_no=f"PO{datetime.now().strftime('%Y')}{request_data.get('request_no','').replace('-','')}"
        data={**request_data, **v, 'order_no': order_no}
        path=os.path.join(output_dir, f"발주서_{order_no}_{v.get('vendor_name','업체')}.pdf")
        generate_purchase_order_pdf(data,path); paths.append(path)
    return paths
