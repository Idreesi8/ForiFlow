"""Dated repayment schedules and explicitly allocated payment receipts."""
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0012_repayment_calendar'
down_revision = '0011_score_submissions'
branch_labels = None
depends_on = None
JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), 'postgresql')


def upgrade():
    op.create_table('repayment_schedules',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('application_id', sa.Integer(), sa.ForeignKey('applications.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('submission_key', sa.String(36), unique=True, nullable=False),
        sa.Column('replaces_id', sa.Integer(), sa.ForeignKey('repayment_schedules.id', ondelete='RESTRICT')),
        sa.Column('disbursed_on', sa.Date(), nullable=False),
        sa.Column('items', JSON_TYPE, nullable=False),
        sa.Column('source_note', sa.String(500), nullable=False),
        sa.Column('created_by', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('application_id', 'version', name='uq_repayment_schedule_version'))
    op.create_index('ix_repayment_schedules_application_id', 'repayment_schedules', ['application_id'])
    op.create_table('repayment_receipts',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('application_id', sa.Integer(), sa.ForeignKey('applications.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('schedule_id', sa.Integer(), sa.ForeignKey('repayment_schedules.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('submission_key', sa.String(36), unique=True, nullable=False),
        sa.Column('paid_on', sa.Date(), nullable=False),
        sa.Column('reference', sa.String(80), nullable=False),
        sa.Column('allocations', JSON_TYPE, nullable=False),
        sa.Column('created_by', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('voided_at', sa.DateTime(timezone=True)),
        sa.Column('voided_by', sa.String(64)),
        sa.Column('void_reason', sa.String(500)))
    op.create_index('ix_repayment_receipts_schedule_id', 'repayment_receipts', ['schedule_id'])
    op.create_index('uq_repayment_active_reference', 'repayment_receipts', ['application_id', 'reference'],
        unique=True, postgresql_where=sa.text('voided_at IS NULL'), sqlite_where=sa.text('voided_at IS NULL'))
    audit = sa.table('audit_logs', sa.column('occurred_at', sa.DateTime(timezone=True)),
        sa.column('username', sa.String), sa.column('action', sa.String),
        sa.column('entity_type', sa.String), sa.column('entity_id', sa.String), sa.column('details', JSON_TYPE))
    op.get_bind().execute(audit.insert(), [dict(occurred_at=datetime.now(timezone.utc), username='system',
        action='migration.applied', entity_type='migration', entity_id=revision,
        details={'new_tables': ['repayment_schedules', 'repayment_receipts'], 'existing_records_unchanged': True})])


def downgrade():
    op.drop_table('repayment_receipts')
    op.drop_table('repayment_schedules')
