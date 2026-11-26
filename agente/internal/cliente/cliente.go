// Package cliente habla con /api/agent del backend.
//
// Solo conexiones salientes, solo al backend configurado (§4.1, prohibiciones 7
// y 8). TLS con la confianza del sistema o una CA propia y, si se configura,
// con el pin de la clave pública del servidor. No sigue redirecciones: una
// redirección es la forma más sencilla de que un intermediario se lleve el
// token, y el backend no tiene ningún motivo para emitirlas.
package cliente

import (
	"bytes"
	"context"
	"crypto/sha256"
	"crypto/subtle"
	"crypto/tls"
	"crypto/x509"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"sync"
	"time"

	"github.com/sr-juanchii/passwd/agente/internal/config"
	"github.com/sr-juanchii/passwd/agente/internal/sobre"
)

// Una respuesta del backend a un agente es pequeña: un sobre con dos
// contraseñas. Leer más sería aceptar que nos llenen la memoria.
const maxRespuesta = 256 * 1024

// ErrorAPI es una respuesta de error del backend.
type ErrorAPI struct {
	Codigo  int
	Detalle string
}

func (e *ErrorAPI) Error() string {
	return fmt.Sprintf("el backend respondió %d: %s", e.Codigo, e.Detalle)
}

// Codigo devuelve el código HTTP de un ErrorAPI, o 0 si err es otra cosa.
func Codigo(err error) int {
	var e *ErrorAPI
	if errors.As(err, &e) {
		return e.Codigo
	}
	return 0
}

// RespEnrolar es la identidad recién emitida.
type RespEnrolar struct {
	AgenteID      int64  `json:"agente_id"`
	Nombre        string `json:"nombre"`
	Token         string `json:"token"`
	TokenExpiraEn string `json:"token_expira_en"`
	IntervaloMin  int    `json:"intervalo_min"`
}

// RespSaludo es la respuesta al latido.
type RespSaludo struct {
	TokenNuevo      *string `json:"token_nuevo"`
	TokenExpiraEn   *string `json:"token_expira_en"`
	IntervaloMin    int     `json:"intervalo_min"`
	VersionMinima   string  `json:"version_minima"`
	VersionAdmitida bool    `json:"version_admitida"`
	VersionEnGracia bool    `json:"version_en_gracia"`
}

// RespTrabajo es un trabajo pendiente, aún sellado.
type RespTrabajo struct {
	TrabajoID int64       `json:"trabajo_id"`
	ExpiraEn  string      `json:"expira_en"`
	Sobre     sobre.Sobre `json:"sobre"`
}

// Cliente es la conexión con el backend.
type Cliente struct {
	base      *url.URL
	http      *http.Client
	userAgent string
	mutex     sync.RWMutex
	token     string
}

// Nuevo construye el cliente a partir de la configuración local.
func Nuevo(cfg *config.Config, token, version string) (*Cliente, error) {
	base, err := url.Parse(cfg.Backend)
	if err != nil {
		return nil, err
	}
	tlsConf := &tls.Config{MinVersion: tls.VersionTLS12}
	if cfg.CAFile != "" {
		pem, err := os.ReadFile(cfg.CAFile)
		if err != nil {
			return nil, fmt.Errorf("ca_file: %w", err)
		}
		raices, err := x509.SystemCertPool()
		if err != nil || raices == nil {
			raices = x509.NewCertPool()
		}
		if !raices.AppendCertsFromPEM(pem) {
			return nil, errors.New("ca_file no contiene ningún certificado PEM")
		}
		tlsConf.RootCAs = raices
	}
	if cfg.PinSHA256 != "" {
		pin, err := base64.StdEncoding.DecodeString(cfg.PinSHA256)
		if err != nil || len(pin) != sha256.Size {
			return nil, errors.New("pin_sha256 debe ser el SHA-256 en base64 de la clave pública del servidor")
		}
		// Se comprueba ADEMÁS de la cadena de confianza, no en su lugar.
		tlsConf.VerifyConnection = func(estado tls.ConnectionState) error {
			if len(estado.PeerCertificates) == 0 {
				return errors.New("el servidor no presentó certificado")
			}
			suma := sha256.Sum256(estado.PeerCertificates[0].RawSubjectPublicKeyInfo)
			if subtle.ConstantTimeCompare(suma[:], pin) != 1 {
				return errors.New("la clave pública del servidor no coincide con el pin configurado")
			}
			return nil
		}
	}
	transporte := &http.Transport{
		Proxy:                 http.ProxyFromEnvironment,
		TLSClientConfig:       tlsConf,
		TLSHandshakeTimeout:   10 * time.Second,
		ResponseHeaderTimeout: 20 * time.Second,
		IdleConnTimeout:       90 * time.Second,
		MaxIdleConns:          2,
	}
	return &Cliente{
		base:      base,
		userAgent: "passwd-agente/" + version,
		token:     token,
		http: &http.Client{
			Transport: transporte,
			Timeout:   30 * time.Second,
			CheckRedirect: func(*http.Request, []*http.Request) error {
				return http.ErrUseLastResponse
			},
		},
	}, nil
}

// SetToken cambia la identidad con la que se presenta (tras una renovación).
func (c *Cliente) SetToken(token string) {
	c.mutex.Lock()
	defer c.mutex.Unlock()
	c.token = token
}

func (c *Cliente) tokenActual() string {
	c.mutex.RLock()
	defer c.mutex.RUnlock()
	return c.token
}

func (c *Cliente) hacer(ctx context.Context, metodo, ruta string, cuerpo, destino any, autenticado bool) (int, error) {
	var lector io.Reader
	if cuerpo != nil {
		datos, err := json.Marshal(cuerpo)
		if err != nil {
			return 0, err
		}
		lector = bytes.NewReader(datos)
	}
	peticion, err := http.NewRequestWithContext(ctx, metodo, c.base.JoinPath("api", "agent", ruta).String(), lector)
	if err != nil {
		return 0, err
	}
	peticion.Header.Set("User-Agent", c.userAgent)
	peticion.Header.Set("Accept", "application/json")
	if cuerpo != nil {
		peticion.Header.Set("Content-Type", "application/json")
	}
	if autenticado {
		peticion.Header.Set("Authorization", "Bearer "+c.tokenActual())
	}
	respuesta, err := c.http.Do(peticion)
	if err != nil {
		return 0, err
	}
	defer respuesta.Body.Close()
	datos, err := io.ReadAll(io.LimitReader(respuesta.Body, maxRespuesta+1))
	if err != nil {
		return respuesta.StatusCode, err
	}
	if len(datos) > maxRespuesta {
		return respuesta.StatusCode, errors.New("respuesta del backend demasiado grande")
	}
	if respuesta.StatusCode < 200 || respuesta.StatusCode > 299 {
		return respuesta.StatusCode, &ErrorAPI{Codigo: respuesta.StatusCode, Detalle: detalle(datos)}
	}
	if respuesta.StatusCode == http.StatusNoContent || destino == nil {
		return respuesta.StatusCode, nil
	}
	if err := json.Unmarshal(datos, destino); err != nil {
		return respuesta.StatusCode, fmt.Errorf("respuesta del backend ilegible: %w", err)
	}
	return respuesta.StatusCode, nil
}

func detalle(datos []byte) string {
	var cuerpo struct {
		Detail any `json:"detail"`
	}
	if json.Unmarshal(datos, &cuerpo) == nil && cuerpo.Detail != nil {
		if texto, ok := cuerpo.Detail.(string); ok {
			return texto
		}
		return fmt.Sprint(cuerpo.Detail)
	}
	if len(datos) > 200 {
		datos = datos[:200]
	}
	return strconv.Quote(string(datos))
}

// Enrolar canjea el token de un solo uso por la identidad del agente.
func (c *Cliente) Enrolar(ctx context.Context, tokenEnrolamiento, clavePublica, nombreHost, version string) (*RespEnrolar, error) {
	var r RespEnrolar
	_, err := c.hacer(ctx, http.MethodPost, "enrolar", map[string]string{
		"token_enrolamiento": tokenEnrolamiento, "clave_publica": clavePublica,
		"nombre_host": nombreHost, "version": version,
	}, &r, false)
	if err != nil {
		return nil, err
	}
	return &r, nil
}

// Saludo es el latido; puede traer un token renovado.
func (c *Cliente) Saludo(ctx context.Context, version string) (*RespSaludo, error) {
	var r RespSaludo
	if _, err := c.hacer(ctx, http.MethodPost, "saludo", map[string]string{"version": version}, &r, true); err != nil {
		return nil, err
	}
	return &r, nil
}

// Pendiente devuelve el trabajo pendiente, o nil si no hay ninguno.
func (c *Cliente) Pendiente(ctx context.Context) (*RespTrabajo, error) {
	var r RespTrabajo
	codigo, err := c.hacer(ctx, http.MethodGet, "trabajos/pendiente", nil, &r, true)
	if err != nil {
		return nil, err
	}
	if codigo == http.StatusNoContent {
		return nil, nil
	}
	return &r, nil
}

// Resultado informa del cierre de un trabajo.
func (c *Cliente) Resultado(ctx context.Context, trabajoID int64, estado, verificacion, detalle string) error {
	_, err := c.hacer(ctx, http.MethodPost, fmt.Sprintf("trabajos/%d/resultado", trabajoID), map[string]string{
		"estado": estado, "verificacion": verificacion, "detalle": detalle,
	}, nil, true)
	return err
}

// Telemetria envía un latido con métricas.
func (c *Cliente) Telemetria(ctx context.Context, datos any) error {
	_, err := c.hacer(ctx, http.MethodPost, "telemetria", datos, nil, true)
	return err
}
