// Package sobre abre los trabajos que el backend sella para este agente.
//
// El esquema es el de app/servicios/cifrado_agente.py, sin una sola variación:
//
//	efímera X25519 del backend × clave privada del agente → secreto compartido
//	HKDF-SHA256(secreto, salt = efímera_pub ‖ agente_pub,
//	            info = "passwd-agente/trabajo/v1")          → 32 bytes
//	Fernet(esos 32 bytes)                                   → contenido JSON
//
// Fernet se descifra aquí según su especificación pública
// (https://github.com/fernet/spec), con la biblioteca estándar: AES-128-CBC
// con PKCS#7 y HMAC-SHA256 comparado en tiempo constante. No se usa una
// biblioteca de terceros porque la que existe no tiene ninguna versión
// etiquetada, y en la ruta de las contraseñas una dependencia sin versiones es
// peor que unas líneas de una especificación verificadas contra los vectores
// del backend (tests/vectores/cifrado_agente.json).
//
// No se aplica caducidad al token Fernet: la validez del trabajo la marca
// expira_en, dentro del contenido, y la comprueba el contrato.
package sobre

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/ecdh"
	"crypto/hkdf"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"errors"
	"fmt"
)

// Info es la etiqueta de derivación; debe ser idéntica a INFO_HKDF del backend.
const Info = "passwd-agente/trabajo/v1"

// Version es la única versión de sobre que este agente entiende.
const Version = 1

const (
	largoClave     = 32
	versionFernet  = 0x80
	largoCabecera  = 1 + 8 + 16 // versión + marca de tiempo + IV
	largoMAC       = sha256.Size
	largoBloqueAES = aes.BlockSize
)

// Sobre es lo que viaja por la red. Ninguno de sus campos es secreto por sí solo.
type Sobre struct {
	V       int    `json:"v"`
	Efimera string `json:"efimera"`
	Token   string `json:"token"`
}

// ErrNoAbre indica que el sobre no es para esta clave o fue alterado. A
// propósito no distingue entre los dos casos.
var ErrNoAbre = errors.New("el sobre no se abre con esta clave")

// Abrir devuelve el contenido en claro de un sobre sellado para privada.
func Abrir(privada *ecdh.PrivateKey, s Sobre) ([]byte, error) {
	if s.V != Version {
		return nil, fmt.Errorf("versión de sobre desconocida: %d", s.V)
	}
	efimera, err := base64.StdEncoding.DecodeString(s.Efimera)
	if err != nil || len(efimera) != largoClave {
		return nil, errors.New("sobre mal formado")
	}
	publicaEfimera, err := ecdh.X25519().NewPublicKey(efimera)
	if err != nil {
		return nil, errors.New("sobre mal formado")
	}
	compartido, err := privada.ECDH(publicaEfimera)
	if err != nil {
		return nil, ErrNoAbre
	}
	salt := make([]byte, 0, 2*largoClave)
	salt = append(salt, efimera...)
	salt = append(salt, privada.PublicKey().Bytes()...)
	clave, err := hkdf.Key(sha256.New, compartido, salt, Info, largoClave)
	if err != nil {
		return nil, err
	}
	return descifrarFernet(clave, s.Token)
}

// descifrarFernet implementa la verificación y el descifrado de un token Fernet.
//
// La clave de 32 bytes se parte como manda la especificación: los 16 primeros
// firman, los 16 últimos cifran. El MAC se comprueba ANTES de tocar el
// relleno, de modo que no hay oráculo de relleno que explotar.
func descifrarFernet(clave []byte, token string) ([]byte, error) {
	if len(clave) != largoClave {
		return nil, errors.New("clave Fernet de longitud incorrecta")
	}
	datos, err := base64.URLEncoding.DecodeString(token)
	if err != nil {
		return nil, ErrNoAbre
	}
	if len(datos) < largoCabecera+largoBloqueAES+largoMAC || datos[0] != versionFernet {
		return nil, ErrNoAbre
	}
	cuerpo, mac := datos[:len(datos)-largoMAC], datos[len(datos)-largoMAC:]
	firma := hmac.New(sha256.New, clave[:16])
	firma.Write(cuerpo)
	if !hmac.Equal(firma.Sum(nil), mac) {
		return nil, ErrNoAbre
	}

	iv := cuerpo[9:largoCabecera]
	cifrado := cuerpo[largoCabecera:]
	if len(cifrado) == 0 || len(cifrado)%largoBloqueAES != 0 {
		return nil, ErrNoAbre
	}
	bloque, err := aes.NewCipher(clave[16:])
	if err != nil {
		return nil, err
	}
	claro := make([]byte, len(cifrado))
	cipher.NewCBCDecrypter(bloque, iv).CryptBlocks(claro, cifrado)

	relleno := int(claro[len(claro)-1])
	if relleno < 1 || relleno > largoBloqueAES {
		return nil, ErrNoAbre
	}
	for _, b := range claro[len(claro)-relleno:] {
		if int(b) != relleno {
			return nil, ErrNoAbre
		}
	}
	return claro[:len(claro)-relleno], nil
}
