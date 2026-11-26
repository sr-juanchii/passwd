// Package config carga la configuración LOCAL del agente.
//
// Nada de lo que hay aquí se puede cambiar desde la red (prohibición 6 de
// docs/plan-rotacion-agentes.md §4.1): el backend al que habla, la CA en la que
// confía, el pin de su clave y el helper que ejecuta los decide quien
// administra el servidor, editando este archivo.
package config

import (
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"net/url"
	"os"
	"strings"
	"time"
)

// RutaPorDefecto es donde lo busca el servicio si no se indica otra.
const RutaPorDefecto = "/etc/passwd-agente/config.json"

// Config es el contenido del archivo de configuración.
type Config struct {
	// URL base del backend, p. ej. https://passwd.ejemplo.org. Solo https; http
	// únicamente hacia loopback, para pruebas.
	Backend string `json:"backend"`
	// CA adicional en PEM (p. ej. una CA interna). Vacío: las del sistema.
	CAFile string `json:"ca_file"`
	// Pin opcional: SHA-256, en base64, de la clave pública (SPKI) del
	// certificado del servidor. Si se indica, cualquier otro certificado se
	// rechaza aunque una CA lo avale.
	PinSHA256 string `json:"pin_sha256"`
	// Archivos de estado. Deben vivir en un directorio solo del agente.
	Identidad string `json:"identidad"`
	Journal   string `json:"journal"`
	// Socket del helper root de acción única (lo crea systemd:
	// /run/passwd-agente/helper.sock). Vacío: el agente solo late y envía
	// telemetría, sin pedir trabajos que no podría ejecutar.
	Helper string `json:"helper"`
	// Intervalo mínimo local entre dos rotaciones de la misma cuenta, en
	// minutos. Defensa ante un backend que martillee; el de verdad (24 h, con
	// excepción de emergencia) lo aplica el backend.
	AntiThrashMin int `json:"anti_thrash_min"`
}

// Cargar lee y valida el archivo.
func Cargar(ruta string) (*Config, error) {
	datos, err := os.ReadFile(ruta)
	if err != nil {
		return nil, err
	}
	var c Config
	decodificador := json.NewDecoder(strings.NewReader(string(datos)))
	decodificador.DisallowUnknownFields() // una errata no debe pasar en silencio
	if err := decodificador.Decode(&c); err != nil {
		return nil, fmt.Errorf("%s: %w", ruta, err)
	}
	c.completar()
	if err := c.Validar(); err != nil {
		return nil, fmt.Errorf("%s: %w", ruta, err)
	}
	return &c, nil
}

func (c *Config) completar() {
	if c.Identidad == "" {
		c.Identidad = "/var/lib/passwd-agente/identidad.json"
	}
	if c.Journal == "" {
		c.Journal = "/var/lib/passwd-agente/journal.bin"
	}
	if c.AntiThrashMin == 0 {
		c.AntiThrashMin = 60
	}
}

// AntiThrash devuelve el intervalo mínimo local como duración.
func (c *Config) AntiThrash() time.Duration {
	return time.Duration(c.AntiThrashMin) * time.Minute
}

// Validar comprueba lo que haría inseguro arrancar.
func (c *Config) Validar() error {
	u, err := url.Parse(c.Backend)
	if err != nil || u.Host == "" {
		return errors.New("«backend» debe ser una URL completa, p. ej. https://passwd.ejemplo.org")
	}
	if u.User != nil {
		return errors.New("«backend» no puede llevar usuario ni contraseña en la URL")
	}
	switch u.Scheme {
	case "https":
	case "http":
		if !esLoopback(u.Hostname()) {
			return errors.New("«backend» debe usar https: http solo se admite hacia loopback, para pruebas")
		}
	default:
		return fmt.Errorf("esquema no admitido en «backend»: %q", u.Scheme)
	}
	if c.Helper != "" && !strings.HasPrefix(c.Helper, "/") {
		return errors.New("«helper» debe ser la ruta absoluta del socket del helper")
	}
	if c.AntiThrashMin < 0 {
		return errors.New("«anti_thrash_min» no puede ser negativo")
	}
	return nil
}

func esLoopback(host string) bool {
	if host == "localhost" {
		return true
	}
	ip := net.ParseIP(host)
	return ip != nil && ip.IsLoopback()
}
