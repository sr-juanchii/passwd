"""Capa de servicios: un caso de uso, una función.

Aquí viven las **reglas** del sistema; las interfaces (``app/api_web`` para la
API JSON y ``app/routes`` para la interfaz clásica) solo traducen HTTP ↔ servicio
y no deciden nada por su cuenta. Es el principio de diseño que
[`docs/plan-v2.0.md`](../../docs/plan-v2.0.md) fija para la 2.0 y que la
gobernanza de rotación necesita desde ya: una regla que vive en un controlador
solo protege a quien entra por ese controlador, y el fallo de seguridad de la
1.2.0 nació exactamente de esa duplicación.
"""
