FROM python:3.12-slim

# Usuario sin privilegios (CIS 4.x — configuración segura)
RUN groupadd --gid 1001 passwd && useradd --uid 1001 --gid 1001 --create-home passwd

WORKDIR /srv/passwd

COPY requirements.txt ./
# Tolerante a redes lentas: más tiempo de lectura y reintentos por paquete
RUN pip install --no-cache-dir --timeout 120 --retries 10 -r requirements.txt

COPY app ./app

RUN mkdir -p /srv/passwd/data && chown -R passwd:passwd /srv/passwd
USER passwd

ENV PASSWD_DATA_DIR=/srv/passwd/data

# Muchos PaaS gratuitos (Render, Koyeb, Railway, Fly…) inyectan el puerto en
# $PORT y terminan el TLS por delante: respetamos $PORT (8000 por defecto) y
# confiamos en las cabeceras de reenvío para registrar la IP real del cliente.
ENV PORT=8000
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import os,urllib.request,sys; p=os.environ.get('PORT','8000'); sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{p}/healthz', timeout=3).status == 200 else 1)"

CMD ["sh", "-c", "exec python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips=*"]
