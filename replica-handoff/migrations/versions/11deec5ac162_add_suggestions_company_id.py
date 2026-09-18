"""add suggestions company_id

Revision ID: 11deec5ac162
Revises: dae87f6612b3
Create Date: 2026-09-18 11:56:36.449788

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '11deec5ac162'
down_revision: Union[str, Sequence[str], None] = 'dae87f6612b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('suggestions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('company_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_suggestions_company_id'), ['company_id'], unique=False)
        batch_op.create_foreign_key('fk_suggestions_company_id_companies', 'companies', ['company_id'], ['id'])


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('suggestions', schema=None) as batch_op:
        batch_op.drop_constraint('fk_suggestions_company_id_companies', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_suggestions_company_id'))
        batch_op.drop_column('company_id')
