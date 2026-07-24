"""Verificación funcional end-to-end de la API JSON /api/web.

Ejercita CADA función para confirmar que el frontend Next.js puede operar todo
lo que hacía la web Jinja (auth+MFA, inventario, credenciales, rotación e
historial, notas, control de acceso por objeto, usuarios, tokens vía /api/v1,
auditoría + export CSV, métricas, búsqueda, importación CSV y cascadas).

Usa el TestClient en proceso (no necesita servidor ni red). Ejecutar desde la
raíz del repo con las dependencias instaladas:

    pip install -r requirements.txt -r requirements-dev.txt
    python scripts/verificar_api_web.py

Sale con código 0 si todo pasa; 1 si alguna comprobación falla.
"""
import os, tempfile, sys
from pathlib import Path

# Permite ejecutarlo como `python scripts/verificar_api_web.py` desde la raíz.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ["PASSWD_DATA_DIR"] = tempfile.mkdtemp()
# Respeta una URL ya definida (p. ej. MySQL en CI) para verificar cross-engine;
# si no, usa un SQLite temporal.
os.environ.setdefault("PASSWD_DATABASE_URL", f"sqlite:///{os.environ['PASSWD_DATA_DIR']}/v.db")
os.environ["PASSWD_ADMIN_USERNAME"] = "admin"
os.environ["PASSWD_ADMIN_EMAIL"] = "admin@example.com"
os.environ["PASSWD_ADMIN_PASSWORD"] = "ClaveInicialRobusta!9"
os.environ["PASSWD_COOKIE_SECURE"] = "false"

import pyotp
from starlette.testclient import TestClient
from app.main import create_app
from app.database import get_db
from app.security.crypto import descifrar
from app.models import Usuario
from sqlalchemy import select

fallos = []
def check(nombre, cond, extra=""):
    estado = "OK " if cond else "FALLO"
    if not cond:
        fallos.append(nombre)
    print(f"[{estado}] {nombre} {extra}")

app = create_app()

def secreto_de(username):
    db = next(get_db())
    u = db.scalar(select(Usuario).where(Usuario.username == username))
    s = descifrar(u.totp_secret_cifrado)
    db.close()
    return s

def login_completo(c, username, password, nueva=None):
    """Hace el ciclo login -> (cambio) -> enrol/verif MFA hasta sesión activa."""
    csrf = c.get("/api/web/csrf").json()["csrf_login"]
    r = c.post("/api/web/login", json={"username": username, "password": password, "csrf_login": csrf})
    assert r.status_code == 200, r.text
    stage = r.json()["stage"]
    tok = c.get("/api/web/session").json()["csrf_token"]
    if stage == "cambio_password":
        r = c.post("/api/web/password/cambiar", headers={"X-CSRF-Token": tok},
                   json={"password_actual": password, "password_nueva": nueva, "password_confirmacion": nueva})
        assert r.status_code == 200, r.text
        stage = r.json().get("stage")
        tok = c.get("/api/web/session").json()["csrf_token"]
    if stage == "mfa_enrolamiento":
        c.get("/api/web/mfa/configurar")
        code = pyotp.TOTP(secreto_de(username)).now()
        r = c.post("/api/web/mfa/configurar", headers={"X-CSRF-Token": tok}, json={"codigo": code})
        assert r.status_code == 200, r.text
        codigos = r.json()["codigos_recuperacion"]
    else:
        codigos = None
    if stage == "mfa_pendiente":
        code = pyotp.TOTP(secreto_de(username)).now()
        r = c.post("/api/web/mfa/verificar", headers={"X-CSRF-Token": tok}, json={"codigo": code})
        assert r.status_code == 200, r.text
    tok = c.get("/api/web/session").json()["csrf_token"]
    return tok, codigos

# === 1. Admin: ciclo completo de auth ===
admin = TestClient(app)
tok, recovery_admin = login_completo(admin, "admin", "ClaveInicialRobusta!9", nueva="Cl4veMaestra!Segura26")
s = admin.get("/api/web/session").json()
check("auth admin -> sesión activa", s["stage"] == "activa" and s["authenticated"])
check("admin tiene 14 permisos", sum(1 for v in s["permisos"].values() if v) == 14)
H = {"X-CSRF-Token": tok}

# === 2. Inventario: servidor dedicado + hipervisor de nivel superior -> vm + credenciales ===
r = admin.post("/api/web/servidores", headers=H, json={"nombre":"srv-dedicado","descripcion":"BD nómina","sistema_operativo":"Debian","marca_modelo":"Dell","ubicacion":"CPD","ip_gestion":"10.0.0.1","ram":"64GB","cpu":"Xeon","almacenamiento":"2TB","numero_serie":"SN1","garantia_hasta":"2027-01-01","proveedor":"Dell","estado":"activo","etiquetas":"prod, critico"})
host_id = r.json()["id"]; check("crear servidor dedicado", r.status_code == 200)
r = admin.post("/api/web/hipervisores", headers=H, json={"nombre":"pve-01","plataforma":"Proxmox VE","version":"8.1","ip_gestion":"10.0.0.2","descripcion":"","marca_modelo":"HPE","ubicacion":"CPD","ram":"256GB","cpu":"2x Xeon","almacenamiento":"8TB","numero_serie":"SN2","garantia_hasta":"2028-01-01","proveedor":"HPE","estado":"activo","etiquetas":"virt"})
hv_id = r.json()["id"]; check("crear hipervisor (nivel superior)", r.status_code == 200)
r = admin.post(f"/api/web/hipervisores/{hv_id}/vms", headers=H, json={"nombre":"vm-web","sistema_operativo":"Ubuntu 24.04","ip":"10.0.1.5","descripcion":"web","ram":"8 GB","cpu":"4 vCPU","almacenamiento":"120 GB","estado":"activo","etiquetas":"web"})
vm_id = r.json()["id"]; check("crear VM", r.status_code == 200)
r = admin.get(f"/api/web/vms/{vm_id}")
check("VM expone specs ram/cpu/almacenamiento", r.status_code == 200 and r.json().get("ram")=="8 GB" and r.json().get("cpu")=="4 vCPU" and r.json().get("almacenamiento")=="120 GB")

r = admin.post("/api/web/credenciales", headers=H, json={"activo":"hipervisor","activo_id":hv_id,"usuario_acceso":"root","password":"PwdHv!2026xyz","servicio":"SSH","puerto":22,"descripcion":"root pve"})
cred_hv = r.json()["id"]; check("credencial en hipervisor", r.status_code == 200)
r = admin.post("/api/web/credenciales", headers=H, json={"activo":"vm","activo_id":vm_id,"usuario_acceso":"deploy","password":"PwdVm!2026xyz","servicio":"SSH","puerto":22,"descripcion":"deploy vm"})
cred_vm = r.json()["id"]; check("credencial en VM", r.status_code == 200)

# === 3. Revelar / copiar (auditado) ===
r = admin.post(f"/api/web/credenciales/{cred_vm}/revelar", headers=H)
check("revelar credencial", r.status_code == 200 and r.json()["password"] == "PwdVm!2026xyz" and r.headers.get("cache-control") == "no-store")
r = admin.post(f"/api/web/credenciales/{cred_vm}/copiar", headers=H)
check("copiar credencial", r.status_code == 200 and r.json()["password"] == "PwdVm!2026xyz")

# === 4. Rotación -> historial ===
r = admin.put(f"/api/web/credenciales/{cred_vm}", headers=H, json={"usuario_acceso":"deploy","password":"PwdVm!ROTADA2026","servicio":"SSH","puerto":22,"descripcion":"deploy vm"})
check("rotar credencial (editar password)", r.status_code == 200)
r = admin.get(f"/api/web/credenciales/{cred_vm}")
hist = r.json()["historial"]
check("historial tras rotación", len(hist) == 1)
if hist:
    r = admin.post(f"/api/web/credenciales/{cred_vm}/historial/{hist[0]['id']}/revelar", headers=H)
    check("revelar historial", r.status_code == 200 and r.json()["password"] == "PwdVm!2026xyz")

# === 5. Notas seguras ===
r = admin.put(f"/api/web/activos/vm/{vm_id}/notas", headers=H, json={"contenido":"clave maestra de respaldo: XYZ"})
check("guardar nota", r.status_code == 200)
r = admin.get(f"/api/web/activos/vm/{vm_id}/notas")
check("estado nota (tiene_notas)", r.status_code == 200 and r.json()["tiene_notas"] is True)
r = admin.post(f"/api/web/activos/vm/{vm_id}/notas/revelar", headers=H)
check("revelar nota", r.status_code == 200 and "respaldo" in r.json()["notas"])

# === 6. Usuarios: crear analista, operador, auditor ===
def crear_usuario(u, e, rol):
    r = admin.post("/api/web/usuarios", headers=H, json={"username":u,"email":e,"nombre_completo":u.title(),"rol":rol})
    return r
r = crear_usuario("ana","ana@example.com","analista"); ana_pwd = r.json()["password_temporal"]; check("crear analista", r.status_code == 200)
r = crear_usuario("ope","ope@example.com","operador"); ope_pwd = r.json()["password_temporal"]; check("crear operador", r.status_code == 200)
r = crear_usuario("aud","aud@example.com","auditor"); check("crear auditor", r.status_code == 200)
r = admin.get("/api/web/usuarios"); check("listar usuarios (4)", len(r.json()["usuarios"]) == 4)

# ana_id
db = next(get_db()); ana = db.scalar(select(Usuario).where(Usuario.username=="ana")); ana_id = ana.id; db.close()

# === 7. Control de acceso por objeto: analista no ve nada hasta concesión ===
ana_c = TestClient(app)
tok_ana, _ = login_completo(ana_c, "ana", ana_pwd, nueva="Zx9KlmpQrst!uv26")
Ha = {"X-CSRF-Token": tok_ana}
r = ana_c.get("/api/web/dashboard"); dash = r.json()
check("analista dashboard es_analista", dash.get("es_analista") is True and len(dash.get("concesiones",[]))==0)
r = ana_c.get(f"/api/web/vms/{vm_id}")
check("analista SIN concesión -> 403/404 en VM", r.status_code in (403,404))

# admin concede acceso 'ver_credenciales' a la VM
r = admin.post("/api/web/accesos/conceder", headers=H, json={"usuario_id":ana_id,"tipo":"vm","activo_id":vm_id,"nivel":"ver_credenciales","expira_dias":30})
check("conceder acceso a analista", r.status_code == 200)
r = ana_c.get(f"/api/web/vms/{vm_id}")
check("analista CON concesión -> ve VM", r.status_code == 200)
if r.status_code == 200:
    creds = r.json()["credenciales"]
    check("analista puede_revelar (nivel ver_credenciales)", len(creds)>0 and creds[0]["puede_revelar"] is True)
    r2 = ana_c.post(f"/api/web/credenciales/{cred_vm}/revelar", headers=Ha)
    check("analista revela credencial concedida", r2.status_code == 200)
# analista NO puede gestionar inventario
r = ana_c.post("/api/web/servidores", headers=Ha, json={"nombre":"x","tipo":"funcion_unica","descripcion":"","sistema_operativo":"","marca_modelo":"","ubicacion":"","ip_gestion":"","ram":"","cpu":"","almacenamiento":"","numero_serie":"","garantia_hasta":"","proveedor":"","estado":"activo","etiquetas":""})
check("analista NO puede crear servidor (403)", r.status_code == 403)
# revocar
db = next(get_db())
from app.models import ConcesionAcceso
con = db.scalar(select(ConcesionAcceso).where(ConcesionAcceso.usuario_id==ana_id)); con_id = con.id; db.close()
r = admin.post(f"/api/web/accesos/{con_id}/revocar", headers=H); check("revocar acceso", r.status_code == 200)
r = ana_c.get(f"/api/web/vms/{vm_id}"); check("analista tras revocar -> sin acceso", r.status_code in (403,404))

# === 8. Gestión de usuarios: reset password, reset mfa, cambiar rol, desactivar/reactivar ===
db = next(get_db()); aud = db.scalar(select(Usuario).where(Usuario.username=="aud")); aud_id = aud.id; db.close()
r = admin.post(f"/api/web/usuarios/{aud_id}/reset-password", headers=H); check("reset password", r.status_code == 200 and "password_temporal" in r.json())
r = admin.post(f"/api/web/usuarios/{aud_id}/reset-mfa", headers=H); check("reset MFA", r.status_code == 200)
r = admin.post(f"/api/web/usuarios/{aud_id}/rol", headers=H, json={"rol":"operador"}); check("cambiar rol", r.status_code == 200)
r = admin.post(f"/api/web/usuarios/{aud_id}/desactivar", headers=H); check("desactivar usuario", r.status_code == 200)
r = admin.post(f"/api/web/usuarios/{aud_id}/reactivar", headers=H); check("reactivar usuario", r.status_code == 200)

# === 9. Tokens API + uso real en /api/v1 ===
r = admin.post("/api/web/tokens", headers=H, json={"nombre":"siem"}); token_valor = r.json()["token"]; check("crear token API", r.status_code == 200 and token_valor)
r = admin.get("/api/v1/inventario", headers={"Authorization": f"Bearer {token_valor}"})
check("token funciona en /api/v1/inventario", r.status_code == 200 and "servidores_fisicos" in r.json())
r = admin.get("/api/v1/auditoria", headers={"Authorization": f"Bearer {token_valor}"})
check("token funciona en /api/v1/auditoria", r.status_code == 200)
db = next(get_db())
from app.models import TokenApi
t = db.scalar(select(TokenApi)); tid = t.id; db.close()
r = admin.post(f"/api/web/tokens/{tid}/revocar", headers=H); check("revocar token", r.status_code == 200)
r = admin.get("/api/v1/inventario", headers={"Authorization": f"Bearer {token_valor}"})
check("token revocado -> 401", r.status_code == 401)

# Alcance (scope): un token 'auditoria' NO puede leer inventario y viceversa.
r = admin.post("/api/web/tokens", headers=H, json={"nombre":"solo-aud","alcance":"auditoria","dias_validez":0})
t_aud = r.json()["token"]
check("token auditoria: ve auditoría", admin.get("/api/v1/auditoria", headers={"Authorization": f"Bearer {t_aud}"}).status_code == 200)
check("token auditoria: 403 en inventario", admin.get("/api/v1/inventario", headers={"Authorization": f"Bearer {t_aud}"}).status_code == 403)

# === 9 bis. Integridad de la cadena de auditoría ===
db = next(get_db())
from app import audit as _audit
res_cadena = _audit.verificar_cadena(db); db.close()
check("cadena de auditoría íntegra", res_cadena["ok"] is True and res_cadena["verificados"] > 0)

# === 10. Auditoría: listar, filtrar y exportar CSV ===
r = admin.get("/api/web/auditoria?pagina=1"); aj = r.json()
check("auditoría lista", r.status_code == 200 and len(aj["registros"])>0 and "acciones" in aj)
r = admin.get("/api/web/auditoria?filtro_accion=credencial_revelada")
check("auditoría filtrada por acción", r.status_code == 200 and all(x["accion"]=="credencial_revelada" for x in r.json()["registros"]))
r = admin.get("/api/web/auditoria/export.csv")
check("export CSV", r.status_code == 200 and "fecha" in r.text.splitlines()[0])

# === 11. Métricas ===
r = admin.get("/api/web/metricas"); m = r.json()
check("métricas", r.status_code == 200 and all(k in m for k in ["rotacion_vencida","logins_fallidos_24h","sin_mfa","top_accesos","concesiones_por_caducar"]))

# === 11 bis. Configuración en tiempo de ejecución ===
r = admin.get("/api/web/configuracion"); cfg = r.json()
check("configuración: grupos e info", r.status_code == 200 and len(cfg["grupos"]) >= 5 and len(cfg["info_sistema"]) > 0)
r = admin.put("/api/web/configuracion", headers=H, json={"cambios": {"session_idle_minutes": 20, "reveal_rate_limit": 25}})
check("configuración: guardar override", r.status_code == 200 and "session_idle_minutes" in r.json()["modificadas"])
_todos = [a for g in admin.get("/api/web/configuracion").json()["grupos"] for a in g["ajustes"]]
_idle = next(a for a in _todos if a["clave"] == "session_idle_minutes")
check("configuración: valor y origen efectivos", _idle["valor"] == 20 and _idle["origen"] == "configurado")
r = admin.put("/api/web/configuracion", headers=H, json={"cambios": {"smtp_host": "smtp.local", "smtp_password": "Secreto-SMTP!2026"}})
check("configuración: guardar secreto SMTP", r.status_code == 200)
_smtp = next(a for a in [a for g in admin.get("/api/web/configuracion").json()["grupos"] for a in g["ajustes"]] if a["clave"] == "smtp_password")
check("configuración: secreto no se filtra", "Secreto-SMTP!2026" not in admin.get("/api/web/configuracion").text and _smtp["configurado"] is True and "valor" not in _smtp)
r = admin.post("/api/web/configuracion/restablecer", headers=H, json={"clave": "session_idle_minutes"})
check("configuración: restablecer", r.status_code == 200 and r.json()["restablecido"] is True)
r = admin.put("/api/web/configuracion", headers=H, json={"cambios": {"audit_retention_days": 10}})
check("configuración: validación de rango (piso 90)", r.status_code == 400)
r = admin.post("/api/web/configuracion/probar-correo", headers=H, json={"destinatario": ""})
check("configuración: probar correo sin destinatario -> 400", r.status_code == 400)

# === 12. Búsqueda global ===
r = admin.get("/api/web/buscar?q=dedicado"); b = r.json()
check("búsqueda servidores", r.status_code == 200 and any(s["nombre"]=="srv-dedicado" for s in b["servidores"]))
r = admin.get("/api/web/buscar?q=pve"); bh = r.json()
check("búsqueda hipervisores", r.status_code == 200 and any(h["nombre"]=="pve-01" for h in bh["hipervisores"]))
r = admin.get("/api/web/buscar?q=deploy")
check("búsqueda credenciales (sin password)", r.status_code == 200 and all("password" not in c for c in r.json()["credenciales"]))

# === 13. Importación CSV ===
csv_data = (
    "tipo,nombre,sistema_operativo,ip,descripcion,estado,etiquetas,padre,plataforma,version,activo_tipo,usuario_acceso,password,servicio,puerto\n"
    "servidor,srv-bd,Debian,10.0.2.1,base de datos,activo,bd,,,,,,,,\n"
    "hipervisor,pve-imp,,10.0.2.2,nodo,activo,,,Proxmox VE,8.2,,,,,\n"
    "credencial,,,,,,,srv-bd,,,servidor,dba,ImportPwd!2026,SSH,22\n"
)
r = admin.post("/api/web/importar", headers=H, files={"archivo": ("inv.csv", csv_data, "text/csv")})
imp = r.json()
check("importación CSV", r.status_code == 200 and imp["creados"]["servidor"]==1 and imp["creados"]["hipervisor"]==1 and imp["creados"]["credencial"]==1, str(imp.get("errores")))

# === 13 ter. Dispositivos de red (switches, routers, firewalls…) ===
r = admin.post("/api/web/dispositivos", headers=H, json={"nombre":"sw-core-01","tipo_dispositivo":"switch","marca_modelo":"Catalyst 9300","version":"IOS-XE 17.9","ip_gestion":"10.0.3.1","ubicacion":"Rack A1","puertos":"48x 1GbE + 4x SFP+","descripcion":"switch de núcleo","etiquetas":"red"})
disp_id = r.json()["id"]; check("crear dispositivo de red", r.status_code == 200)
r = admin.get(f"/api/web/dispositivos/{disp_id}")
check("detalle de dispositivo", r.status_code == 200 and r.json()["tipo_dispositivo_label"] == "Switch" and r.json()["puertos"] == "48x 1GbE + 4x SFP+")
r = admin.post("/api/web/credenciales", headers=H, json={"activo":"dispositivo","activo_id":disp_id,"usuario_acceso":"netadmin","password":"SwitchPwd!2026","servicio":"SSH","puerto":22,"descripcion":"gestión"})
cred_disp = r.json()["id"]; check("credencial en dispositivo", r.status_code == 200)
r = admin.post(f"/api/web/credenciales/{cred_disp}/revelar", headers=H)
check("revelar credencial de dispositivo", r.status_code == 200 and r.json()["password"] == "SwitchPwd!2026")
r = admin.get("/api/web/buscar?q=sw-core")
check("búsqueda dispositivos", r.status_code == 200 and any(d["nombre"]=="sw-core-01" for d in r.json()["dispositivos"]))
r = admin.get("/api/web/dashboard")
check("dashboard cuenta dispositivos", r.json()["resumen"]["dispositivos"] >= 1)

# === 13 bis. Vault personal (privado del usuario) ===
r = admin.post("/api/web/vault", headers=H, json={"titulo":"Correo admin","usuario_acceso":"admin@correo","password":"VaultPwd!2026x","url":"https://correo","categoria":"cuenta","notas":"principal"})
vault_id = r.json()["id"]; check("crear entrada de vault", r.status_code == 200)
r = admin.get("/api/web/vault"); vl = r.json()["entradas"]
check("listar vault (sin password)", r.status_code == 200 and len(vl)==1 and all("password" not in e for e in vl))
r = admin.post(f"/api/web/vault/{vault_id}/revelar", headers=H)
check("revelar vault", r.status_code == 200 and r.json()["password"]=="VaultPwd!2026x" and r.headers.get("cache-control")=="no-store")
# El vault es privado: el operador no ve la entrada del admin
ope_c = TestClient(app)
tok_ope, _ = login_completo(ope_c, "ope", ope_pwd, nueva="Op3r-Clave-Segura-26!")
Ho = {"X-CSRF-Token": tok_ope}
r = ope_c.get(f"/api/web/vault/{vault_id}"); check("vault ajeno -> 404 (privado)", r.status_code == 404)
r = ope_c.get("/api/web/vault"); check("operador tiene su propio vault vacío", r.status_code == 200 and r.json()["entradas"]==[])

# === 13 ter. Export en claro para migración + plantilla ===
r = admin.post("/api/web/exportar", headers=H)
check("export en claro (CSV)", r.status_code == 200 and "PwdHv!2026xyz" in r.text and "vm-web" in r.text and "8 GB" in r.text and r.headers.get("cache-control")=="no-store")
r = admin.get("/api/web/plantilla.csv")
check("plantilla CSV", r.status_code == 200 and all(c in r.text.splitlines()[0] for c in ("tipo","ram","cpu","almacenamiento","password")))
# El operador (con gestión) puede exportar; el analista no
r = ope_c.post("/api/web/exportar", headers=Ho); check("operador puede exportar", r.status_code == 200)

# === 13 quater. Activos restringidos a administradores ===
# El admin crea un servidor y lo marca restringido.
r = admin.post("/api/web/servidores", headers=H, json={"nombre":"srv-restringido","sistema_operativo":"Debian","ip_gestion":"10.0.9.9","restringido":True})
srv_restr = r.json()["id"]; check("crear servidor restringido", r.status_code == 200)
r = admin.get(f"/api/web/servidores/{srv_restr}")
check("detalle expone restringido/puede_restringir", r.json().get("restringido") is True and r.json().get("puede_restringir") is True)
r = admin.post("/api/web/credenciales", headers=H, json={"activo":"fisico","activo_id":srv_restr,"usuario_acceso":"root","password":"RestrPwd!2026","servicio":"SSH","puerto":22,"descripcion":"secreto"})
cred_restr = r.json()["id"]; check("credencial en activo restringido", r.status_code == 200)
# El operador NO ve el activo restringido
check("operador: detalle restringido -> 404", ope_c.get(f"/api/web/servidores/{srv_restr}").status_code == 404)
check("operador: dashboard oculta restringido", all(s["nombre"]!="srv-restringido" for s in ope_c.get("/api/web/dashboard").json()["servidores"]))
check("operador: revelar restringido -> 404", ope_c.post(f"/api/web/credenciales/{cred_restr}/revelar", headers=Ho).status_code == 404)
check("operador: buscar no lo encuentra", all(s["nombre"]!="srv-restringido" for s in ope_c.get("/api/web/buscar?q=restringido").json()["servidores"]))
# El auditor SÍ ve el activo pero no revela (auditor fresco: el «aud» inicial se
# transformó en operador en la sección 8 de gestión de usuarios).
r = crear_usuario("rev","rev@example.com","auditor"); rev_pwd = r.json()["password_temporal"]
aud_c = TestClient(app)
tok_aud, _ = login_completo(aud_c, "rev", rev_pwd, nueva="Sup3rv1sor-Clave-26!")
check("auditor: sí ve el restringido", aud_c.get(f"/api/web/servidores/{srv_restr}").status_code == 200)
check("auditor: no puede revelar", aud_c.post(f"/api/web/credenciales/{cred_restr}/revelar", headers={"X-CSRF-Token":tok_aud}).status_code == 403)
# El operador no puede restringir (se ignora la marca)
r = ope_c.post("/api/web/servidores", headers=Ho, json={"nombre":"srv-ope-restr","restringido":True})
check("operador no puede restringir", r.status_code == 200 and admin.get(f"/api/web/servidores/{r.json()['id']}").json()["restringido"] is False)

# === 14. Eliminaciones en cascada ===
r = admin.delete(f"/api/web/servidores/{host_id}", headers=H); check("eliminar servidor dedicado", r.status_code == 200)
r = admin.delete(f"/api/web/hipervisores/{hv_id}", headers=H); check("eliminar hipervisor (cascada)", r.status_code == 200)
r = admin.get(f"/api/web/vms/{vm_id}"); check("VM eliminada en cascada -> 404", r.status_code == 404)

# === 15. Login con código de recuperación ===
rec = TestClient(app)
csrf = rec.get("/api/web/csrf").json()["csrf_login"]
rec.post("/api/web/login", json={"username":"admin","password":"Cl4veMaestra!Segura26","csrf_login":csrf})
tok = rec.get("/api/web/session").json()["csrf_token"]
r = rec.post("/api/web/mfa/verificar", headers={"X-CSRF-Token":tok}, json={"codigo": recovery_admin[0]})
check("login con código de recuperación", r.status_code == 200 and r.json().get("ok"))

# === 16. Logout ===
r = admin.post("/api/web/logout", headers=H); check("logout", r.status_code == 200)
r = admin.get("/api/web/dashboard"); check("tras logout -> 401", r.status_code == 401)

print("\n=== RESULTADO ===")
if fallos:
    print(f"FALLOS ({len(fallos)}): " + ", ".join(fallos)); sys.exit(1)
print("TODAS LAS FUNCIONES VERIFICADAS OK")
