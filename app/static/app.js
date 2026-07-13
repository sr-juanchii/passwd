// Interacciones mínimas del lado cliente, compatibles con la CSP estricta
// (sin código embebido en el HTML).
"use strict";

// Genera una cadena aleatoria uniforme (sin sesgo de módulo) con el CSPRNG
// del navegador.
function generarAleatoria(alfabeto, longitud) {
  var limite = Math.floor(256 / alfabeto.length) * alfabeto.length;
  var resultado = "";
  var buffer = new Uint8Array(64);
  while (resultado.length < longitud) {
    crypto.getRandomValues(buffer);
    for (var i = 0; i < buffer.length && resultado.length < longitud; i++) {
      if (buffer[i] < limite) {
        resultado += alfabeto[buffer[i] % alfabeto.length];
      }
    }
  }
  return resultado;
}

// Escritura en portapapeles con reserva para contextos sin HTTPS (pruebas).
function escribirPortapapeles(texto) {
  if (navigator.clipboard && window.isSecureContext) {
    return navigator.clipboard.writeText(texto);
  }
  return new Promise(function (resolver, rechazar) {
    var area = document.createElement("textarea");
    area.value = texto;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.left = "-9999px";
    document.body.appendChild(area);
    area.select();
    var ok = document.execCommand("copy");
    document.body.removeChild(area);
    if (ok) {
      resolver();
    } else {
      rechazar(new Error("portapapeles no disponible"));
    }
  });
}

function tokenCsrf() {
  var entrada = document.querySelector("input[name='csrf_token']");
  return entrada ? entrada.value : "";
}

// Pide la contraseña al servidor (acción auditada). Devuelve una promesa con
// el texto, o lanza con un mensaje apto para mostrar.
function pedirPassword(credencialId, accion) {
  return fetch("/credenciales/" + credencialId + "/" + accion, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: "csrf_token=" + encodeURIComponent(tokenCsrf()),
    credentials: "same-origin",
  }).then(function (respuesta) {
    if (respuesta.status === 429) throw new Error("límite alcanzado; espere unos minutos");
    if (respuesta.status === 403) throw new Error("no autorizado");
    if (!respuesta.ok) throw new Error("error " + respuesta.status);
    return respuesta.json();
  });
}

document.addEventListener("DOMContentLoaded", function () {
  // Tema claro/oscuro persistido en el navegador (localStorage).
  try {
    if (localStorage.getItem("tema") === "oscuro") {
      document.documentElement.dataset.tema = "oscuro";
    }
  } catch (e) { /* almacenamiento no disponible */ }
  var toggleTema = document.getElementById("toggle-tema");
  if (toggleTema) {
    toggleTema.addEventListener("click", function () {
      var oscuro = document.documentElement.dataset.tema === "oscuro";
      if (oscuro) {
        delete document.documentElement.dataset.tema;
      } else {
        document.documentElement.dataset.tema = "oscuro";
      }
      try { localStorage.setItem("tema", oscuro ? "claro" : "oscuro"); } catch (e) { /* ignore */ }
    });
  }

  // Confirmación previa en formularios destructivos.
  document.querySelectorAll("form[data-confirmar]").forEach(function (formulario) {
    formulario.addEventListener("submit", function (evento) {
      if (!window.confirm(formulario.dataset.confirmar)) {
        evento.preventDefault();
      }
    });
  });

  // Generador de contraseñas robustas para credenciales de servidores.
  document.querySelectorAll("button[data-generar]").forEach(function (boton) {
    boton.addEventListener("click", function () {
      var campo = document.getElementById(boton.dataset.generar);
      if (!campo) return;
      var alfabeto =
        "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789!#$%&*+-=?@_";
      campo.value = generarAleatoria(alfabeto, 20);
      campo.type = "text"; // visible para poder copiarla al servidor
      campo.focus();
    });
  });

  // Copiar al portapapeles SIN mostrar la contraseña en pantalla.
  // El portapapeles se sobrescribe a los 30 s (mejor esfuerzo).
  document.querySelectorAll("button[data-copiar]").forEach(function (boton) {
    var etiquetaOriginal = boton.textContent;
    boton.addEventListener("click", function () {
      var destino = document.getElementById(boton.dataset.destino);
      boton.disabled = true;
      pedirPassword(boton.dataset.copiar, "copiar")
        .then(function (datos) {
          return escribirPortapapeles(datos.password);
        })
        .then(function () {
          boton.textContent = "✓ Copiada (30 s)";
          window.setTimeout(function () {
            escribirPortapapeles("").catch(function () {});
            boton.textContent = etiquetaOriginal;
          }, 30000);
        })
        .catch(function (error) {
          if (destino) destino.textContent = "(" + error.message + ")";
          boton.textContent = etiquetaOriginal;
        })
        .finally(function () {
          boton.disabled = false;
        });
    });
  });

  // Revelado de una contraseña anterior del historial (auditado).
  document.querySelectorAll("button[data-revelar-historial]").forEach(function (boton) {
    boton.addEventListener("click", function () {
      var destino = document.getElementById(boton.dataset.destino);
      if (!destino) return;
      if (boton.dataset.visible === "1") {
        destino.textContent = "••••••••";
        boton.dataset.visible = "0";
        boton.textContent = "Revelar";
        return;
      }
      boton.disabled = true;
      fetch("/credenciales/" + boton.dataset.revelarHistorial + "/revelar", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: "csrf_token=" + encodeURIComponent(tokenCsrf()),
        credentials: "same-origin",
      })
        .then(function (r) {
          if (r.status === 429) throw new Error("límite alcanzado");
          if (!r.ok) throw new Error("no autorizado");
          return r.json();
        })
        .then(function (datos) {
          destino.textContent = datos.password;
          boton.dataset.visible = "1";
          boton.textContent = "Ocultar";
          window.setTimeout(function () {
            if (boton.dataset.visible === "1") {
              destino.textContent = "••••••••";
              boton.dataset.visible = "0";
              boton.textContent = "Revelar";
            }
          }, 30000);
        })
        .catch(function (e) { destino.textContent = "(" + e.message + ")"; })
        .finally(function () { boton.disabled = false; });
    });
  });

  // Revelado de notas seguras (auditado). Se ocultan a los 30 segundos.
  document.querySelectorAll("button[data-revelar-notas]").forEach(function (boton) {
    boton.addEventListener("click", function () {
      var destino = document.getElementById(boton.dataset.destino);
      if (!destino) return;
      if (boton.dataset.visible === "1") {
        destino.hidden = true;
        destino.textContent = "";
        boton.dataset.visible = "0";
        boton.textContent = "Ver notas";
        return;
      }
      boton.disabled = true;
      fetch("/activos/" + boton.dataset.revelarNotas + "/notas/revelar", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: "csrf_token=" + encodeURIComponent(tokenCsrf()),
        credentials: "same-origin",
      })
        .then(function (r) {
          if (r.status === 429) throw new Error("límite alcanzado; espere unos minutos");
          if (!r.ok) throw new Error("no autorizado");
          return r.json();
        })
        .then(function (datos) {
          destino.textContent = datos.notas || "(sin contenido)";
          destino.hidden = false;
          boton.dataset.visible = "1";
          boton.textContent = "Ocultar notas";
          window.setTimeout(function () {
            if (boton.dataset.visible === "1") {
              destino.hidden = true;
              destino.textContent = "";
              boton.dataset.visible = "0";
              boton.textContent = "Ver notas";
            }
          }, 30000);
        })
        .catch(function (e) {
          destino.hidden = false;
          destino.textContent = "(" + e.message + ")";
        })
        .finally(function () {
          boton.disabled = false;
        });
    });
  });

  // Revelado en pantalla: consulta autenticada + auditada; se vuelve a
  // ocultar automáticamente después de 30 segundos.
  document.querySelectorAll("button[data-revelar]").forEach(function (boton) {
    boton.addEventListener("click", function () {
      var destino = document.getElementById(boton.dataset.destino);
      if (!destino) return;

      if (boton.dataset.visible === "1") {
        destino.textContent = "••••••••";
        boton.dataset.visible = "0";
        boton.textContent = "Revelar";
        return;
      }

      boton.disabled = true;
      pedirPassword(boton.dataset.revelar, "revelar")
        .then(function (datos) {
          destino.textContent = datos.password;
          boton.dataset.visible = "1";
          boton.textContent = "Ocultar";
          window.setTimeout(function () {
            if (boton.dataset.visible === "1") {
              destino.textContent = "••••••••";
              boton.dataset.visible = "0";
              boton.textContent = "Revelar";
            }
          }, 30000);
        })
        .catch(function (error) {
          destino.textContent = "(" + error.message + ")";
        })
        .finally(function () {
          boton.disabled = false;
        });
    });
  });

  // Vault personal: revelar/copiar la contraseña de una entrada (auditado,
  // limitado). Mismo comportamiento que las credenciales pero contra /vault.
  function pedirPasswordVault(entradaId, accion) {
    return fetch("/vault/" + entradaId + "/" + accion, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: "csrf_token=" + encodeURIComponent(tokenCsrf()),
      credentials: "same-origin",
    }).then(function (r) {
      if (r.status === 429) throw new Error("límite alcanzado; espere unos minutos");
      if (!r.ok) throw new Error("error " + r.status);
      return r.json();
    });
  }

  document.querySelectorAll("button[data-revelar-vault]").forEach(function (boton) {
    boton.addEventListener("click", function () {
      var destino = document.getElementById(boton.dataset.destino);
      if (!destino) return;
      if (boton.dataset.visible === "1") {
        destino.textContent = "••••••••";
        boton.dataset.visible = "0";
        boton.textContent = "Revelar";
        return;
      }
      boton.disabled = true;
      pedirPasswordVault(boton.dataset.revelarVault, "revelar")
        .then(function (datos) {
          destino.textContent = datos.password;
          boton.dataset.visible = "1";
          boton.textContent = "Ocultar";
          window.setTimeout(function () {
            if (boton.dataset.visible === "1") {
              destino.textContent = "••••••••";
              boton.dataset.visible = "0";
              boton.textContent = "Revelar";
            }
          }, 30000);
        })
        .catch(function (e) { destino.textContent = "(" + e.message + ")"; })
        .finally(function () { boton.disabled = false; });
    });
  });

  document.querySelectorAll("button[data-copiar-vault]").forEach(function (boton) {
    var etiquetaOriginal = boton.textContent;
    boton.addEventListener("click", function () {
      var destino = document.getElementById(boton.dataset.destino);
      boton.disabled = true;
      pedirPasswordVault(boton.dataset.copiarVault, "copiar")
        .then(function (datos) { return escribirPortapapeles(datos.password); })
        .then(function () {
          boton.textContent = "✓ Copiada (30 s)";
          window.setTimeout(function () {
            escribirPortapapeles("").catch(function () {});
            boton.textContent = etiquetaOriginal;
          }, 30000);
        })
        .catch(function (error) {
          if (destino) destino.textContent = "(" + error.message + ")";
          boton.textContent = etiquetaOriginal;
        })
        .finally(function () { boton.disabled = false; });
    });
  });
});
