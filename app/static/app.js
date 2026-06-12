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

document.addEventListener("DOMContentLoaded", function () {
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

  // Revelado de contraseñas: consulta autenticada + auditada; se vuelve a
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

      var csrf = "";
      var entrada = document.querySelector("input[name='csrf_token']");
      if (entrada) csrf = entrada.value;

      boton.disabled = true;
      fetch("/credenciales/" + boton.dataset.revelar + "/revelar", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: "csrf_token=" + encodeURIComponent(csrf),
        credentials: "same-origin",
      })
        .then(function (respuesta) {
          if (!respuesta.ok) throw new Error("No autorizado");
          return respuesta.json();
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
        .catch(function () {
          destino.textContent = "(error al revelar)";
        })
        .finally(function () {
          boton.disabled = false;
        });
    });
  });
});
