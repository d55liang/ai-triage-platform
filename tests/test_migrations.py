from alembic import command
from alembic.config import Config


def test_downgrade_and_upgrade_round_trip(alembic_config: Config) -> None:
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")
