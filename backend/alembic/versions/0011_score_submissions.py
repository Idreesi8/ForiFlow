"""Preserve assessment save intents for safe retries; existing cases stay intact."""
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '0011_score_submissions'
down_revision = '0010_security_hardening'
branch_labels = None
depends_on = None
JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), 'postgresql')


def upgrade():
    op.create_table('score_submissions',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('submission_key', sa.String(36), nullable=False),
        sa.Column('payload_hash', sa.String(64), nullable=False),
        sa.Column('application_id', sa.Integer(), sa.ForeignKey('applications.id', ondelete='RESTRICT'), nullable=True),
        sa.Column('response_json', JSON_TYPE, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('user_id', 'submission_key', name='uq_score_submission_owner_key'))
    audit = sa.table('audit_logs', sa.column('occurred_at', sa.DateTime(timezone=True)),
        sa.column('username', sa.String), sa.column('action', sa.String),
        sa.column('entity_type', sa.String), sa.column('entity_id', sa.String), sa.column('details', JSON_TYPE))
    op.get_bind().execute(audit.insert(), [dict(occurred_at=datetime.now(timezone.utc), username='system',
        action='migration.applied', entity_type='migration', entity_id=revision,
        details={'new_table': 'score_submissions', 'existing_assessments_unchanged': True})])


def downgrade():
    op.drop_table('score_submissions')
