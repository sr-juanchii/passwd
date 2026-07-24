"""dispositivos de red (switches, routers, firewalls…)

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-23 00:00:00.000000

Añade el activo de nivel superior ``dispositivos_red`` y la cuarta clave
foránea en ``credenciales`` y ``concesiones_acceso``. Las restricciones CHECK
«exactamente un activo» y la UNIQUE de concesiones cambian de tres a cuatro
términos, por lo que en SQLite ambas tablas se recrean en modo batch con
``copy_from`` explícito (la reflexión de SQLite no conserva los CHECK).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# Identificadores de la revisión (usados por Alembic).
revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def _tabla_credenciales(con_dispositivo: bool) -> sa.Table:
    """Definición de ``credenciales`` (espejo de 0001, ± dispositivo_red_id)."""
    metadata = sa.MetaData()
    columnas = [
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('servidor_fisico_id', sa.Integer(), nullable=True),
        sa.Column('hipervisor_id', sa.Integer(), nullable=True),
        sa.Column('maquina_virtual_id', sa.Integer(), nullable=True),
    ]
    if con_dispositivo:
        columnas.append(sa.Column('dispositivo_red_id', sa.Integer(), nullable=True))
    columnas += [
        sa.Column('usuario_acceso', sa.String(length=120), nullable=False),
        sa.Column('password_cifrada', sa.LargeBinary(), nullable=False),
        sa.Column('servicio', sa.String(length=60), nullable=False),
        sa.Column('puerto', sa.Integer(), nullable=True),
        sa.Column('descripcion', sa.Text(), nullable=False),
        sa.Column('creado_por_id', sa.Integer(), nullable=True),
        sa.Column('creado_en', sa.DateTime(), nullable=False),
        sa.Column('actualizado_en', sa.DateTime(), nullable=False),
        sa.Column('password_rotada_en', sa.DateTime(), nullable=False),
    ]
    restricciones = [
        sa.ForeignKeyConstraint(['creado_por_id'], ['usuarios.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['hipervisor_id'], ['hipervisores.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['maquina_virtual_id'], ['maquinas_virtuales.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['servidor_fisico_id'], ['servidores_fisicos.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.Index('ix_credenciales_hipervisor_id', 'hipervisor_id'),
        sa.Index('ix_credenciales_maquina_virtual_id', 'maquina_virtual_id'),
        sa.Index('ix_credenciales_servidor_fisico_id', 'servidor_fisico_id'),
    ]
    if con_dispositivo:
        restricciones += [
            sa.ForeignKeyConstraint(['dispositivo_red_id'], ['dispositivos_red.id'],
                                    name='fk_credenciales_dispositivo_red', ondelete='CASCADE'),
            sa.Index('ix_credenciales_dispositivo_red_id', 'dispositivo_red_id'),
            sa.CheckConstraint(
                '(CASE WHEN servidor_fisico_id IS NULL THEN 0 ELSE 1 END'
                ' + CASE WHEN hipervisor_id IS NULL THEN 0 ELSE 1 END'
                ' + CASE WHEN maquina_virtual_id IS NULL THEN 0 ELSE 1 END'
                ' + CASE WHEN dispositivo_red_id IS NULL THEN 0 ELSE 1 END) = 1',
                name='ck_credenciales_un_activo'),
        ]
    else:
        restricciones.append(sa.CheckConstraint(
            '(CASE WHEN servidor_fisico_id IS NULL THEN 0 ELSE 1 END'
            ' + CASE WHEN hipervisor_id IS NULL THEN 0 ELSE 1 END'
            ' + CASE WHEN maquina_virtual_id IS NULL THEN 0 ELSE 1 END) = 1',
            name='ck_credenciales_un_activo'))
    return sa.Table('credenciales', metadata, *columnas, *restricciones)


def _tabla_concesiones(con_dispositivo: bool) -> sa.Table:
    """Definición de ``concesiones_acceso`` (espejo de 0001, ± dispositivo_red_id)."""
    metadata = sa.MetaData()
    columnas = [
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('usuario_id', sa.Integer(), nullable=False),
        sa.Column('servidor_fisico_id', sa.Integer(), nullable=True),
        sa.Column('hipervisor_id', sa.Integer(), nullable=True),
        sa.Column('maquina_virtual_id', sa.Integer(), nullable=True),
    ]
    if con_dispositivo:
        columnas.append(sa.Column('dispositivo_red_id', sa.Integer(), nullable=True))
    columnas += [
        sa.Column('nivel', sa.String(length=20), nullable=False),
        sa.Column('concedido_por_id', sa.Integer(), nullable=True),
        sa.Column('creado_en', sa.DateTime(), nullable=False),
        sa.Column('expira_en', sa.DateTime(), nullable=True),
    ]
    restricciones = [
        sa.CheckConstraint("nivel IN ('ver', 'ver_credenciales')", name='ck_concesiones_nivel'),
        sa.ForeignKeyConstraint(['concedido_por_id'], ['usuarios.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['hipervisor_id'], ['hipervisores.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['maquina_virtual_id'], ['maquinas_virtuales.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['servidor_fisico_id'], ['servidores_fisicos.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.Index('ix_concesiones_acceso_hipervisor_id', 'hipervisor_id'),
        sa.Index('ix_concesiones_acceso_maquina_virtual_id', 'maquina_virtual_id'),
        sa.Index('ix_concesiones_acceso_servidor_fisico_id', 'servidor_fisico_id'),
        sa.Index('ix_concesiones_acceso_usuario_id', 'usuario_id'),
    ]
    if con_dispositivo:
        restricciones += [
            sa.ForeignKeyConstraint(['dispositivo_red_id'], ['dispositivos_red.id'],
                                    name='fk_concesiones_dispositivo_red', ondelete='CASCADE'),
            sa.Index('ix_concesiones_acceso_dispositivo_red_id', 'dispositivo_red_id'),
            sa.CheckConstraint(
                '(CASE WHEN servidor_fisico_id IS NULL THEN 0 ELSE 1 END'
                ' + CASE WHEN hipervisor_id IS NULL THEN 0 ELSE 1 END'
                ' + CASE WHEN maquina_virtual_id IS NULL THEN 0 ELSE 1 END'
                ' + CASE WHEN dispositivo_red_id IS NULL THEN 0 ELSE 1 END) = 1',
                name='ck_concesiones_un_activo'),
            sa.UniqueConstraint('usuario_id', 'servidor_fisico_id', 'hipervisor_id',
                                'maquina_virtual_id', 'dispositivo_red_id',
                                name='uq_concesion_usuario_activo'),
        ]
    else:
        restricciones += [
            sa.CheckConstraint(
                '(CASE WHEN servidor_fisico_id IS NULL THEN 0 ELSE 1 END'
                ' + CASE WHEN hipervisor_id IS NULL THEN 0 ELSE 1 END'
                ' + CASE WHEN maquina_virtual_id IS NULL THEN 0 ELSE 1 END) = 1',
                name='ck_concesiones_un_activo'),
            sa.UniqueConstraint('usuario_id', 'servidor_fisico_id', 'hipervisor_id',
                                'maquina_virtual_id', name='uq_concesion_usuario_activo'),
        ]
    return sa.Table('concesiones_acceso', metadata, *columnas, *restricciones)


def upgrade() -> None:
    op.create_table('dispositivos_red',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('nombre', sa.String(length=120), nullable=False),
    sa.Column('tipo_dispositivo', sa.String(length=20), server_default='switch', nullable=False),
    sa.Column('marca_modelo', sa.String(length=120), server_default='', nullable=False),
    sa.Column('version', sa.String(length=60), server_default='', nullable=False),
    sa.Column('ip_gestion', sa.String(length=45), nullable=False),
    sa.Column('ubicacion', sa.String(length=120), server_default='', nullable=False),
    sa.Column('puertos', sa.String(length=120), server_default='', nullable=False),
    sa.Column('descripcion', sa.Text(), nullable=False),
    sa.Column('numero_serie', sa.String(length=120), server_default='', nullable=False),
    sa.Column('garantia_hasta', sa.String(length=40), server_default='', nullable=False),
    sa.Column('proveedor', sa.String(length=120), server_default='', nullable=False),
    sa.Column('estado', sa.String(length=20), server_default='activo', nullable=False),
    sa.Column('etiquetas', sa.String(length=255), server_default='', nullable=False),
    sa.Column('notas_cifradas', sa.LargeBinary(), nullable=True),
    sa.Column('creado_en', sa.DateTime(), nullable=False),
    sa.Column('actualizado_en', sa.DateTime(), nullable=False),
    sa.CheckConstraint(
        "tipo_dispositivo IN ('switch', 'router', 'firewall', 'access_point', 'balanceador', 'otro')",
        name='ck_dispositivos_red_tipo'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('nombre')
    )

    with op.batch_alter_table('credenciales', schema=None,
                              copy_from=_tabla_credenciales(con_dispositivo=False)) as batch_op:
        batch_op.add_column(sa.Column('dispositivo_red_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_credenciales_dispositivo_red_id'),
                              ['dispositivo_red_id'], unique=False)
        batch_op.create_foreign_key('fk_credenciales_dispositivo_red', 'dispositivos_red',
                                    ['dispositivo_red_id'], ['id'], ondelete='CASCADE')
        batch_op.drop_constraint('ck_credenciales_un_activo', type_='check')
        batch_op.create_check_constraint(
            'ck_credenciales_un_activo',
            '(CASE WHEN servidor_fisico_id IS NULL THEN 0 ELSE 1 END'
            ' + CASE WHEN hipervisor_id IS NULL THEN 0 ELSE 1 END'
            ' + CASE WHEN maquina_virtual_id IS NULL THEN 0 ELSE 1 END'
            ' + CASE WHEN dispositivo_red_id IS NULL THEN 0 ELSE 1 END) = 1')

    with op.batch_alter_table('concesiones_acceso', schema=None,
                              copy_from=_tabla_concesiones(con_dispositivo=False)) as batch_op:
        batch_op.add_column(sa.Column('dispositivo_red_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_concesiones_acceso_dispositivo_red_id'),
                              ['dispositivo_red_id'], unique=False)
        batch_op.create_foreign_key('fk_concesiones_dispositivo_red', 'dispositivos_red',
                                    ['dispositivo_red_id'], ['id'], ondelete='CASCADE')
        batch_op.drop_constraint('ck_concesiones_un_activo', type_='check')
        batch_op.create_check_constraint(
            'ck_concesiones_un_activo',
            '(CASE WHEN servidor_fisico_id IS NULL THEN 0 ELSE 1 END'
            ' + CASE WHEN hipervisor_id IS NULL THEN 0 ELSE 1 END'
            ' + CASE WHEN maquina_virtual_id IS NULL THEN 0 ELSE 1 END'
            ' + CASE WHEN dispositivo_red_id IS NULL THEN 0 ELSE 1 END) = 1')
        batch_op.drop_constraint('uq_concesion_usuario_activo', type_='unique')
        batch_op.create_unique_constraint(
            'uq_concesion_usuario_activo',
            ['usuario_id', 'servidor_fisico_id', 'hipervisor_id',
             'maquina_virtual_id', 'dispositivo_red_id'])


def downgrade() -> None:
    # Solo es seguro si no hay dispositivos de red (ni credenciales/concesiones
    # colgando de ellos); de haberlos, el borrado en cascada los eliminaría.
    with op.batch_alter_table('concesiones_acceso', schema=None,
                              copy_from=_tabla_concesiones(con_dispositivo=True)) as batch_op:
        batch_op.drop_constraint('uq_concesion_usuario_activo', type_='unique')
        batch_op.drop_constraint('ck_concesiones_un_activo', type_='check')
        batch_op.drop_constraint('fk_concesiones_dispositivo_red', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_concesiones_acceso_dispositivo_red_id'))
        batch_op.drop_column('dispositivo_red_id')
        batch_op.create_check_constraint(
            'ck_concesiones_un_activo',
            '(CASE WHEN servidor_fisico_id IS NULL THEN 0 ELSE 1 END'
            ' + CASE WHEN hipervisor_id IS NULL THEN 0 ELSE 1 END'
            ' + CASE WHEN maquina_virtual_id IS NULL THEN 0 ELSE 1 END) = 1')
        batch_op.create_unique_constraint(
            'uq_concesion_usuario_activo',
            ['usuario_id', 'servidor_fisico_id', 'hipervisor_id', 'maquina_virtual_id'])

    with op.batch_alter_table('credenciales', schema=None,
                              copy_from=_tabla_credenciales(con_dispositivo=True)) as batch_op:
        batch_op.drop_constraint('ck_credenciales_un_activo', type_='check')
        batch_op.drop_constraint('fk_credenciales_dispositivo_red', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_credenciales_dispositivo_red_id'))
        batch_op.drop_column('dispositivo_red_id')
        batch_op.create_check_constraint(
            'ck_credenciales_un_activo',
            '(CASE WHEN servidor_fisico_id IS NULL THEN 0 ELSE 1 END'
            ' + CASE WHEN hipervisor_id IS NULL THEN 0 ELSE 1 END'
            ' + CASE WHEN maquina_virtual_id IS NULL THEN 0 ELSE 1 END) = 1')

    op.drop_table('dispositivos_red')
