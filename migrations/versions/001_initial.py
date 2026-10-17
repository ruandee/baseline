from pathlib import Path

from alembic import op

revision = "001"
down_revision = None


def upgrade():
    sql = Path(__file__).with_suffix(".sql").read_text(encoding="utf-8")
    op.get_bind().connection.driver_connection.execute(sql)


def downgrade():
    raise RuntimeError("Source-preserving migration: restore a backup or forward-repair instead")
