# server/routers/documents.py
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from server.database import get_db

router = APIRouter()

@router.get("/list")
def list_documents(db: Session = Depends(get_db)):
    return []
