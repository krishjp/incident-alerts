import os
import pytz
from datetime import datetime
from dotenv import load_dotenv
from sqlalchemy import create_engine, Column, String, Boolean, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker

from crypto_utils import decrypt_phone

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL is not set")

# Prisma maps model Account to Account table, user to User, etc.
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class RouteSubscription(Base):
    __tablename__ = "RouteSubscription"
    id = Column(String, primary_key=True, index=True)
    userId = Column(String)
    origin = Column(String)
    destination = Column(String)
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
def get_active_subscriptions():
    db = SessionLocal()
    try:
        # Get current time in PST
        pst = pytz.timezone('America/Los_Angeles')
        now = datetime.now(pst)
        current_time_str = now.strftime("%H:%M")
        
        subs = db.query(RouteSubscription).filter(RouteSubscription.isActive == True).all()
        # Filter in python to avoid complex time logic in SQLite/Postgres
        active_subs = []
        for sub in subs:
            user = db.query(User).filter(User.id == sub.userId).first()
            if not user or not user.phone:
                continue

            # Handle cross-midnight sub times vs single day
            in_window = False
            start, end = sub.startTime, sub.endTime
            if start <= end:
                in_window = start <= current_time_str <= end
            else:
                # e.g. 22:00 -> 06:00
                in_window = current_time_str >= start or current_time_str <= end
                
            if in_window:
                active_subs.append({
                    "sub": sub,
                    "phone": decrypt_phone(user.phone),
                    "user": user.name or "User"
                })
        return active_subs
    finally:
        db.close()
