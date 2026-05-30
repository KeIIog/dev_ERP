# reset_login_password.py
# DevERP 로그인 비밀번호 긴급 초기화 도구
# 사용 예:
#   python reset_login_password.py 고성훈 1
#   python reset_login_password.py admin roqkfxla
#   python reset_login_password.py --all-employees 1

import os
import sys
import sqlite3
from pathlib import Path


def _runtime_base() -> Path:
    return Path(__file__).resolve().parent


def _find_db() -> Path:
    base = _runtime_base()
    candidates = [
        base / "database" / "dev_erp.db",
        base / "_internal" / "database" / "dev_erp.db",
        Path.cwd() / "database" / "dev_erp.db",
        Path.cwd() / "_internal" / "database" / "dev_erp.db",
    ]
    for p in candidates:
        if p.exists():
            return p
    # 새 DB 위치 기준으로 표시
    return base / "database" / "dev_erp.db"


def _reset_one(conn: sqlite3.Connection, username: str, password: str) -> int:
    cur = conn.execute("SELECT id FROM users WHERE username=?", (username,))
    row = cur.fetchone()
    if not row:
        return 0
    # routers/users.py가 평문 password_hash를 호환하고, 첫 로그인 성공 시 bcrypt로 승격한다.
    conn.execute("UPDATE users SET password_hash=?, is_active=1 WHERE username=?", (password, username))
    return 1


def main() -> int:
    if len(sys.argv) < 2:
        print("사용법:")
        print("  python reset_login_password.py <아이디> [새비밀번호]")
        print("  python reset_login_password.py --all-employees [새비밀번호]")
        print("예:")
        print("  python reset_login_password.py 고성훈 1")
        print("  python reset_login_password.py admin roqkfxla")
        return 2

    target = sys.argv[1].strip()
    new_pw = (sys.argv[2] if len(sys.argv) >= 3 else ("roqkfxla" if target == "admin" else "1")).strip()
    db_path = _find_db()
    if not db_path.exists():
        print(f"DB 파일을 찾지 못했습니다: {db_path}")
        print("DevERP_Server.exe가 있는 폴더에서 실행하거나 database\\dev_erp.db를 확인하세요.")
        return 1

    conn = sqlite3.connect(str(db_path))
    try:
        if target == "--all-employees":
            rows = conn.execute("SELECT username FROM users WHERE username <> 'admin'").fetchall()
            count = 0
            for (username,) in rows:
                count += _reset_one(conn, username, new_pw)
            conn.commit()
            print(f"직원 계정 {count}개의 비밀번호를 '{new_pw}'로 초기화했습니다.")
        else:
            count = _reset_one(conn, target, new_pw)
            if count:
                conn.commit()
                print(f"'{target}' 계정 비밀번호를 '{new_pw}'로 초기화했습니다.")
            else:
                print(f"'{target}' 계정을 DB에서 찾지 못했습니다.")
                return 1
    finally:
        conn.close()
    print(f"DB: {db_path}")
    print("서버를 재시작한 뒤 새 비밀번호로 로그인하세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
