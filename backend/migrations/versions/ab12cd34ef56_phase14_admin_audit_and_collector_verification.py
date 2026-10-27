"""phase 14 admin audit and collector verification"""
from alembic import op
import sqlalchemy as sa
revision='ab12cd34ef56'; down_revision='c2c8be079f05'; branch_labels=None; depends_on=None

def upgrade():
    op.add_column('users', sa.Column('is_verified', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table('audit_logs', sa.Column('id', sa.UUID(), nullable=False), sa.Column('actor_user_id', sa.UUID(), nullable=True), sa.Column('action', sa.String(length=120), nullable=False), sa.Column('entity_type', sa.String(length=80), nullable=False), sa.Column('entity_id', sa.String(length=80), nullable=True), sa.Column('details', sa.JSON(), nullable=False), sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False), sa.ForeignKeyConstraint(['actor_user_id'], ['users.id'], ondelete='SET NULL'), sa.PrimaryKeyConstraint('id'))
    for idx,col in [('ix_audit_logs_actor_user_id','actor_user_id'),('ix_audit_logs_action','action'),('ix_audit_logs_entity_type','entity_type'),('ix_audit_logs_entity_id','entity_id'),('ix_audit_logs_created_at','created_at')]: op.create_index(idx,'audit_logs',[col])

def downgrade():
    for idx in ['ix_audit_logs_created_at','ix_audit_logs_entity_id','ix_audit_logs_entity_type','ix_audit_logs_action','ix_audit_logs_actor_user_id']: op.drop_index(idx,table_name='audit_logs')
    op.drop_table('audit_logs'); op.drop_column('users','is_verified')
