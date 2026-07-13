# ── Etapa de construcción: instala dependencias aisladas en un prefijo ───────
FROM python:3.12-slim AS builder

WORKDIR /build
COPY requirements.txt ./
# Instala en un prefijo copiable (no arrastra el toolchain a la imagen final).
RUN pip install --no-cache-dir --prefix=/install --timeout 120 --retries 10 -r requirements.txt

# ── Etapa de ejecución: imagen mínima con usuario sin privilegios ────────────
FROM python:3.12-slim

# Usuario sin privilegios (CIS 4.x — configuración segura)
RUN groupadd --gid 1001 passwd && useradd --uid 1001 --gid 1001 --create-home passwd

WORKDIR /srv/passwd

# Copia solo las dependencias ya instaladas desde la etapa de construcción.
COPY --from=builder /install /usr/local

COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./alembic.ini

RUN mkdir -p /srv/passwd/data && chown -R passwd:passwd /srv/passwd
USER passwd

ENV PASSWD_DATA_DIR=/srv/passwd/data

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3).status == 200 else 1)"

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
