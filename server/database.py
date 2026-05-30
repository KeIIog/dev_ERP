
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Float, Text, ForeignKey, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shared.config import DB_PATH

engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    id            = Column(Integer, primary_key=True, index=True)
    username      = Column(String, unique=True, index=True)
    password_hash = Column(String)
    name          = Column(String)
    role          = Column(String)
    department    = Column(String)
    position      = Column(String)
    phone         = Column(String)
    email         = Column(String)
    bizbox_id     = Column(String)
    created_at    = Column(DateTime, default=datetime.now)
    is_active     = Column(Integer, default=1)


class PurchaseRequest(Base):
    __tablename__ = "purchase_requests"
    id              = Column(Integer, primary_key=True, index=True)
    request_no      = Column(String, unique=True, index=True)
    project_code    = Column(String)
    # 정부과제 재료비관리용 분류 정보
    project_year     = Column(String)  # 예: 1차(2025)
    category         = Column(String)  # 예: 재료비/장비비
    sub_category     = Column(String)
    item_type        = Column(String)  # 화면의 구분
    budget_type      = Column(String)  # 재료비관리 구분 매칭용
    title_full      = Column(String)
    project_name    = Column(String)
    item_name       = Column(String)
    spec            = Column(String)
    quantity        = Column(Integer)
    unit            = Column(String)
    unit_price      = Column(Float)
    reason          = Column(Text)
    requester       = Column(String)
    requested_by    = Column(String)  # 실제 구매의뢰를 등록한 계정명
    department      = Column(String)
    request_date    = Column(DateTime, default=datetime.now)
    required_date   = Column(DateTime)
    status          = Column(String, default="대기")
    bizbox_no       = Column(String)
    bizbox_uploaded = Column(Integer, default=0)
    items_json      = Column(Text)
    vendors_json    = Column(Text)
    actual_received_diff = Column(Integer, default=0)
    actual_items_json = Column(Text)
    # 입고현황에서 관리자가 의도적으로 삭제한 품목의 보정 방지 키 목록(JSON).
    # 업체 발주 건이 품목 0개가 되어 삭제되더라도 구매의뢰서에 tombstone을 보존한다.
    deleted_receipt_item_keys_json = Column(Text)
    attach_files    = Column(Text)
    orders          = relationship("PurchaseOrder", back_populates="purchase_request")


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"
    id                = Column(Integer, primary_key=True, index=True)
    order_no          = Column(String, unique=True, index=True)
    request_id        = Column(Integer, ForeignKey("purchase_requests.id"))
    purchase_request  = relationship("PurchaseRequest", back_populates="orders")
    vendor_name       = Column(String)
    vendor_email      = Column(String)
    vendor_contact    = Column(String)
    delivery_date     = Column(DateTime)
    order_date        = Column(DateTime, default=datetime.now)
    status            = Column(String, default="발주")
    email_sent        = Column(Integer, default=0)
    pdf_path          = Column(String)
    email_draft_path  = Column(String)
    inspection_report_pdf_path = Column(String)
    inspection_report_created_at = Column(DateTime)
    order_completed_by = Column(String)  # 발주진행완료를 누른 계정명
    order_completed_at = Column(DateTime)
    tax_docs_completed_by = Column(String)  # 세금계산서/거래명세서 처리완료를 누른 계정명
    tax_docs_completed_at = Column(DateTime)
    # 입고현황에서 관리자가 의도적으로 삭제한 품목의 보정 방지 키 목록(JSON).
    # 기존 자동 보정 로직이 삭제 품목을 다시 생성하지 않도록 사용한다.
    deleted_receipt_item_keys_json = Column(Text)
    # normal: 견적서 품목과 입고 품목이 동일한 일반 건
    # cost: 실제 입고품 다름 건의 비용처리/발주서 전송용 발주 건
    # receipt: 실제 입고품 다름 건의 QR/입고관리용 발주 건
    order_type        = Column(String, default="normal")
    items             = relationship("ReceiptItem", back_populates="order")


class ReceiptItem(Base):
    __tablename__ = "receipt_items"
    id              = Column(Integer, primary_key=True, index=True)
    order_id        = Column(Integer, ForeignKey("purchase_orders.id"))
    order           = relationship("PurchaseOrder", back_populates="items")
    item_name       = Column(String)
    spec            = Column(String)
    quantity        = Column(Integer, default=0)
    unit            = Column(String, default="EA")
    unit_price      = Column(Float, default=0)
    # 발주/입고현황 표시용 보조 컬럼. 기존 DB는 마이그레이션에서 자동 추가한다.
    material_code   = Column(String)
    maker           = Column(String)  # 화면의 비고(제조사). 업체 구분에도 사용.
    item_group      = Column(String)
    axis_type       = Column(String)
    order_round     = Column(String)
    note            = Column(Text)
    qr_code         = Column(String, unique=True, index=True)
    qr_code_path    = Column(String)
    stage           = Column(String, default="미입고")
    purchase_recv_at   = Column(DateTime)
    purchase_recv_by   = Column(String)
    purchase_photo     = Column(String)
    quality_recv_at    = Column(DateTime)
    quality_recv_by    = Column(String)
    quality_photo      = Column(String)
    manufacture_recv_at  = Column(DateTime)
    manufacture_recv_by  = Column(String)
    manufacture_photo    = Column(String)
    created_at      = Column(DateTime, default=datetime.now)


def _add_column_if_missing(conn, table_name: str, column_name: str, column_sql: str):
    cols = [row[1] for row in conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()]
    if column_name not in cols:
        conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}"))


def _run_migrations():
    with engine.begin() as conn:
        _add_column_if_missing(conn, 'purchase_requests', 'project_code', 'TEXT')
        _add_column_if_missing(conn, 'purchase_requests', 'project_year', 'TEXT')
        _add_column_if_missing(conn, 'purchase_requests', 'category', 'TEXT')
        _add_column_if_missing(conn, 'purchase_requests', 'sub_category', 'TEXT')
        _add_column_if_missing(conn, 'purchase_requests', 'item_type', 'TEXT')
        _add_column_if_missing(conn, 'purchase_requests', 'budget_type', 'TEXT')
        _add_column_if_missing(conn, 'purchase_requests', 'title_full', 'TEXT')
        _add_column_if_missing(conn, 'purchase_requests', 'attach_files', 'TEXT')
        _add_column_if_missing(conn, 'purchase_requests', 'requested_by', 'TEXT')
        _add_column_if_missing(conn, 'purchase_requests', 'actual_received_diff', 'INTEGER DEFAULT 0')
        _add_column_if_missing(conn, 'purchase_requests', 'actual_items_json', 'TEXT')
        _add_column_if_missing(conn, 'purchase_requests', 'deleted_receipt_item_keys_json', 'TEXT')
        _add_column_if_missing(conn, 'purchase_orders', 'pdf_path', 'TEXT')
        _add_column_if_missing(conn, 'purchase_orders', 'email_draft_path', 'TEXT')
        _add_column_if_missing(conn, 'purchase_orders', 'inspection_report_pdf_path', 'TEXT')
        _add_column_if_missing(conn, 'purchase_orders', 'inspection_report_created_at', 'DATETIME')
        _add_column_if_missing(conn, 'purchase_orders', 'order_completed_by', 'TEXT')
        _add_column_if_missing(conn, 'purchase_orders', 'order_completed_at', 'DATETIME')
        _add_column_if_missing(conn, 'purchase_orders', 'tax_docs_completed_by', 'TEXT')
        _add_column_if_missing(conn, 'purchase_orders', 'tax_docs_completed_at', 'DATETIME')
        _add_column_if_missing(conn, 'purchase_orders', 'deleted_receipt_item_keys_json', 'TEXT')
        _add_column_if_missing(conn, 'purchase_orders', 'order_type', "TEXT DEFAULT 'normal'")
        _add_column_if_missing(conn, 'receipt_items', 'quality_photo', 'TEXT')
        _add_column_if_missing(conn, 'receipt_items', 'manufacture_photo', 'TEXT')
        _add_column_if_missing(conn, 'receipt_items', 'material_code', 'TEXT')
        _add_column_if_missing(conn, 'receipt_items', 'maker', 'TEXT')
        _add_column_if_missing(conn, 'receipt_items', 'item_group', 'TEXT')
        _add_column_if_missing(conn, 'receipt_items', 'axis_type', 'TEXT')
        _add_column_if_missing(conn, 'receipt_items', 'order_round', 'TEXT')
        _add_column_if_missing(conn, 'receipt_items', 'note', 'TEXT')


# ─── 조직도 기반 직원 계정 (id=이름, pw=1) ────────────────────────────────────
ORG_USERS = [
    # (username, name, department, position)
    ("이현철",   "이현철",   "경영진",                 "대표이사"),
    ("박경도",   "박경도",   "경영진",                 "부사장/CTO"),
    ("임원규",   "임원규",   "경영진",                 "전무/COO"),

    ("조규중",   "조규중",   "모션개발팀/개발그룹",      "상무"),
    ("조승협",   "조승협",   "모션개발팀/개발그룹",      "마스터연구원"),
    ("정회빈",   "정회빈",   "모션개발팀/개발그룹",      "마스터연구원"),
    ("노덕기",   "노덕기",   "모션개발팀/개발그룹",      "선임연구원"),
    ("고성훈",   "고성훈",   "모션개발팀/개발그룹",      "책임연구원"),
    ("임다솔",   "임다솔",   "모션개발팀/개발그룹",      "전임연구원"),
    ("서준상",   "서준상",   "모션개발팀/개발그룹",      "선임연구원"),
    ("명재욱",   "명재욱",   "모션개발팀/개발그룹",      "선임연구원"),
    ("이호형",   "이호형",   "모션개발팀/개발그룹",      "선임연구원"),
    ("조석우",   "조석우",   "모션개발팀/개발그룹",      "전임연구원"),
    ("김유정",   "김유정",   "모션개발팀/개발그룹",      "선임연구원"),
    ("이지현",   "이지현",   "모션개발팀/개발그룹",      "전임연구원"),
    ("정세용",   "정세용",   "모션개발팀/개발그룹",      "전임연구원"),

    ("이길행",   "이길행",   "생산팀",                 "상무"),
    ("이용주",   "이용주",   "생산팀/생산그룹",          "부장"),
    ("이승락",   "이승락",   "생산팀/생산그룹",          "부장"),
    ("김준성",   "김준성",   "생산팀/생산그룹",          "부장"),
    ("김성해",   "김성해",   "생산팀/생산그룹",          "차장"),
    ("김동성",   "김동성",   "생산팀/생산그룹",          "차장"),
    ("최용일",   "최용일",   "생산팀/생산그룹",          "과장"),
    ("김홍위",   "김홍위",   "생산팀/생산그룹",          "과장"),
    ("김대한",   "김대한",   "생산팀/생산그룹",          "대리"),
    ("김정훈",   "김정훈",   "생산팀/생산그룹",          "주임"),
    ("안도현",   "안도현",   "생산팀/생산그룹",          "사원"),
    ("김우주",   "김우주",   "생산팀/생산그룹",          "사원"),

    ("원충진",   "원충진",   "생산팀/전장/제어그룹",      "부장"),
    ("이만영",   "이만영",   "생산팀/전장/제어그룹",      "부장"),
    ("이건종",   "이건종",   "생산팀/전장/제어그룹",      "부장"),
    ("김지용",   "김지용",   "생산팀/전장/제어그룹",      "차장"),
    ("유민성",   "유민성",   "생산팀/전장/제어그룹",      "차장"),
    ("김원재",   "김원재",   "생산팀/전장/제어그룹",      "차장"),
    ("권보성",   "권보성",   "생산팀/전장/제어그룹",      "차장"),
    ("신준",     "신준",     "생산팀/전장/제어그룹",      "사원"),

    ("황성남",   "황성남",   "생산팀/품질그룹",          "차장"),
    ("전덕훈",   "전덕훈",   "생산팀/품질그룹",          "차장"),

    ("이영진",   "이영진",   "생산팀/설비개발그룹",       "이사"),
    ("송기영",   "송기영",   "생산팀/설비개발그룹",       "수석연구원"),
    ("변정한",   "변정한",   "생산팀/설비개발그룹",       "선임연구원"),
    ("황지영",   "황지영",   "생산팀/설비개발그룹",       "전임연구원"),

    ("김병록",   "김병록",   "영업팀",                 "전무"),
    ("권민준",   "권민준",   "영업팀/영업1그룹",         "이사"),
    ("송진화",   "송진화",   "영업팀/영업1그룹",         "이사"),
    ("김대용",   "김대웅",   "영업팀/영업1그룹",         "부장"),
    ("박준호",   "박준호",   "영업팀/영업1그룹",         "차장"),
    ("김명희",   "김명희",   "영업팀/영업1그룹",         "사원"),
    ("김재구",   "김재구",   "영업팀/영업2그룹",         "이사"),

    ("마종환",   "마충환",   "구매팀",                 "상무"),
    ("김권태",   "김권태",   "구매팀/구매그룹",          "이사"),
    ("이종한글", "이종한글", "구매팀/구매그룹",          "차장"),
    ("정일수",   "정일수",   "구매팀/구매그룹",          "과장"),
    ("원영상",   "원영상",   "구매팀/구매그룹",          "대리"),

    ("김혜숙",   "김혜숙",   "경영지원팀/기획그룹",       "부장"),
    ("민재기",   "민재기",   "경영지원팀/기획그룹",       "차장"),
    ("원미연",   "원미연",   "경영지원팀/기획그룹",       "대리"),
    ("여인태",   "여인태",   "경영지원팀/재무그룹",       "대리"),
]

# 예전 오타/구 조직도 이름도 로그인 가능하도록 유지
LEGACY_ALIASES = [
    ("조승혁", "조승혁", "모션개발팀/개발그룹", "마스터연구원"),
    ("정희빈", "정희빈", "모션개발팀/개발그룹", "마스터연구원"),
    ("신준", "신준", "생산팀/전장/제어그룹", "사원"),
    ("변정한", "변정한", "생산팀/설비개발그룹", "선임연구원"),
    ("김대웅", "김대웅", "영업팀/영업1그룹", "부장"),
    ("이종한글", "이종한글", "구매팀/구매그룹", "차장"),
]


def infer_role_from_department(department: str) -> str:
    dept = str(department or '').strip()
    if '개발그룹' in dept:
        return 'dev'
    if '구매그룹' in dept or dept.startswith('구매팀'):
        return 'purchase'
    return 'general'


def init_db():
    os.makedirs(os.path.dirname(DB_PATH) if os.path.dirname(DB_PATH) else '.', exist_ok=True)
    Base.metadata.create_all(bind=engine)
    _run_migrations()

    from passlib.context import CryptContext
    pwd_context = CryptContext(schemes=['bcrypt'], deprecated='auto')
    db = SessionLocal()

    # 관리자 계정
    if not db.query(User).filter(User.username == 'admin').first():
        admin = User(username='admin', password_hash=pwd_context.hash('roqkfxla'),
                     name='관리자', role='admin', department='관리')
        db.add(admin)
        db.commit()
        print('✅ 기본 관리자 계정 생성 완료 (admin / roqkfxla)')
    else:
        admin = db.query(User).filter(User.username == 'admin').first()
        # 기존 관리자 비밀번호는 설정 탭에서 변경될 수 있으므로 서버 시작 때 강제 초기화하지 않는다.
        # 비밀번호를 잊은 경우에만 DB 백업/복구 또는 신규 DB 생성 절차를 사용한다.
        changed = False
        if admin.role != 'admin':
            admin.role = 'admin'; changed = True
        if not admin.name:
            admin.name = '관리자'; changed = True
        if changed:
            db.commit()

    # 조직도 직원 계정 일괄 생성 (id=이름, pw=1)
    created = 0
    updated = 0
    all_org_users = ORG_USERS + LEGACY_ALIASES
    for (username, name, department, position) in all_org_users:
        inferred_role = infer_role_from_department(department)
        existing = db.query(User).filter(User.username == username).first()
        if not existing:
            u = User(username=username, password_hash=pwd_context.hash('1'),
                     name=name, role=inferred_role, department=department, position=position)
            db.add(u)
            created += 1
        else:
            changed = False
            # 기존 계정 비밀번호는 설정탭에서 변경 가능하므로 더 이상 1로 강제 초기화하지 않음
            if existing.name != name:
                existing.name = name
                changed = True
            if existing.department != department:
                existing.department = department
                changed = True
            if existing.position != position:
                existing.position = position
                changed = True
            if existing.role != inferred_role and existing.role != 'admin':
                existing.role = inferred_role
                changed = True
            if changed:
                updated += 1
    if created > 0 or updated > 0:
        db.commit()
    if created > 0:
        print(f'✅ 조직도 직원 계정 {created}명 생성 완료 (비밀번호: 1)')
    if updated > 0:
        print(f'✅ 조직도 권한/부서 정보 {updated}명 동기화 완료')

    db.close()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
