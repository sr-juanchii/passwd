// Package helper es la lógica del helper root de acción única.
//
// El agente no tiene privilegios: no puede cambiar una contraseña. Lo hace este
// helper, que systemd arranca como root por cada conexión a un socket local
// (Accept=yes) y que atiende UNA petición y termina. Este paquete no toca el
// sistema: recibe las operaciones reales (PAM y chpasswd) por la interfaz
// Sistema, de modo que todas sus reglas se prueban sin root.
//
// Reglas (docs/plan-rotacion-agentes.md §4.1 y §4.2):
//   - solo las cuentas de su lista, y solo si existen: nunca crea una cuenta;
//   - solo atiende al usuario del agente (SO_PEERCRED del socket), o a root
//     cuando se invoca a mano;
//   - antes de cambiar una contraseña comprueba que la actual del inventario
//     sigue valiendo; si no, no toca nada;
//   - nunca devuelve ni registra una contraseña.
package helper

import (
	"bufio"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"regexp"
	"slices"
	"strings"
	"syscall"
	"unicode/utf8"
)

// ServicioPAM es el nombre del servicio PAM propio del helper. Su archivo
// (/etc/pam.d/passwd-agente-helper) solo usa pam_unix: verifica la contraseña
// local sin pasar por faillock ni por otros factores.
const ServicioPAM = "passwd-agente-helper"

// RutaConfigPorDefecto es donde el instalador deja la lista de cuentas.
const RutaConfigPorDefecto = "/etc/passwd-agente/helper.json"

// MaxPeticion acota lo que se lee de la conexión.
const MaxPeticion = 4096

// Acciones del protocolo.
const (
	AccionVerificar = "verificar"
	AccionAplicar   = "aplicar"
	AccionRestaurar = "restaurar"
)

const largoMaximoPassword = 256

var patronCuenta = regexp.MustCompile(`^[a-z_][a-z0-9_.-]{0,31}$`)

// Peticion es lo que envía el agente, una línea JSON.
type Peticion struct {
	Accion   string `json:"accion"`
	Cuenta   string `json:"cuenta"`
	Password string `json:"password,omitempty"`
	Actual   string `json:"actual,omitempty"`
	Nueva    string `json:"nueva,omitempty"`
	Valor    string `json:"valor,omitempty"`
}

// Respuesta es lo que devuelve el helper. Error nunca lleva una contraseña.
type Respuesta struct {
	OK    bool   `json:"ok"`
	Error string `json:"error,omitempty"`
	// SinCambios: el helper rechazó la petición ANTES de tocar la cuenta. Sin
	// esta marca, un fallo puede haber ocurrido a mitad de fijar la contraseña,
	// y quien llama debe comprobar qué quedó.
	SinCambios bool `json:"sin_cambios,omitempty"`
}

// ErrSinCambios lo envuelven los errores de un rechazo que no tocó la cuenta.
var ErrSinCambios = errors.New("el helper no cambió nada")

// Config es la configuración del helper, propiedad de root.
type Config struct {
	// Usuario con el que corre el agente: el único que puede pedir algo.
	UsuarioAgente string `json:"usuario_agente"`
	// Cuentas cuya contraseña se puede cambiar. Es la lista exacta: ampliarla
	// exige editar este archivo como root.
	Cuentas []string `json:"cuentas"`
}

// CargarConfig lee la configuración y exige que solo root pueda modificarla:
// si el agente pudiera escribirla, se concedería a sí mismo cualquier cuenta.
func CargarConfig(ruta string) (*Config, error) {
	info, err := os.Stat(ruta)
	if err != nil {
		return nil, err
	}
	if st, ok := info.Sys().(*syscall.Stat_t); !ok || st.Uid != 0 {
		return nil, fmt.Errorf("%s debe pertenecer a root", ruta)
	}
	if info.Mode().Perm()&0o022 != 0 {
		return nil, fmt.Errorf("%s no puede ser escribible por el grupo ni por otros (%#o)", ruta, info.Mode().Perm())
	}
	datos, err := os.ReadFile(ruta)
	if err != nil {
		return nil, err
	}
	var c Config
	decodificador := json.NewDecoder(strings.NewReader(string(datos)))
	decodificador.DisallowUnknownFields()
	if err := decodificador.Decode(&c); err != nil {
		return nil, fmt.Errorf("%s: %w", ruta, err)
	}
	if c.UsuarioAgente == "" {
		return nil, fmt.Errorf("%s: falta «usuario_agente»", ruta)
	}
	for _, cuenta := range c.Cuentas {
		if !patronCuenta.MatchString(cuenta) {
			return nil, fmt.Errorf("%s: cuenta con formato no admitido: %q", ruta, cuenta)
		}
	}
	return &c, nil
}

// Sistema son las operaciones reales sobre las cuentas.
type Sistema interface {
	Existe(cuenta string) bool
	Verificar(cuenta, password string) (bool, error)
	Fijar(cuenta, password string) error
}

// Llamante describe quién está al otro lado.
type Llamante struct {
	EsSocket bool
	UID      int
}

// Helper atiende una petición.
type Helper struct {
	Config    *Config
	Sistema   Sistema
	UIDAgente int
}

// Atender lee una petición de r y devuelve la respuesta.
func (h *Helper) Atender(r io.Reader, quien Llamante) Respuesta {
	if quien.EsSocket && quien.UID != h.UIDAgente {
		return fallo("llamada no autorizada: solo atiende al usuario del agente")
	}
	if !quien.EsSocket && quien.UID != 0 {
		return fallo("invocado fuera del socket: solo root")
	}
	p, err := leer(r)
	if err != nil {
		return fallo(err.Error())
	}
	if !patronCuenta.MatchString(p.Cuenta) {
		return fallo("nombre de cuenta con formato no admitido")
	}
	if !slices.Contains(h.Config.Cuentas, p.Cuenta) {
		return fallo("la cuenta no está en la lista de cuentas que este helper puede rotar")
	}
	if !h.Sistema.Existe(p.Cuenta) {
		// Nunca se crea una cuenta: si no existe, no hay nada que rotar.
		return fallo("la cuenta no existe en este sistema")
	}

	switch p.Accion {
	case AccionVerificar:
		if err := validarPassword(p.Password); err != nil {
			return fallo(err.Error())
		}
		ok, err := h.Sistema.Verificar(p.Cuenta, p.Password)
		if err != nil {
			return fallo("no se pudo verificar: " + err.Error())
		}
		return Respuesta{OK: ok}
	case AccionAplicar:
		if err := validarPassword(p.Actual); err != nil {
			return fallo(err.Error())
		}
		if err := validarPassword(p.Nueva); err != nil {
			return fallo(err.Error())
		}
		ok, err := h.Sistema.Verificar(p.Cuenta, p.Actual)
		if err != nil {
			return fallo("no se pudo verificar la contraseña actual: " + err.Error())
		}
		if !ok {
			return fallo("la contraseña actual del inventario no autentica la cuenta: no se cambia nada")
		}
		if err := h.Sistema.Fijar(p.Cuenta, p.Nueva); err != nil {
			return falloAlFijar("no se pudo fijar la contraseña: " + err.Error())
		}
		return Respuesta{OK: true}
	case AccionRestaurar:
		if err := validarPassword(p.Valor); err != nil {
			return fallo(err.Error())
		}
		if err := h.Sistema.Fijar(p.Cuenta, p.Valor); err != nil {
			return falloAlFijar("no se pudo restaurar la contraseña: " + err.Error())
		}
		return Respuesta{OK: true}
	default:
		return fallo("acción desconocida")
	}
}

// fallo es un rechazo antes de tocar la cuenta.
func fallo(motivo string) Respuesta { return Respuesta{Error: motivo, SinCambios: true} }

// falloAlFijar es un error de chpasswd: la cuenta pudo quedar a medias.
func falloAlFijar(motivo string) Respuesta { return Respuesta{Error: motivo} }

func leer(r io.Reader) (*Peticion, error) {
	linea, err := bufio.NewReader(io.LimitReader(r, MaxPeticion+1)).ReadBytes('\n')
	if err != nil && !errors.Is(err, io.EOF) {
		return nil, errors.New("no se pudo leer la petición")
	}
	if len(linea) > MaxPeticion {
		return nil, errors.New("petición demasiado grande")
	}
	var p Peticion
	decodificador := json.NewDecoder(strings.NewReader(string(linea)))
	decodificador.DisallowUnknownFields()
	if err := decodificador.Decode(&p); err != nil {
		return nil, errors.New("petición ilegible")
	}
	return &p, nil
}

func validarPassword(p string) error {
	// chpasswd recibe «cuenta:contraseña» por línea y corta en los PRIMEROS dos
	// puntos, así que «:» es válido dentro de la contraseña; un salto de línea o
	// un NUL no lo son.
	if p == "" || len(p) > largoMaximoPassword || !utf8.ValidString(p) || strings.ContainsAny(p, "\n\r\x00") {
		return errors.New("contraseña con formato no admitido")
	}
	return nil
}
