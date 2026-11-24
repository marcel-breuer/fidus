"""Store the cached speech object key for each chat message."""

import sqlalchemy as sa

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("speech_key", sa.String(255)))


def downgrade() -> None:
    op.drop_column("messages", "speech_key")
