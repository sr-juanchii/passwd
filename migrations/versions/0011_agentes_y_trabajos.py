"""agentes de rotacion, trabajos despachados y telemetria

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-25 00:00:00.000000

Cambios **aditivos** de la v1.4.0 (docs/plan-rotacion-agentes.md §3.1):

- Tabla ``agentes``: un agente por activo Linux, con identidad de vida corta y
  enrolamiento de un solo uso.
- Tabla ``trabajos_rotacion``: trabajo cifrado al agente, con los secretos
  purgables y como máximo uno activo por agente.
- Tabla ``telemetria_agente``: latido con métricas agregadas del host.
- ``rotaciones_credencial.agente_id``, ``agente_nombre`` y
  ``clave_agente_huella``: qué agente ejecutó la rotación y con qué clave.
  ``agente_id`` va sin clave foránea a propósito (ver el modelo).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# Identificadores de la revisión (usados por Alembic).
revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'agentes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('nombre', sa.String(length=120), nullable=False),
        sa.Column('servidor_fisico_id', sa.Integer(), nullable=True),
        sa.Column('hipervisor_id', sa.Integer(), nullable=True),
        sa.Column('maquina_virtual_id', sa.Integer(), nullable=True),
        sa.Column('vinculo_vigente', sa.String(length=40), nullable=True),
        sa.Column('estado', sa.String(length=20), server_default='pendiente', nullable=False),
        sa.Column('enrolamiento_hash', sa.String(length=64), nullable=True),
        sa.Column('enrolamiento_expira_en', sa.DateTime(), nullable=True),
        sa.Column('enrolado_en', sa.DateTime(), nullable=True),
        sa.Column('token_hash', sa.String(length=64), nullable=True),
        sa.Column('token_expira_en', sa.DateTime(), nullable=True),
        sa.Column('token_anterior_hash', sa.String(length=64), nullable=True),
        sa.Column('token_anterior_expira_en', sa.DateTime(), nullable=True),
        sa.Column('token_renovado_en', sa.DateTime(), nullable=True),
        sa.Column('ip_ultima_renovacion', sa.String(length=45), server_default='', nullable=False),
        sa.Column('clave_publica', sa.String(length=64), server_default='', nullable=False),
        sa.Column('clave_huella', sa.String(length=64), server_default='', nullable=False),
        sa.Column('nombre_host', sa.String(length=255), server_default='', nullable=False),
        sa.Column('version_agente', sa.String(length=40), server_default='', nullable=False),
        sa.Column('ultimo_contacto_en', sa.DateTime(), nullable=True),
        sa.Column('ip_ultimo_contacto', sa.String(length=45), server_default='', nullable=False),
        sa.Column('rotacion_habilitada', sa.Boolean(), server_default=sa.text('1'), nullable=False),
        sa.Column('creado_por_id', sa.Integer(), nullable=True),
        sa.Column('creado_en', sa.DateTime(), nullable=False),
        sa.Column('revocado_por_id', sa.Integer(), nullable=True),
        sa.Column('revocado_en', sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "(CASE WHEN servidor_fisico_id IS NULL THEN 0 ELSE 1 END"
            " + CASE WHEN hipervisor_id IS NULL THEN 0 ELSE 1 END"
            " + CASE WHEN maquina_virtual_id IS NULL THEN 0 ELSE 1 END) = 1",
            name='ck_agentes_un_activo',
        ),
        sa.CheckConstraint(
            "estado IN ('pendiente', 'activo', 'revocado')", name='ck_agentes_estado'
        ),
        sa.ForeignKeyConstraint(['servidor_fisico_id'], ['servidores_fisicos.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['hipervisor_id'], ['hipervisores.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['maquina_virtual_id'], ['maquinas_virtuales.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['creado_por_id'], ['usuarios.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['revocado_por_id'], ['usuarios.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('nombre'),
        sa.UniqueConstraint('vinculo_vigente'),
        sa.UniqueConstraint('enrolamiento_hash'),
        sa.UniqueConstraint('token_anterior_hash'),
    )
    with op.batch_alter_table('agentes', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_agentes_servidor_fisico_id'), ['servidor_fisico_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_agentes_hipervisor_id'), ['hipervisor_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_agentes_maquina_virtual_id'), ['maquina_virtual_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_agentes_estado'), ['estado'], unique=False)
        batch_op.create_index(batch_op.f('ix_agentes_token_hash'), ['token_hash'], unique=True)

    op.create_table(
        'trabajos_rotacion',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('agente_id', sa.Integer(), nullable=False),
        sa.Column('credencial_id', sa.Integer(), nullable=False),
        sa.Column('rotacion_id', sa.Integer(), nullable=False),
        sa.Column('activo_agente_id', sa.Integer(), nullable=True),
        sa.Column('estado', sa.String(length=20), server_default='pendiente', nullable=False),
        sa.Column('nueva_cifrada', sa.LargeBinary(), nullable=True),
        sa.Column('actual_cifrada', sa.LargeBinary(), nullable=True),
        sa.Column('clave_huella', sa.String(length=64), server_default='', nullable=False),
        sa.Column('ventana_expira_en', sa.DateTime(), nullable=False),
        sa.Column('intentos', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('disparado_por_id', sa.Integer(), nullable=True),
        sa.Column('creado_en', sa.DateTime(), nullable=False),
        sa.Column('entregado_en', sa.DateTime(), nullable=True),
        sa.Column('confirmado_en', sa.DateTime(), nullable=True),
        sa.Column('verificacion', sa.String(length=20), server_default='ninguna', nullable=False),
        sa.Column('detalle_error', sa.Text(), nullable=False),
        sa.CheckConstraint(
            "estado IN ('pendiente', 'entregado', 'aplicado', 'revertido',"
            " 'fallado', 'expirado', 'cancelado')",
            name='ck_trabajos_estado',
        ),
        sa.CheckConstraint(
            "verificacion IN ('ninguna', 'local', 'remota')", name='ck_trabajos_verificacion'
        ),
        sa.ForeignKeyConstraint(['agente_id'], ['agentes.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['credencial_id'], ['credenciales.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['rotacion_id'], ['rotaciones_credencial.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['disparado_por_id'], ['usuarios.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('activo_agente_id'),
    )
    with op.batch_alter_table('trabajos_rotacion', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_trabajos_rotacion_agente_id'), ['agente_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_trabajos_rotacion_credencial_id'), ['credencial_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_trabajos_rotacion_rotacion_id'), ['rotacion_id'], unique=False)
        batch_op.create_index('ix_trabajos_agente_estado', ['agente_id', 'estado'], unique=False)

    op.create_table(
        'telemetria_agente',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('agente_id', sa.Integer(), nullable=False),
        sa.Column('fecha', sa.DateTime(), nullable=False),
        sa.Column('cpu_pct', sa.Integer(), nullable=True),
        sa.Column('ram_pct', sa.Integer(), nullable=True),
        sa.Column('disco_pct', sa.Integer(), nullable=True),
        sa.Column('uptime_s', sa.BigInteger(), nullable=True),
        sa.Column('sistema_operativo', sa.String(length=120), server_default='', nullable=False),
        sa.Column('kernel', sa.String(length=120), server_default='', nullable=False),
        sa.Column('cpu_modelo', sa.String(length=120), server_default='', nullable=False),
        sa.Column('ram_total', sa.BigInteger(), nullable=True),
        sa.Column('discos_json', sa.Text(), nullable=False),
        sa.Column('recortada', sa.Boolean(), server_default=sa.text('0'), nullable=False),
        sa.ForeignKeyConstraint(['agente_id'], ['agentes.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('telemetria_agente', schema=None) as batch_op:
        batch_op.create_index('ix_telemetria_agente_fecha', ['agente_id', 'fecha'], unique=False)

    with op.batch_alter_table('rotaciones_credencial', schema=None) as batch_op:
        batch_op.add_column(sa.Column('agente_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('agente_nombre', sa.String(length=120),
                                      server_default='', nullable=False))
        batch_op.add_column(sa.Column('clave_agente_huella', sa.String(length=64),
                                      server_default='', nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('rotaciones_credencial', schema=None) as batch_op:
        batch_op.drop_column('clave_agente_huella')
        batch_op.drop_column('agente_nombre')
        batch_op.drop_column('agente_id')

    with op.batch_alter_table('telemetria_agente', schema=None) as batch_op:
        batch_op.drop_index('ix_telemetria_agente_fecha')
    op.drop_table('telemetria_agente')

    with op.batch_alter_table('trabajos_rotacion', schema=None) as batch_op:
        batch_op.drop_index('ix_trabajos_agente_estado')
        batch_op.drop_index(batch_op.f('ix_trabajos_rotacion_rotacion_id'))
        batch_op.drop_index(batch_op.f('ix_trabajos_rotacion_credencial_id'))
        batch_op.drop_index(batch_op.f('ix_trabajos_rotacion_agente_id'))
    op.drop_table('trabajos_rotacion')

    with op.batch_alter_table('agentes', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_agentes_token_hash'))
        batch_op.drop_index(batch_op.f('ix_agentes_estado'))
        batch_op.drop_index(batch_op.f('ix_agentes_maquina_virtual_id'))
        batch_op.drop_index(batch_op.f('ix_agentes_hipervisor_id'))
        batch_op.drop_index(batch_op.f('ix_agentes_servidor_fisico_id'))
    op.drop_table('agentes')
