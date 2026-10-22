import pytz
from contextlib import contextmanager
from datetime import datetime
from sqlalchemy import create_engine, Column, String, Boolean, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker

from config import settings
from crypto_utils import decrypt_phone

DATABASE_URL = settings.database_url

# Prisma maps model Account to Account table, user to User, etc.
#
# Pooling is configured explicitly rather than left at SQLAlchemy's defaults:
# the worker shares its Postgres instance with the Next.js frontend's Prisma
# client, and managed Postgres tiers cap total connections aggressively. An
# unbounded pool here starves the frontend under load.
#   - pool_pre_ping discards connections a managed proxy (PgBouncer, Cloud SQL
#     auth proxy) closed while the worker was sleeping between poll cycles.
#   - pool_recycle bounds connection age below typical server-side idle timeouts.
engine = create_engine(
    DATABASE_URL,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout,
    pool_recycle=settings.db_pool_recycle,
    pool_pre_ping=True,
)
# expire_on_commit=False: the worker reads subscription rows in one session and
# then uses those objects for the rest of the poll cycle, after the session has
# been returned to the pool. Expiring on commit would turn every later attribute
# read into a DetachedInstanceError.
SessionLocal = sessionmaker(
    autocommit=False, autoflush=False, expire_on_commit=False, bind=engine
)
Base = declarative_base()


@contextmanager
def session_scope():
    """
    Transactional session that always returns its connection to the pool.

    Replaces the manual try/except/finally + db.close() blocks that were
    duplicated per incident in the worker loop — a single missed close() there
    leaks a pooled connection every poll cycle until the pool is exhausted.
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

class RouteSubscription(Base):
    __tablename__ = "RouteSubscription"
    id = Column(String, primary_key=True, index=True)
    userId = Column(String)
    origin = Column(String)
    destination = Column(String)
    originDisplayName = Column(String, nullable=True)
    destinationDisplayName = Column(String, nullable=True)
    polyline = Column(String)
    area = Column(String)
    startTime = Column(String) # e.g. "07:00"
    endTime = Column(String)   # e.g. "08:00"
    isActive = Column(Boolean)

class User(Base):
    __tablename__ = "User"
    id = Column(String, primary_key=True)
    name = Column(String)
    email = Column(String, unique=True)
    phone = Column(String)

class NotifiedIncident(Base):
    __tablename__ = "NotifiedIncident"
    id = Column(String, primary_key=True)
    state = Column(String)
    createdAt = Column(DateTime, default=datetime.utcnow)
    updatedAt = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
def is_in_time_window(current_time_str: str, start: str, end: str) -> bool:
    """
    True when "HH:MM" current_time_str falls inside [start, end], handling
    windows that wrap past midnight (e.g. 22:00 -> 06:00).
    """
    if start <= end:
        return start <= current_time_str <= end
    return current_time_str >= start or current_time_str <= end


def get_active_subscriptions():
    with session_scope() as db:
        # Get current time in PST
        pst = pytz.timezone('America/Los_Angeles')
        now = datetime.now(pst)
        current_time_str = now.strftime("%H:%M")

        # Single join instead of a per-subscription User lookup — the old N+1
        # issued one round trip per subscription every poll cycle.
        rows = (
            db.query(RouteSubscription, User)
            .join(User, User.id == RouteSubscription.userId)
            .filter(RouteSubscription.isActive == True)  # noqa: E712 (SQL expression)
            .all()
        )

        # Time filtering stays in Python: the window logic wraps past midnight,
        # which is awkward to express portably in SQL.
        active_subs = []
        for sub, user in rows:
            if not user.phone:
                continue
            if not is_in_time_window(current_time_str, sub.startTime, sub.endTime):
                continue
            active_subs.append({
                "sub": sub,
                "phone": decrypt_phone(user.phone),
                "user": user.name or "User",
            })
        return active_subs
