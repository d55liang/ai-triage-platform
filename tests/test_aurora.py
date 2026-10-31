import pytest
from sqlalchemy import text

from app.database import create_iam_engine


@pytest.mark.aurora
def test_iam_engine_connects() -> None:
    engine = create_iam_engine()
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT 1")) == 1
    engine.dispose()
