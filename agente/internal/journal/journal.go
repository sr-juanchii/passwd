// Package journal guarda, cifrado, el trabajo que el agente tiene entre manos.
//
// Si el agente muere entre «apliqué» y «confirmé», al rearrancar sabe qué
// estaba haciendo y con qué contraseñas, y puede completar o revertir: nunca un
// estado indeterminado en silencio (docs/plan-rotacion-agentes.md §2.2, paso 5).
//
// El archivo se cifra con AES-256-GCM y una clave derivada por HKDF de la clave
// privada del agente, así que solo sirve en este servidor y con esta identidad.
// Contiene únicamente el trabajo en curso —se purga al cerrarlo— y, sin
// secretos, la fecha de la última rotación de cada cuenta para el anti-thrash
// local.
//
// Limitación conocida: al purgar, el archivo nuevo sustituye al anterior por
// renombrado, pero los bloques antiguos del disco no se sobrescriben. Por eso el
// contenido va cifrado, y por eso la clave depende de la identidad: re-enrolar
// el agente deja ilegible cualquier resto.
package journal

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/ecdh"
	"crypto/hkdf"
	"crypto/rand"
	"crypto/sha256"
	"encoding/json"
	"errors"
	"io/fs"
	"os"
	"sync"
	"time"

	"github.com/sr-juanchii/passwd/agente/internal/archivo"
	"github.com/sr-juanchii/passwd/agente/internal/contrato"
)

const info = "passwd-agente/journal/v1"

// Fases de un trabajo en curso.
const (
	FaseAplicando = "aplicando" // se va a cambiar o se estaba cambiando
	FaseCerrada   = "cerrada"   // el resultado está decidido; falta informarlo
)

// Entrada es el trabajo en curso.
type Entrada struct {
	Trabajo      contrato.Trabajo `json:"trabajo"`
	Fase         string           `json:"fase"`
	Resultado    string           `json:"resultado,omitempty"`
	Verificacion string           `json:"verificacion,omitempty"`
	Detalle      string           `json:"detalle,omitempty"`
}

// Estado es todo el contenido del journal.
type Estado struct {
	EnCurso *Entrada             `json:"en_curso,omitempty"`
	Ultimas map[string]time.Time `json:"ultimas"`
}

// Journal es el archivo y su clave.
type Journal struct {
	ruta  string
	aead  cipher.AEAD
	mutex sync.Mutex
}

// Abrir prepara el journal de ruta con la clave derivada de privada.
func Abrir(ruta string, privada *ecdh.PrivateKey) (*Journal, error) {
	clave, err := hkdf.Key(sha256.New, privada.Bytes(), nil, info, 32)
	if err != nil {
		return nil, err
	}
	bloque, err := aes.NewCipher(clave)
	if err != nil {
		return nil, err
	}
	aead, err := cipher.NewGCM(bloque)
	if err != nil {
		return nil, err
	}
	return &Journal{ruta: ruta, aead: aead}, nil
}

// Leer devuelve el estado guardado, o uno vacío si aún no hay archivo.
func (j *Journal) Leer() (*Estado, error) {
	j.mutex.Lock()
	defer j.mutex.Unlock()
	return j.leer()
}

func (j *Journal) leer() (*Estado, error) {
	datos, err := os.ReadFile(j.ruta)
	if errors.Is(err, fs.ErrNotExist) {
		return &Estado{Ultimas: map[string]time.Time{}}, nil
	}
	if err != nil {
		return nil, err
	}
	if err := archivo.ExigirPrivado(j.ruta); err != nil {
		return nil, err
	}
	tam := j.aead.NonceSize()
	if len(datos) < tam {
		return nil, errors.New("journal truncado")
	}
	claro, err := j.aead.Open(nil, datos[:tam], datos[tam:], nil)
	if err != nil {
		return nil, errors.New("journal ilegible con esta identidad")
	}
	var e Estado
	if err := json.Unmarshal(claro, &e); err != nil {
		return nil, err
	}
	if e.Ultimas == nil {
		e.Ultimas = map[string]time.Time{}
	}
	return &e, nil
}

// Guardar escribe el estado completo, cifrado y de forma atómica.
func (j *Journal) Guardar(e *Estado) error {
	j.mutex.Lock()
	defer j.mutex.Unlock()
	claro, err := json.Marshal(e)
	if err != nil {
		return err
	}
	nonce := make([]byte, j.aead.NonceSize())
	if _, err := rand.Read(nonce); err != nil {
		return err
	}
	return archivo.EscribirAtomico(j.ruta, j.aead.Seal(nonce, nonce, claro, nil), 0o600)
}

// Purgar quita el trabajo en curso (y con él sus contraseñas) y apunta la
// rotación si se aplicó.
func (j *Journal) Purgar(usuarioRotado string, cuando time.Time) error {
	e, err := j.Leer()
	if err != nil {
		return err
	}
	e.EnCurso = nil
	if usuarioRotado != "" {
		e.Ultimas[usuarioRotado] = cuando
	}
	return j.Guardar(e)
}
