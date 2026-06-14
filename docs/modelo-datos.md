# Modelo de datos relacional

## Jerarquía del inventario

La segmentación pedida se modela con tres niveles enlazados por claves foráneas:

```mermaid
erDiagram
    SERVIDOR_FISICO ||--o{ HIPERVISOR : "aloja (solo tipo host_virtualizacion)"
    HIPERVISOR ||--o{ MAQUINA_VIRTUAL : "ejecuta"
    SERVIDOR_FISICO ||--o{ CREDENCIAL : "tiene"
    HIPERVISOR ||--o{ CREDENCIAL : "tiene"
    MAQUINA_VIRTUAL ||--o{ CREDENCIAL : "tiene"
    USUARIO ||--o{ SESION_WEB : "abre"
    USUARIO ||--o{ CREDENCIAL : "registró"
    USUARIO ||--o{ REGISTRO_AUDITORIA : "genera"
    USUARIO ||--o{ CODIGO_RECUPERACION_MFA : "posee"
    USUARIO ||--o{ CONCESION_ACCESO : "recibe (analista)"
    SERVIDOR_FISICO ||--o{ CONCESION_ACCESO : "concedido"
    HIPERVISOR ||--o{ CONCESION_ACCESO : "concedido"
    MAQUINA_VIRTUAL ||--o{ CONCESION_ACCESO : "concedido"

    SERVIDOR_FISICO {
        int id PK
        string nombre UK
        string tipo "funcion_unica | host_virtualizacion"
        text descripcion "sistema o funcion que cumple"
        string sistema_operativo
        string marca_modelo
        string ubicacion
        string ip_gestion
    }
    HIPERVISOR {
        int id PK
        int servidor_fisico_id FK
        string nombre
        string plataforma "Proxmox, ESXi, Hyper-V..."
        string version
        string ip_gestion
        text descripcion
    }
    MAQUINA_VIRTUAL {
        int id PK
        int hipervisor_id FK
        string nombre
        string sistema_operativo
        string ip
        text descripcion "sistema que corre"
    }
    CREDENCIAL {
        int id PK
        int servidor_fisico_id FK "exactamente uno de los tres"
        int hipervisor_id FK
        int maquina_virtual_id FK
        string usuario_acceso
        bytes password_cifrada "Fernet AES"
        string servicio "SSH, RDP, iLO..."
        int puerto
        text descripcion
        int creado_por_id FK
        datetime password_rotada_en "alertas de rotacion"
    }
    CODIGO_RECUPERACION_MFA {
        int id PK
        int usuario_id FK
        string codigo_hash UK "SHA-256, un solo uso"
        datetime usado_en
    }
    USUARIO {
        int id PK
        string username UK
        string email UK
        string password_hash "Argon2id"
        string rol "admin | operador | auditor | analista"
        bytes totp_secret_cifrado
        bool mfa_habilitado
        bool activo
    }
    CONCESION_ACCESO {
        int id PK
        int usuario_id FK "analista"
        int servidor_fisico_id FK "exactamente uno de los tres"
        int hipervisor_id FK
        int maquina_virtual_id FK
        string nivel "ver | ver_credenciales"
        int concedido_por_id FK "admin"
        datetime expira_en "caducidad opcional"
    }
    SESION_WEB {
        int id PK
        string token_hash UK "SHA-256"
        int usuario_id FK
        string etapa "cambio_password | mfa_enrolamiento | mfa_pendiente | activa"
        datetime expira_en
        datetime revocada_en
    }
    REGISTRO_AUDITORIA {
        int id PK
        datetime fecha
        int usuario_id FK
        string accion
        string objeto_tipo
        string objeto_id
        text detalle
        string direccion_ip
        bool exito
    }
```

## Reglas de integridad

1. **Tipos de servidor físico**: `funcion_unica` (dedicado a un solo sistema) o
   `host_virtualizacion` (sin función única; aloja hipervisores). Restricción CHECK en BD
   y validación de negocio: no se pueden crear hipervisores bajo un servidor de función
   única, ni degradar a función única un servidor que tenga hipervisores.
2. **Máquinas virtuales**: siempre pertenecen a un hipervisor (`hipervisor_id NOT NULL`);
   un hipervisor siempre pertenece a un servidor físico (`servidor_fisico_id NOT NULL`).
3. **Credenciales**: restricción CHECK que exige exactamente **una** de las tres claves
   foráneas (`servidor_fisico_id`, `hipervisor_id`, `maquina_virtual_id`); imposible una
   credencial huérfana o ambigua.
4. **Borrado en cascada**: eliminar un servidor físico elimina sus hipervisores, las VMs
   de estos y todas las credenciales asociadas; eliminar un hipervisor hace lo propio con
   sus VMs y credenciales.
5. **Secretos**: `password_cifrada` y `totp_secret_cifrado` nunca contienen texto plano;
   `token_hash` impide reutilizar un volcado de BD para secuestrar sesiones.
6. **Auditoría**: `usuario_id` usa `ON DELETE SET NULL` y se conserva el `username`
   textual, de modo que la trazabilidad sobrevive a cualquier baja.
7. **Concesiones de acceso**: misma restricción CHECK de «exactamente un activo» que las
   credenciales, más `UNIQUE(usuario, activo)` (sin duplicados) y `nivel ∈ {ver,
   ver_credenciales}`. `ON DELETE CASCADE` desde el usuario y desde el activo: al eliminar
   cualquiera, sus concesiones desaparecen. No hay herencia entre niveles del inventario.
   Detalle del modelo de acceso en [`control-acceso.md`](control-acceso.md).
