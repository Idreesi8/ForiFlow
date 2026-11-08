"""Append-only source and data-permission evidence, with no inferred grants."""
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0013_case_data_records'
down_revision = '0012_repayment_calendar'
branch_labels = None
depends_on = None
JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), 'postgresql')


def upgrade():
    op.create_table('case_data_records',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('application_id', sa.Integer(), sa.ForeignKey('applications.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('stream_key', sa.String(36), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('supersedes_id', sa.Integer(), sa.ForeignKey('case_data_records.id', ondelete='RESTRICT')),
        sa.Column('submission_key', sa.String(36), unique=True, nullable=False),
        sa.Column('payload_hash', sa.String(64), nullable=False),
        sa.Column('event_kind', sa.String(16), nullable=False),
        sa.Column('payload', JSON_TYPE, nullable=False),
        sa.Column('input_snapshot', JSON_TYPE, nullable=False),
        sa.Column('note', sa.String(500), nullable=False),
        sa.Column('created_by', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('application_id', 'stream_key', 'revision', name='uq_case_data_revision'))
    op.create_index('ix_case_data_records_application_id', 'case_data_records', ['application_id'])
    if op.get_bind().dialect.name == 'postgresql':
        op.execute("CREATE OR REPLACE FUNCTION case_data_records_append_only() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'case_data_records is append-only'; END; $$ LANGUAGE plpgsql")
        op.execute('CREATE TRIGGER case_data_records_no_change BEFORE UPDATE OR DELETE ON case_data_records FOR EACH ROW EXECUTE FUNCTION case_data_records_append_only()')
        op.execute('CREATE TRIGGER case_data_records_no_truncate BEFORE TRUNCATE ON case_data_records FOR EACH STATEMENT EXECUTE FUNCTION case_data_records_append_only()')
    else:
        for action in ('UPDATE', 'DELETE'):
            op.execute(f"CREATE TRIGGER case_data_records_no_{action.lower()} BEFORE {action} ON case_data_records BEGIN SELECT RAISE(ABORT, 'case_data_records is append-only'); END")
    audit = sa.table('audit_logs', sa.column('occurred_at', sa.DateTime(timezone=True)), sa.column('username', sa.String),
        sa.column('action', sa.String), sa.column('entity_type', sa.String), sa.column('entity_id', sa.String), sa.column('details', JSON_TYPE))
    op.get_bind().execute(audit.insert(), [dict(occurred_at=datetime.now(timezone.utc), username='system', action='migration.applied',
        entity_type='migration', entity_id=revision, details={'new_table': 'case_data_records', 'existing_records_unchanged': True})])


def downgrade():
    op.drop_table('case_data_records')
    if op.get_bind().dialect.name == 'postgresql':
        op.execute('DROP FUNCTION IF EXISTS case_data_records_append_only()')
