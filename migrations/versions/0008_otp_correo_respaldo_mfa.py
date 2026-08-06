"""otp por correo como respaldo del mfa

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-06 03:10:00.000000

Añade la tabla de códigos OTP de un solo uso enviados al correo, que permiten
completar el segundo factor cuando el usuario no tiene acceso a su aplicación
autenticadora. Solo se persiste el hash SHA-256 del código.

No toca ninguna tabla existente ni ningún dato, así que la actualización es
segura en caliente y el downgrade se limita a eliminar la tabla nueva.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# Identificadores de la revisión (usados por Alembic).
revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'codigos_otp_correo',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('usuario_id', sa.Integer(), nullable=False),
        sa.Column('codigo_hash', sa.String(length=64), nullable=False),
        sa.Column('creado_en', sa.DateTime(), nullable=False),
        sa.Column('expira_en', sa.DateTime(), nullable=False),
        sa.Column('intentos', sa.Integer(), nullable=False),
        sa.Column('usado_en', sa.DateTime(), nullable=True),
        sa.Column('invalidado_en', sa.DateTime(), nullable=True),
        sa.Column('direccion_ip', sa.String(length=45), nullable=False),
        sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('codigos_otp_correo', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_codigos_otp_correo_usuario_id'), ['usuario_id'], unique=False
        )
        # No único: un mismo hash podría repetirse entre usuarios o en el tiempo;
        # la búsqueda siempre acota por usuario_id + estado.
        batch_op.create_index(
            batch_op.f('ix_codigos_otp_correo_codigo_hash'), ['codigo_hash'], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table('codigos_otp_correo', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_codigos_otp_correo_codigo_hash'))
        batch_op.drop_index(batch_op.f('ix_codigos_otp_correo_usuario_id'))
    op.drop_table('codigos_otp_correo')
