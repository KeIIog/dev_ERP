# server/scheduler.py
import schedule, time, logging
from datetime import datetime
import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.database import SessionLocal, PurchaseOrder, ReceiptItem
from shared.config import QR_SCHEDULER_INTERVAL

logging.basicConfig(level=logging.INFO, format="%(asctime)s [SCHEDULER] %(message)s")
logger = logging.getLogger(__name__)


def job_generate_pending_qr():
    logger.info("QR 자동 생성 작업 시작...")
    db = SessionLocal()
    try:
        pending = db.query(PurchaseOrder).filter(
            PurchaseOrder.status != "취소"
        ).all()
        count = 0
        for order in pending:
            for item in order.items:
                if not item.qr_code:
                    try:
                        from server.qr_generator import generate_qr_for_item
                        generate_qr_for_item(item, order, db)
                        count += 1
                    except Exception as e:
                        logger.error(f"QR 생성 실패 [{item.item_name}]: {e}")
        if count:
            logger.info(f"  ✅ QR {count}개 생성 완료")
        else:
            logger.info("  신규 QR 생성 대상 없음")
    finally:
        db.close()


def job_check_delivery():
    db = SessionLocal()
    try:
        today = datetime.now()
        orders = db.query(PurchaseOrder).filter(
            PurchaseOrder.status.in_(["발주", "입고대기"])
        ).all()
        for o in orders:
            if o.delivery_date:
                days = (o.delivery_date - today).days
                if days < 0:
                    logger.warning(f"  ⚠️  납기 지연: {o.order_no} ({abs(days)}일 초과)")
                elif days <= 3:
                    logger.warning(f"  ⏰ 납기 임박: {o.order_no} (D-{days})")
    finally:
        db.close()


def start_scheduler():
    schedule.every(QR_SCHEDULER_INTERVAL).minutes.do(job_generate_pending_qr)
    schedule.every(QR_SCHEDULER_INTERVAL).minutes.do(job_check_delivery)
    job_generate_pending_qr()
    job_check_delivery()
    logger.info(f"스케줄러 실행중 ({QR_SCHEDULER_INTERVAL}분 주기)")
    while True:
        schedule.run_pending()
        time.sleep(60)
