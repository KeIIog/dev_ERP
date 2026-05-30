import os
import re
import html
from datetime import datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

DEFAULT_SUBJECT = "[국책과제][{project_code}]_{request_no}_발주서_송부의_件_({vendor_name})"


def _clean_spec_unit_values(spec, unit):
    known_units = {'EA','EACH','개','PCS','PC','SET','SETS','BOX','ROLL','M','MM','CM','KG','G','L','ML','식','본','매','조','대'}
    spec_txt = str(spec or '').strip()
    unit_txt = str(unit or '').strip()
    if unit_txt and unit_txt.upper() != 'EA':
        token = unit_txt.upper().replace('.', '').replace(' ', '')
        if token not in known_units and unit_txt not in spec_txt:
            spec_txt = (spec_txt + ' ' + unit_txt).strip() if spec_txt else unit_txt
    return spec_txt, 'EA'


def _short_vendor_name(vendor: str) -> str:
    """메일 제목 괄호 안 업체명은 화면 예시처럼 법인 표기를 줄여서 표시한다."""
    txt = str(vendor or '업체').strip()
    if not txt:
        return '업체'
    # 괄호/공백 법인 표기와 뒤쪽 주식회사 표기를 정리한다.
    txt = re.sub(r'\s+', ' ', txt)
    txt = re.sub(r'^(주식회사|\(주\)|㈜)\s*', '', txt)
    txt = re.sub(r'\s*(주식회사|\(주\)|㈜)$', '', txt)
    txt = txt.strip()
    return txt or str(vendor or '업체').strip() or '업체'


def build_order_mail_subject(order_data: dict) -> str:
    project_code = str(order_data.get('project_code') or '').strip()
    req = str(order_data.get('request_no') or order_data.get('order_no') or '').strip()
    vendor = _short_vendor_name(order_data.get('vendor_name') or '')
    # 스크린샷 기준 제목 형식:
    # [국책과제][R25GA01_02]_2026-3868_발주서_송부의_件_(강유시스템)
    if project_code:
        return f"[국책과제][{project_code}]_{req}_발주서_송부의_件_({vendor})"
    return f"[국책과제]_{req}_발주서_송부의_件_({vendor})"


def _fmt_num(v):
    try:
        f = float(v or 0)
        return f"{int(f):,}" if f.is_integer() else f"{f:,.1f}"
    except Exception:
        return str(v or '')


def _format_item_lines(order_data: dict) -> str:
    lines = []
    for idx, item in enumerate(order_data.get('items', []), start=1):
        item_name = (item.get('item_name') or '').strip()
        spec, unit = _clean_spec_unit_values(item.get('spec') or '-', item.get('unit') or 'EA')
        qty = item.get('quantity', 0)
        due = item.get('due_date') or order_data.get('delivery_date') or ''
        price = _fmt_num(item.get('unit_price'))
        maker = (item.get('maker') or '').strip()
        axis = (item.get('axis') or '').strip()
        extras = []
        if axis:
            extras.append(f"축구분: {axis}")
        if maker:
            extras.append(f"비고: {maker}")
        extra_txt = f" ({', '.join(extras)})" if extras else ''
        lines.append(f"{idx}. {item_name} / 규격: {spec} / 수량: {qty} {unit} / 납기: {due} / 단가: {price}{extra_txt}")
    return '\n'.join(lines) if lines else '- 품목 정보 없음'


def _short_due_date(date_text: str) -> str:
    txt = str(date_text or '').strip()
    if not txt:
        return '지정 납기일'
    for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%Y.%m.%d', '%Y%m%d'):
        try:
            d = datetime.strptime(txt[:10] if fmt != '%Y%m%d' else txt[:8], fmt)
            return f"{d.month}/{d.day}"
        except Exception:
            pass
    # 2026-06-25 00:00:00 같은 값 보정
    m = re.search(r'(\d{4})[-./](\d{1,2})[-./](\d{1,2})', txt)
    if m:
        return f"{int(m.group(2))}/{int(m.group(3))}"
    return txt


def _orderer_name(order_data: dict) -> str:
    name = str(order_data.get('orderer_name') or '').strip()
    return name or '정일수'


def build_order_mail_body(order_data: dict) -> str:
    due = _short_due_date(order_data.get('delivery_date') or '')
    orderer = _orderer_name(order_data)
    req_no = str(order_data.get('request_no') or order_data.get('order_no') or '2025-XXXX').strip() or '2025-XXXX'
    return f"""안녕하십니까.

이노로보틱스 구매팀 {orderer} 입니다.

보내주신 견적 관련하여 선진행 건 국책과제 발주서 송부 드립니다.

송부드린 QR라벨 제품에 부착하여 {due} 까지 납품 요청 드립니다.

[국책과제 발주 건 납품 시 참고사항]
- 거래명세표 컬러 직인 필수(문서번호와 일치: {req_no}).
- 납품 후 거래명세표 일자와 동일한 일자로 세금계산서 발행.
- 해당 국책과제 발주 건은 납품 시 서류처리 후 공급가액, 부가세 별도 입금 진행 예정.
- 계산서 발행 메일 주소 : goomae@innorobotics.co.kr

이상입니다.
"""


def build_order_mail_body_html(order_data: dict) -> str:
    due = html.escape(_short_due_date(order_data.get('delivery_date') or ''))
    orderer = html.escape(_orderer_name(order_data))
    req_no = html.escape(str(order_data.get('request_no') or order_data.get('order_no') or '2025-XXXX').strip() or '2025-XXXX')
    # Bizbox 편집기에서 색상/굵기가 유지되도록 모든 주요 스타일을 inline으로 지정한다.
    base = "font-family:'맑은 고딕','Malgun Gothic',Dotum,Arial,sans-serif;font-size:10pt;color:#000;line-height:1.65;"
    p = "margin:0 0 14px 0;"
    li = "margin:0 0 2px 0;"
    red = "color:#ff0000;font-weight:bold;"
    blue = "color:#0563c1;text-decoration:underline;font-weight:bold;"
    return f"""
<div style="{base}">
  <p style="{p}">안녕하십니까.</p>
  <p style="{p}">이노로보틱스 구매팀 {orderer} 입니다.</p>
  <p style="{p}">보내주신 견적 관련하여 선진행 건 국책과제 발주서 송부 드립니다.</p>
  <p style="{p}font-weight:bold;">송부드린 QR라벨 제품에 부착하여 {due} 까지 납품 요청 드립니다.</p>
  <p style="{p}font-weight:bold;">[국책과제 발주 건 납품 시 참고사항]</p>
  <div style="margin:0 0 14px 0;">
    <div style="{li}">- 거래명세표 <span style="{red}">컬러 직인 필수(문서번호와 일치: {req_no}).</span></div>
    <div style="{li}">- 납품 후 <span style="{red}">거래명세표 일자와 동일한 일자로 세금계산서 발행.</span></div>
    <div style="{li}">- 해당 국책과제 발주 건은 납품 시 서류처리 후 공급가액, 부가세 별도 입금 진행 예정.</div>
    <div style="{li}">- 계산서 발행 메일 주소 : <span style="{blue}">goomae@innorobotics.co.kr</span></div>
  </div>
  <p style="{p}">이상입니다.</p>
</div>
"""


def create_email_draft_file(to_email: str, subject: str, body: str, attachment_paths: list[str], output_path: str, body_html: str | None = None) -> str:
    msg = MIMEMultipart()
    msg['To'] = to_email or ''
    msg['Subject'] = subject
    msg['Date'] = datetime.now().strftime('%a, %d %b %Y %H:%M:%S')

    if body_html:
        alt = MIMEMultipart('alternative')
        alt.attach(MIMEText(body or '', 'plain', 'utf-8'))
        alt.attach(MIMEText(body_html or '', 'html', 'utf-8'))
        msg.attach(alt)
    else:
        msg.attach(MIMEText(body, 'plain', 'utf-8'))

    for path in attachment_paths:
        if not path or not os.path.exists(path):
            continue
        with open(path, 'rb') as f:
            part = MIMEApplication(f.read(), Name=os.path.basename(path))
        part['Content-Disposition'] = f'attachment; filename="{os.path.basename(path)}"'
        msg.attach(part)

    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    with open(output_path, 'wb') as f:
        f.write(msg.as_bytes())
    return output_path
