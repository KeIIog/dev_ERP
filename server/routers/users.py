# server/routers/users.py
# DevERP_WEB 로그인 하드픽스
# - admin / roqkfxla 복구
# - 조직도 직원: 아이디=이름 / 기본 비밀번호=1
# - 기존 bcrypt hash, plain password, 손상 hash 모두 호환
# - 설정 탭 비밀번호 변경 API 유지

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from jose import jwt
from datetime import datetime, timedelta
from pydantic import BaseModel
from typing import Optional
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from server.database import get_db, User

try:
    import server.database as dbmod
except Exception:
    dbmod = None

router = APIRouter()

SECRET_KEY = "devERP-secret-key-2024"
ALGORITHM = "HS256"

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/users/login")


class UserCreate(BaseModel):
    username: str
    password: str
    name: str
    role: str
    department: str


class PasswordChange(BaseModel):
    username: Optional[str] = None
    current_password: Optional[str] = None
    new_password: str


def _org_rows():
    if not dbmod:
        return []
    rows = []
    rows += list(getattr(dbmod, "ORG_USERS", []) or [])
    rows += list(getattr(dbmod, "LEGACY_ALIASES", []) or [])
    return rows


def _infer_role(department: str) -> str:
    if dbmod and hasattr(dbmod, "infer_role_from_department"):
        try:
            return dbmod.infer_role_from_department(department)
        except Exception:
            pass

    dept = str(department or "").strip()
    if "개발그룹" in dept:
        return "dev"
    if "구매그룹" in dept or dept.startswith("구매팀"):
        return "purchase"
    return "general"


def _org_user_info(username: str):
    username = str(username or "").strip()
    for row in _org_rows():
        try:
            u, name, department, position = row
        except Exception:
            continue
        if str(u).strip() == username:
            return {
                "username": u,
                "name": name,
                "department": department,
                "position": position,
                "role": _infer_role(department),
            }
    return None


def _hash(password: str) -> str:
    return pwd_context.hash(str(password or ""))


def _password_matches(plain_password: str, stored_hash: str) -> bool:
    plain_password = str(plain_password or "")
    stored_hash = str(stored_hash or "")

    if not stored_hash:
        return False

    # 기존/복구 DB가 평문으로 저장된 경우 호환
    if stored_hash == plain_password:
        return True

    try:
        return pwd_context.verify(plain_password, stored_hash)
    except Exception:
        return False


def _is_plain_password_match(plain_password: str, stored_hash: str) -> bool:
    return str(stored_hash or "") == str(plain_password or "")


def _password_hash_looks_broken(stored_hash: str) -> bool:
    """
    예전 업데이트/DB 이동 과정에서 password_hash가 비거나 잘린 경우만 기본 비번 복구 허용.
    정상적으로 변경된 비밀번호 hash까지 1로 되돌리는 문제는 막는다.
    """
    s = str(stored_hash or "").strip()
    if not s or s.lower() in {"none", "null", "nan"}:
        return True
    # bcrypt hash처럼 보이는데 너무 짧으면 손상으로 판단
    if s.startswith(("$2a$", "$2b$", "$2y$")) and len(s) < 50:
        return True
    # 알 수 없는 $ 시작 hash는 passlib 검증 실패 시 복구 대상이 될 수 있다.
    if s.startswith("$") and not s.startswith(("$2a$", "$2b$", "$2y$")):
        return True
    return False


def _upgrade_plain_password_if_needed(db: Session, user: User, plain_password: str):
    """평문으로 남아 있던 비밀번호는 로그인 성공 시 bcrypt hash로 즉시 승격."""
    try:
        if _is_plain_password_match(plain_password, getattr(user, "password_hash", "")):
            user.password_hash = _hash(plain_password)
            db.commit()
            db.refresh(user)
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass


def _repair_default_password_if_hash_broken(db: Session, user: User, username: str, password: str) -> bool:
    """
    DB의 password_hash가 비어 있거나 손상된 경우에만 조직도 기본 비번/admin 기본 비번으로 복구.
    이미 사용자가 설정 탭에서 바꾼 정상 hash는 여기서 덮어쓰지 않는다.
    """
    default_pw = _default_password_for(username)
    if not default_pw or str(password or "") != default_pw:
        return False
    if not _password_hash_looks_broken(getattr(user, "password_hash", "")):
        return False
    try:
        user.password_hash = _hash(default_pw)
        try:
            user.is_active = True
        except Exception:
            pass
        db.commit()
        db.refresh(user)
        print(f"✅ 로그인 비밀번호 hash 복구: {username}")
        return True
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        print(f"⚠ 로그인 비밀번호 hash 복구 실패: {username}: {e}")
        return False


def _default_password_for(username: str) -> Optional[str]:
    username = str(username or "").strip()
    if username == "admin":
        return "roqkfxla"
    if _org_user_info(username):
        return "1"
    return None


def _ensure_user_for_login(db: Session, username: str, password: str) -> Optional[User]:
    """
    로그인 시점에 필수 계정이 없거나 hash가 깨진 경우 자동 복구.
    """
    username = str(username or "").strip()
    password = str(password or "")

    user = db.query(User).filter(User.username == username).first()
    default_pw = _default_password_for(username)

    if username == "admin":
        if not user:
            if password not in ("roqkfxla", "1"):
                return None
            user = User(
                username="admin",
                password_hash=_hash("roqkfxla"),
                name="관리자",
                role="admin",
                department="관리",
            )
            try:
                user.position = "관리자"
            except Exception:
                pass
            try:
                user.is_active = True
            except Exception:
                pass
            db.add(user)
            db.commit()
            db.refresh(user)
            return user

        # 기존 admin 계정의 비밀번호는 변경 가능해야 하므로 로그인 시 강제 초기화하지 않는다.
        # 계정 메타데이터만 보정하고, 실제 인증은 아래 _password_matches에서 처리한다.
        changed = False
        if user.role != "admin":
            user.role = "admin"; changed = True
        if not user.name:
            user.name = "관리자"; changed = True
        if not user.department:
            user.department = "관리"; changed = True
        try:
            if getattr(user, "is_active", True) is not True:
                user.is_active = True; changed = True
        except Exception:
            pass
        if changed:
            db.commit()
            db.refresh(user)

    info = _org_user_info(username)
    if info:
        if not user:
            if password != "1":
                return None
            user = User(
                username=username,
                password_hash=_hash("1"),
                name=info["name"],
                role=info["role"],
                department=info["department"],
            )
            try:
                user.position = info["position"]
            except Exception:
                pass
            try:
                user.is_active = True
            except Exception:
                pass
            db.add(user)
            db.commit()
            db.refresh(user)
            return user

        # 조직도 계정은 로그인 시마다 부서/직급/권한을 최신 ORG_USERS 기준으로 동기화한다.
        # 기존에는 기본 비밀번호(1)로 로그인할 때만 동기화되어,
        # 비밀번호를 변경한 직원은 database.py의 부서 변경이 즉시 반영되지 않을 수 있었다.
        changed = False
        if user.name != info["name"]:
            user.name = info["name"]
            changed = True
        if user.department != info["department"]:
            user.department = info["department"]
            changed = True
        if getattr(user, "role", "") != "admin" and user.role != info["role"]:
            user.role = info["role"]
            changed = True
        try:
            if getattr(user, "position", None) != info["position"]:
                user.position = info["position"]
                changed = True
        except Exception:
            pass
        try:
            if getattr(user, "is_active", True) is not True:
                user.is_active = True
                changed = True
        except Exception:
            pass

        # 기존 직원 계정의 비밀번호는 설정 탭에서 변경될 수 있으므로
        # 기본 비밀번호(1)로 로그인했다는 이유만으로 hash를 다시 1로 덮어쓰지 않는다.

        if changed:
            db.commit()
            db.refresh(user)

    return user


def create_token(data: dict):
    d = data.copy()
    d["exp"] = datetime.utcnow() + timedelta(hours=8)
    return jwt.encode(d, SECRET_KEY, algorithm=ALGORITHM)


def _get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
    except Exception:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")

    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=401, detail="사용자 정보를 찾을 수 없습니다")
    return user


@router.post("/login")
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    username = str(form.username or "").strip()
    password = str(form.password or "")

    user = _ensure_user_for_login(db, username, password)

    if not user:
        raise HTTPException(status_code=401, detail="아이디 또는 비밀번호가 틀렸습니다")

    active = getattr(user, "is_active", True)
    if active is False or str(active).strip() == "0":
        # 조직도/관리자 기본 계정은 비활성화되어 있어도 기본 비번으로 로그인 시 활성화
        if username == "admin" and password in ("roqkfxla", "1"):
            user.is_active = True
            db.commit()
        elif _org_user_info(username) and password == "1":
            user.is_active = True
            db.commit()
        else:
            raise HTTPException(status_code=403, detail="비활성화된 계정입니다")

    if not _password_matches(password, user.password_hash):
        # 변경된 비밀번호가 기본 비밀번호(1)로 되돌아가는 문제는 막되,
        # DB 이동/업데이트 중 password_hash가 비거나 깨진 경우에만 기본 비번으로 복구한다.
        if not _repair_default_password_if_hash_broken(db, user, username, password):
            raise HTTPException(status_code=401, detail="아이디 또는 비밀번호가 틀렸습니다. 비밀번호를 잊은 경우 reset_login_password.bat로 초기화하세요.")
    else:
        _upgrade_plain_password_if_needed(db, user, password)

    token = create_token({"sub": user.username, "role": user.role, "name": user.name})
    return {
        "access_token": token,
        "token_type": "bearer",
        "role": user.role,
        "name": user.name,
        "username": user.username,
        "department": user.department,
    }


@router.post("/create")
def create_user(data: UserCreate, db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == data.username).first():
        raise HTTPException(status_code=400, detail="이미 존재하는 아이디입니다")

    user = User(
        username=data.username,
        password_hash=_hash(data.password),
        name=data.name,
        role=data.role,
        department=data.department,
    )
    db.add(user)
    db.commit()
    return {"success": True, "message": f"사용자 '{data.name}' 생성 완료"}


@router.get("/list")
def list_users(db: Session = Depends(get_db)):
    return [
        {
            "id": u.id,
            "username": u.username,
            "name": u.name,
            "role": u.role,
            "department": u.department,
            "position": getattr(u, "position", ""),
            "is_active": getattr(u, "is_active", True),
        }
        for u in db.query(User).order_by(User.id.asc()).all()
    ]


@router.post("/change_password")
def change_password(data: PasswordChange, db: Session = Depends(get_db), current_user: User = Depends(_get_current_user)):
    target_username = (data.username or current_user.username).strip()
    target = db.query(User).filter(User.username == target_username).first()

    if not target:
        raise HTTPException(status_code=404, detail="계정을 찾을 수 없습니다")

    is_self = target.username == current_user.username
    is_admin = current_user.role == "admin"

    if not (is_self or is_admin):
        raise HTTPException(status_code=403, detail="다른 계정 비밀번호를 변경할 권한이 없습니다")

    if is_self and not is_admin:
        if not data.current_password or not _password_matches(data.current_password, current_user.password_hash):
            # 직원 기본 비번 1이 아직 해시 복구 전일 수도 있으므로 허용
            if not (data.current_password == "1" and _org_user_info(current_user.username)):
                raise HTTPException(status_code=400, detail="현재 비밀번호가 틀렸습니다")

    if not data.new_password or len(data.new_password.strip()) < 1:
        raise HTTPException(status_code=400, detail="새 비밀번호를 입력하세요")

    target.password_hash = _hash(data.new_password.strip())
    db.commit()

    return {"success": True, "message": "비밀번호가 변경되었습니다"}
