"""Local identities and immutable upload attribution; no Jira runtime state."""
from alembic import op
import sqlalchemy as sa

revision = "0002_user_auth"
down_revision = "0001_upload_v3"
branch_labels = None
depends_on = None

# Frozen DDL: this revision does not import the evolving application metadata.
STATEMENTS = ["CREATE TABLE users (\n\tid TEXT NOT NULL, \n\tusername TEXT NOT NULL, \n\tdisplay_name TEXT NOT NULL, \n\tkind TEXT NOT NULL, \n\trole TEXT NOT NULL, \n\tenabled BOOLEAN NOT NULL, \n\tpassword_hash TEXT, \n\tmust_change_password BOOLEAN NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT ck_users_kind CHECK (kind IN ('human','service','system','legacy')), \n\tCONSTRAINT ck_users_role CHECK (role IN ('member','admin')), \n\tCONSTRAINT ck_users_username_case CHECK (username = lower(username)), \n\tCONSTRAINT ck_users_credentials CHECK (kind = 'human' OR (password_hash IS NULL AND role = 'member')), \n\tUNIQUE (username)\n)", 'CREATE TABLE auth_sessions (\n\tid TEXT NOT NULL, \n\tuser_id TEXT NOT NULL, \n\ttoken_hash CHAR(64) NOT NULL, \n\tcsrf_hash CHAR(64) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tlast_used_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\trevoked_at TIMESTAMP WITH TIME ZONE, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(user_id) REFERENCES users (id), \n\tUNIQUE (token_hash)\n)', 'CREATE INDEX ix_auth_sessions_user_id ON auth_sessions (user_id)', 'CREATE TABLE access_tokens (\n\tid TEXT NOT NULL, \n\tuser_id TEXT NOT NULL, \n\tname TEXT NOT NULL, \n\ttoken_hash CHAR(64) NOT NULL, \n\tscope TEXT NOT NULL, \n\tissued_by_user_id TEXT NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tlast_used_at TIMESTAMP WITH TIME ZONE, \n\trevoked_at TIMESTAMP WITH TIME ZONE, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(user_id) REFERENCES users (id), \n\tUNIQUE (token_hash), \n\tFOREIGN KEY(issued_by_user_id) REFERENCES users (id)\n)', 'CREATE INDEX ix_access_tokens_user_id ON access_tokens (user_id)', 'CREATE TABLE auth_rate_limits (\n\tkey TEXT NOT NULL, \n\t"window" BIGINT NOT NULL, \n\tcount INTEGER NOT NULL, \n\tPRIMARY KEY (key)\n)']


def upgrade():
    for statement in STATEMENTS:
        op.execute(statement)
    op.execute("""INSERT INTO users
        (id,username,display_name,kind,role,enabled,must_change_password,created_at)
        VALUES ('usr_ci','ci-bot','CI','service','member',true,false,CURRENT_TIMESTAMP),
        ('usr_system','system','后台系统','system','member',false,false,CURRENT_TIMESTAMP),
        ('usr_legacy','legacy-unknown','历史未知用户','legacy','member',false,false,CURRENT_TIMESTAMP)""")
    op.add_column('uploads', sa.Column('uploaded_by_user_id', sa.Text(), nullable=True))
    op.add_column('uploads', sa.Column('uploaded_by_name', sa.Text(), nullable=True))
    op.add_column('uploads', sa.Column('uploaded_by_username', sa.Text(), nullable=True))
    op.add_column('uploads', sa.Column('access_token_id', sa.Text(), nullable=True))
    op.execute("UPDATE uploads SET uploaded_by_user_id='usr_legacy', uploaded_by_name='历史未知用户', uploaded_by_username='legacy-unknown'")
    for column in ('uploaded_by_user_id','uploaded_by_name','uploaded_by_username'):
        op.alter_column('uploads', column, nullable=False)
    op.create_foreign_key('fk_uploads_user','uploads','users',['uploaded_by_user_id'],['id'])
    op.create_foreign_key('fk_uploads_token','uploads','access_tokens',['access_token_id'],['id'])
    op.create_index('ix_uploads_uploaded_by_user_id','uploads',['uploaded_by_user_id'])
    op.add_column('crash_groups', sa.Column('owner_user_id',sa.Text(),nullable=True))
    op.create_foreign_key('fk_groups_owner','crash_groups','users',['owner_user_id'],['id'])
    for table in ('operation_logs','catalog_pair_reviews','result_reviews','occurrence_version_audits'):
        op.add_column(table, sa.Column('actor_user_id',sa.Text(),nullable=True))
        op.add_column(table, sa.Column('actor_name',sa.Text(),nullable=True))
        if table in ('result_reviews','occurrence_version_audits'):
            op.execute(f"ALTER TABLE {table} DISABLE TRIGGER {table}_immutable")
        op.execute(f"UPDATE {table} SET actor_user_id='usr_legacy', actor_name='历史未知用户'")
        if table in ('result_reviews','occurrence_version_audits'):
            op.execute(f"ALTER TABLE {table} ENABLE TRIGGER {table}_immutable")
        op.alter_column(table,'actor_user_id',nullable=False)
        op.alter_column(table,'actor_name',nullable=False)
        op.create_foreign_key(f'fk_{table}_actor',table,'users',['actor_user_id'],['id'])
    op.drop_constraint('ck_operation_logs_actor','operation_logs',type_='check')
    op.alter_column('operation_logs','actor',server_default=None)
    op.add_column('operation_logs',sa.Column('auth_method',sa.Text(),nullable=True))
    op.add_column('operation_logs',sa.Column('credential_id',sa.Text(),nullable=True))
    op.execute("UPDATE operation_logs SET auth_method='legacy'")
    op.alter_column('operation_logs','auth_method',nullable=False)

    op.execute("""CREATE FUNCTION reject_upload_attribution_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
        IF (NEW.uploaded_by_user_id,NEW.uploaded_by_name,NEW.uploaded_by_username,NEW.access_token_id)
           IS DISTINCT FROM (OLD.uploaded_by_user_id,OLD.uploaded_by_name,OLD.uploaded_by_username,OLD.access_token_id)
        THEN RAISE EXCEPTION 'upload attribution is immutable'; END IF;
        RETURN NEW;
        END; $$""")
    op.execute("""CREATE TRIGGER uploads_attribution_immutable BEFORE UPDATE ON uploads
        FOR EACH ROW EXECUTE FUNCTION reject_upload_attribution_mutation()""")


def downgrade():
    raise RuntimeError("Restore the previous stack and database backup to roll back authentication")
