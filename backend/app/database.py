from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings

_is_sqlite = settings.database_url.startswith("sqlite")

_engine_kwargs: dict = {}
if _is_sqlite:
    _engine_kwargs["connect_args"] = {
        "check_same_thread": False,
        # Wait for a writer to finish instead of raising "database is locked"
        # the moment two processes collide. The API container and the arq
        # worker share one file, and a rep uploading a month of receipts has
        # both writing at once.
        "timeout": settings.sqlite_busy_timeout,
    }

engine = create_engine(settings.database_url, **_engine_kwargs)


if _is_sqlite:

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record):
        # WAL lets readers work while a writer holds the file, which is what
        # makes two processes on one SQLite file practical at all. Both pragmas
        # are per-connection, so they belong on the connect event.
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute(f"PRAGMA busy_timeout={int(settings.sqlite_busy_timeout * 1000)}")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def create_tables():
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
