// Package identidad guarda quién es este agente: su token de vida corta y su
// clave privada X25519. Es el archivo más sensible del servidor para el agente
// —con él se puede suplantar hasta que el token caduque—, así que solo se
// escribe 0600 y de forma atómica, y no se lee si alguien abrió sus permisos.
package identidad

import (
	"crypto/ecdh"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"errors"
	"os"

	"github.com/sr-juanchii/passwd/agente/internal/archivo"
)

// Identidad es el contenido del archivo.
type Identidad struct {
	AgenteID      int64  `json:"agente_id"`
	Nombre        string `json:"nombre"`
	Token         string `json:"token"`
	TokenExpiraEn string `json:"token_expira_en"`
	ClavePrivada  string `json:"clave_privada"`
}

// NuevaClave genera el par X25519 del agente.
func NuevaClave() (*ecdh.PrivateKey, error) {
	return ecdh.X25519().GenerateKey(rand.Reader)
}

// ClavePublicaB64 es la forma en que el backend recibe la clave pública.
func ClavePublicaB64(privada *ecdh.PrivateKey) string {
	return base64.StdEncoding.EncodeToString(privada.PublicKey().Bytes())
}

// Privada reconstruye la clave privada guardada.
func (i *Identidad) Privada() (*ecdh.PrivateKey, error) {
	cruda, err := base64.StdEncoding.DecodeString(i.ClavePrivada)
	if err != nil {
		return nil, errors.New("clave privada ilegible en el archivo de identidad")
	}
	return ecdh.X25519().NewPrivateKey(cruda)
}

// ConClave rellena la clave privada.
func (i *Identidad) ConClave(privada *ecdh.PrivateKey) {
	i.ClavePrivada = base64.StdEncoding.EncodeToString(privada.Bytes())
}

// Leer carga la identidad, negándose si el archivo no es privado.
func Leer(ruta string) (*Identidad, error) {
	if err := archivo.ExigirPrivado(ruta); err != nil {
		return nil, err
	}
	datos, err := os.ReadFile(ruta)
	if err != nil {
		return nil, err
	}
	var i Identidad
	if err := json.Unmarshal(datos, &i); err != nil {
		return nil, errors.New("archivo de identidad ilegible")
	}
	if i.Token == "" || i.ClavePrivada == "" {
		return nil, errors.New("archivo de identidad incompleto: vuelva a enrolar el agente")
	}
	return &i, nil
}

// Guardar la escribe de forma atómica con permisos 0600.
func Guardar(ruta string, i *Identidad) error {
	datos, err := json.Marshal(i)
	if err != nil {
		return err
	}
	return archivo.EscribirAtomico(ruta, datos, 0o600)
}
