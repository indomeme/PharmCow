from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pharmcow.models import Base
from pharmcow.settings import settings

settings.ensure_dirs()

connect_args = {}
if settings.db_url.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(settings.db_url, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(engine)
