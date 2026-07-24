"""configuración en tiempo de ejecución

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-24 12:00:00.000000

Añade la tabla ``configuracion`` (clave/valor) que almacena los *overrides* de
los ajustes operativos editables por el administrador. Cambio aditivo puro.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# Identificadores de la revisión (usados por Alembic).
revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'configuracion',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('clave', sa.String(length=64), nullable=False),
        sa.Column('valor', sa.Text(), nullable=False),
        sa.Column('es_secreto', sa.Boolean(), server_default=sa.text('0'), nullable=False),
        sa.Column('actualizado_en', sa.DateTime(), nullable=False),
        sa.Column('actualizado_por_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['actualizado_por_id'], ['usuarios.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('configuracion', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_configuracion_clave'), ['clave'], unique=True)


def downgrade() -> None:
    with op.batch_alter_table('configuracion', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_configuracion_clave'))
    op.drop_table('configuracion')
