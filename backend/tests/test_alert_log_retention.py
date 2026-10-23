import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models import AlertMessage, prune_alert_messages

NOW = datetime(2026, 10, 23, 12, 0, 0)


@pytest.fixture
def db():
    # SQLite stands in for Postgres; the cleanup is a single date-filtered delete.
    engine = create_engine("sqlite://")
    AlertMessage.__table__.create(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _msg(db, kind, hours_ago):
    db.add(AlertMessage(
        userId="user1", subscriptionId="sub1", routeLabel="A->B", incidentNumber="LA01",
        kind=kind, message=kind, delivery="mock", createdAt=NOW - timedelta(hours=hours_ago),
    ))
    db.commit()


def test_deletes_messages_older_than_48_hours_resolved_or_not(db):
    _msg(db, "NEW", hours_ago=50)
    _msg(db, "RESOLVED", hours_ago=49)
    _msg(db, "UPDATE", hours_ago=47)

    assert prune_alert_messages(db, now=NOW) == 2
    assert [m.kind for m in db.query(AlertMessage).all()] == ["UPDATE"]


def test_keeps_recent_messages(db):
    _msg(db, "NEW", hours_ago=1)

    assert prune_alert_messages(db, now=NOW) == 0
