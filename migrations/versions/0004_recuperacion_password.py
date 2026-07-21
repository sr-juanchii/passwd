"""desafio de auto-recuperacion de contrasena

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-15 14:40:00.000000

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# Identificadores de la revisión (usados por Alembic).
revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'recuperaciones_password',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('usuario_id', sa.Integer(), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('csrf_token', sa.String(length=64), nullable=False),
        sa.Column('creado_en', sa.DateTime(), nullable=False),
        sa.Column('expira_en', sa.DateTime(), nullable=False),
        sa.Column('intentos', sa.Integer(), nullable=False),
        sa.Column('verificado_en', sa.DateTime(), nullable=True),
        sa.Column('consumido_en', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('recuperaciones_password', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_recuperaciones_password_usuario_id'), ['usuario_id'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_recuperaciones_password_token_hash'), ['token_hash'], unique=True
        )


def downgrade() -> None:
    with op.batch_alter_table('recuperaciones_password', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_recuperaciones_password_token_hash'))
        batch_op.drop_index(batch_op.f('ix_recuperaciones_password_usuario_id'))
    op.drop_table('recuperaciones_password')
