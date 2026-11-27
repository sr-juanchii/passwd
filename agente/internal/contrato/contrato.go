// Package contrato decide si un trabajo se puede ejecutar ANTES de tocar nada.
//
// Es la versión en código de la lista de lo que el agente no puede hacer
// (docs/plan-rotacion-agentes.md §4.1): solo existe un tipo de trabajo, cambiar
// la contraseña de una cuenta que ya existe; no hay comandos, ni altas de
// cuenta, ni trabajos vencidos o simultáneos. Un trabajo que no pasa se informa
// como «fallado» con su motivo y no se ejecuta.
package contrato

import (
	"errors"
	"fmt"
	"regexp"
	"strings"
	"time"
	"unicode/utf8"
)

// TipoRotarCuenta es el ÚNICO tipo de trabajo. El enum es cerrado a propósito:
// cualquier otro valor se rechaza, de modo que un backend comprometido no puede
// colar una acción nueva aprovechando un campo que el agente ignore.
const TipoRotarCuenta = "rotar_cuenta"

// FormatoFecha es el de expira_en tal como lo envía el backend (UTC, sin zona).
const FormatoFecha = "2006-01-02T15:04:05"

const largoMaximoPassword = 256

// Nombres de cuenta como los admite useradd por defecto, sin cuentas de máquina.
var patronUsuario = regexp.MustCompile(`^[a-z_][a-z0-9_.-]{0,31}$`)

// Trabajo es el contenido del sobre.
type Trabajo struct {
	ID       int64  `json:"trabajo_id"`
	Tipo     string `json:"tipo"`
	Usuario  string `json:"usuario"`
	Nueva    string `json:"nueva"`
	Actual   string `json:"actual"`
	ExpiraEn string `json:"expira_en"`
	// Emergencia: la rotación la autorizó el backend por la vía de emergencia,
	// que es la única excepción al intervalo mínimo entre rotaciones (plan §4.1,
	// prohibición 13). Ruidosa y auditada en el backend; el agente la respeta.
	Emergencia bool `json:"emergencia,omitempty"`
}

// Errores del contrato. El mensaje viaja al backend como detalle del fallo:
// nunca lleva una contraseña.
var (
	ErrTipo        = errors.New("tipo de trabajo desconocido: el agente solo rota contraseñas de cuentas existentes")
	ErrVencido     = errors.New("el trabajo llegó vencido: no se aplica fuera de su ventana")
	ErrConcurrente = errors.New("hay otro trabajo en curso: el agente ejecuta uno cada vez")
	ErrAntiThrash  = errors.New("esta cuenta se rotó hace muy poco: intervalo mínimo local del agente")
	ErrUsuario     = errors.New("nombre de cuenta fuera del patrón admitido")
	ErrPassword    = errors.New("contraseña con formato no admitido")
)

// Contexto es lo que el contrato necesita saber del estado local.
type Contexto struct {
	Ahora      time.Time
	EnCurso    int64 // id del trabajo en curso según el journal, 0 si ninguno
	Ultima     func(usuario string) (time.Time, bool)
	AntiThrash time.Duration
}

// Validar devuelve nil si el trabajo se puede ejecutar.
func Validar(t Trabajo, c Contexto) error {
	if t.Tipo != TipoRotarCuenta {
		return ErrTipo
	}
	if t.ID <= 0 {
		return errors.New("trabajo sin identificador")
	}
	if c.EnCurso != 0 && c.EnCurso != t.ID {
		return ErrConcurrente
	}
	expira, err := time.ParseInLocation(FormatoFecha, t.ExpiraEn, time.UTC)
	if err != nil {
		return fmt.Errorf("fecha de expiración ilegible: %q", t.ExpiraEn)
	}
	if !c.Ahora.UTC().Before(expira) {
		return ErrVencido
	}
	if !patronUsuario.MatchString(t.Usuario) {
		return ErrUsuario
	}
	if err := validarPassword(t.Nueva); err != nil {
		return err
	}
	if err := validarPassword(t.Actual); err != nil {
		return err
	}
	if t.Nueva == t.Actual {
		return errors.New("la contraseña nueva es igual a la actual")
	}
	if c.Ultima != nil && c.AntiThrash > 0 && !t.Emergencia {
		if ultima, ok := c.Ultima(t.Usuario); ok && c.Ahora.Sub(ultima) < c.AntiThrash {
			return ErrAntiThrash
		}
	}
	return nil
}

func validarPassword(p string) error {
	if p == "" || len(p) > largoMaximoPassword || !utf8.ValidString(p) {
		return ErrPassword
	}
	// La contraseña viaja por la entrada estándar del helper, una por línea.
	if strings.ContainsAny(p, "\n\r\x00") {
		return ErrPassword
	}
	return nil
}
