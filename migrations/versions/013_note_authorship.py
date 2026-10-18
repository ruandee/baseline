from pathlib import Path

from alembic import op

revision = "013"
down_revision = "012"


def upgrade():
    op.get_bind().connection.driver_connection.execute(
        Path(__file__).with_suffix(".sql").read_text(encoding="utf-8"))


def downgrade():
    raise RuntimeError("Use a forward migration to preserve immutable source attribution")
