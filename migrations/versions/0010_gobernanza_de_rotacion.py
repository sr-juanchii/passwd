"""gobernanza de rotacion de credenciales

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-18 00:00:00.000000

Cambios **aditivos** de la v1.3.0:

- Tabla ``rotaciones_credencial``: libro mayor permanente del ciclo de
  gobernanza (quién pidió, quién autorizó, cuándo se rotó y con qué desviación).
- ``credenciales.via_rotacion`` y ``credenciales.usada_por``.
- ``registros_auditoria.hash_algoritmo``: distingue el tramo heredado
  (SHA-256 sin clave) del tramo firmado con HMAC a partir de esta versión.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# Identificadores de la revisión (usados por Alembic).
revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'rotaciones_credencial',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('credencial_id', sa.Integer(), nullable=True),
        sa.Column('activo_nombre', sa.String(length=120), nullable=False),
        sa.Column('usuario_acceso', sa.String(length=120), nullable=False),
        sa.Column('servicio', sa.String(length=60), nullable=False),
        sa.Column('estado', sa.String(length=20), server_default='solicitada', nullable=False),
        sa.Column('tipo', sa.String(length=20), nullable=False),
        sa.Column('solicitado_por_id', sa.Integer(), nullable=True),
        sa.Column('solicitado_por_username', sa.String(length=64), nullable=False),
        sa.Column('solicitado_en', sa.DateTime(), nullable=False),
        sa.Column('motivo', sa.Text(), nullable=False),
        sa.Column('dias_al_solicitar', sa.Integer(), nullable=True),
        sa.Column('dias_al_autorizar', sa.Integer(), nullable=True),
        sa.Column('temprana', sa.Boolean(), server_default=sa.text('0'), nullable=False),
        sa.Column('autorizado_por_id', sa.Integer(), nullable=True),
        sa.Column('autorizado_por_username', sa.String(length=64), nullable=False),
        sa.Column('autorizado_en', sa.DateTime(), nullable=True),
        sa.Column('reautenticado', sa.Boolean(), server_default=sa.text('0'), nullable=False),
        sa.Column('emergencia_sin_segundo_par', sa.Boolean(), server_default=sa.text('0'), nullable=False),
        sa.Column('revisada_por_id', sa.Integer(), nullable=True),
        sa.Column('revisada_en', sa.DateTime(), nullable=True),
        sa.Column('nota_revision', sa.Text(), nullable=False),
        sa.Column('rechazado_por_id', sa.Integer(), nullable=True),
        sa.Column('rechazado_en', sa.DateTime(), nullable=True),
        sa.Column('motivo_rechazo', sa.Text(), nullable=False),
        sa.Column('cancelado_por_id', sa.Integer(), nullable=True),
        sa.Column('cancelado_en', sa.DateTime(), nullable=True),
        sa.Column('fecha_programada', sa.DateTime(), nullable=True),
        sa.Column('ejecutado_en', sa.DateTime(), nullable=True),
        sa.Column('confirmado_en', sa.DateTime(), nullable=True),
        sa.Column('dias_al_rotar', sa.Integer(), nullable=True),
        sa.Column('desvio_dias', sa.Integer(), nullable=True),
        sa.Column('resultado', sa.String(length=20), server_default='', nullable=False),
        sa.Column('via', sa.String(length=20), server_default='manual', nullable=False),
        sa.Column('verificacion', sa.String(length=20), server_default='ninguna', nullable=False),
        sa.Column('detalle_error', sa.Text(), nullable=False),
        sa.CheckConstraint(
            "estado IN ('solicitada', 'autorizada', 'despachada', 'cerrada',"
            " 'rechazada', 'cancelada', 'expirada')",
            name='ck_rotaciones_estado',
        ),
        sa.CheckConstraint(
            "tipo IN ('programada', 'manual', 'emergencia', 'masiva')",
            name='ck_rotaciones_tipo',
        ),
        sa.CheckConstraint(
            "verificacion IN ('ninguna', 'local', 'remota')",
            name='ck_rotaciones_verificacion',
        ),
        sa.ForeignKeyConstraint(['credencial_id'], ['credenciales.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['solicitado_por_id'], ['usuarios.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['autorizado_por_id'], ['usuarios.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['revisada_por_id'], ['usuarios.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['rechazado_por_id'], ['usuarios.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['cancelado_por_id'], ['usuarios.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('rotaciones_credencial', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_rotaciones_credencial_credencial_id'),
                              ['credencial_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_rotaciones_credencial_estado'),
                              ['estado'], unique=False)
        batch_op.create_index(batch_op.f('ix_rotaciones_credencial_solicitado_en'),
                              ['solicitado_en'], unique=False)
        batch_op.create_index('ix_rotaciones_credencial_fecha',
                              ['credencial_id', 'solicitado_en'], unique=False)
        batch_op.create_index('ix_rotaciones_estado_fecha',
                              ['estado', 'solicitado_en'], unique=False)

    with op.batch_alter_table('credenciales', schema=None) as batch_op:
        batch_op.add_column(sa.Column('via_rotacion', sa.String(length=20),
                                      server_default='manual', nullable=False))
        batch_op.add_column(sa.Column('usada_por', sa.String(length=500),
                                      server_default='', nullable=False))

    with op.batch_alter_table('registros_auditoria', schema=None) as batch_op:
        batch_op.add_column(sa.Column('hash_algoritmo', sa.String(length=16),
                                      server_default='', nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('registros_auditoria', schema=None) as batch_op:
        batch_op.drop_column('hash_algoritmo')

    with op.batch_alter_table('credenciales', schema=None) as batch_op:
        batch_op.drop_column('usada_por')
        batch_op.drop_column('via_rotacion')

    with op.batch_alter_table('rotaciones_credencial', schema=None) as batch_op:
        batch_op.drop_index('ix_rotaciones_estado_fecha')
        batch_op.drop_index('ix_rotaciones_credencial_fecha')
        batch_op.drop_index(batch_op.f('ix_rotaciones_credencial_solicitado_en'))
        batch_op.drop_index(batch_op.f('ix_rotaciones_credencial_estado'))
        batch_op.drop_index(batch_op.f('ix_rotaciones_credencial_credencial_id'))

    op.drop_table('rotaciones_credencial')
