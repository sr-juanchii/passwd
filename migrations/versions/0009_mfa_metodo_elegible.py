"""metodo de mfa elegible por usuario

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-10 17:30:00.000000

Cada usuario elige su método principal de segundo factor: aplicación
autenticadora (``totp``) o código enviado a su correo (``correo``). Las cuentas
existentes conservan ``totp``. Se añade además el paso temporal del último TOTP
aceptado, para rechazar la reutilización de códigos de pasos anteriores.

Cambio aditivo: no altera datos existentes.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# Identificadores de la revisión (usados por Alembic).
revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('usuarios', schema=None) as batch_op:
        batch_op.add_column(sa.Column('ultimo_totp_paso', sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column('mfa_metodo', sa.String(length=8), server_default='totp', nullable=False)
        )


def downgrade() -> None:
    with op.batch_alter_table('usuarios', schema=None) as batch_op:
        batch_op.drop_column('mfa_metodo')
        batch_op.drop_column('ultimo_totp_paso')
