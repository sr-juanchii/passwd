"""activos restringidos a administradores

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-24 00:00:00.000000

Añade la marca ``restringido`` a los tres activos de nivel superior: un activo
restringido solo lo ven los administradores (operadores y auditores lo tratan
como inexistente); las máquinas virtuales heredan la restricción de su
hipervisor, por lo que no llevan columna propia. Cambio aditivo puro.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# Identificadores de la revisión (usados por Alembic).
revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None

_TABLAS = ('servidores_fisicos', 'hipervisores', 'dispositivos_red')


def upgrade() -> None:
    for tabla in _TABLAS:
        with op.batch_alter_table(tabla, schema=None) as batch_op:
            batch_op.add_column(
                sa.Column('restringido', sa.Boolean(), server_default=sa.text('0'), nullable=False)
            )


def downgrade() -> None:
    for tabla in _TABLAS:
        with op.batch_alter_table(tabla, schema=None) as batch_op:
            batch_op.drop_column('restringido')
