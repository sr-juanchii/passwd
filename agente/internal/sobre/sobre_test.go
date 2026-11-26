package sobre

import (
	"crypto/ecdh"
	"encoding/base64"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

// El mismo archivo que abre el backend en tests/test_servicio_agentes.py. Si
// esta prueba falla, el agente y el backend han dejado de hablar el mismo idioma.
var rutaVector = filepath.Join("..", "..", "..", "tests", "vectores", "cifrado_agente.json")

type vector struct {
	Esquema            map[string]any `json:"esquema"`
	ClavePrivadaAgente string         `json:"clave_privada_agente"`
	ClavePublicaAgente string         `json:"clave_publica_agente"`
	Sobre              Sobre          `json:"sobre"`
	Contenido          map[string]any `json:"contenido"`
}

func leerVector(t *testing.T) (vector, *ecdh.PrivateKey) {
	t.Helper()
	datos, err := os.ReadFile(rutaVector)
	if err != nil {
		t.Fatalf("no se pudo leer el vector compartido: %v", err)
	}
	var v vector
	if err := json.Unmarshal(datos, &v); err != nil {
		t.Fatal(err)
	}
	cruda, err := base64.StdEncoding.DecodeString(v.ClavePrivadaAgente)
	if err != nil {
		t.Fatal(err)
	}
	privada, err := ecdh.X25519().NewPrivateKey(cruda)
	if err != nil {
		t.Fatal(err)
	}
	return v, privada
}

func TestElVectorDelBackendSeAbre(t *testing.T) {
	v, privada := leerVector(t)
	if got := v.Esquema["info"]; got != Info {
		t.Fatalf("info HKDF del vector = %v, el agente usa %q", got, Info)
	}
	if base64.StdEncoding.EncodeToString(privada.PublicKey().Bytes()) != v.ClavePublicaAgente {
		t.Fatal("la clave pública derivada no coincide con la del vector")
	}
	claro, err := Abrir(privada, v.Sobre)
	if err != nil {
		t.Fatalf("no abre el vector del backend: %v", err)
	}
	var contenido map[string]any
	if err := json.Unmarshal(claro, &contenido); err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(contenido, v.Contenido) {
		t.Fatalf("contenido distinto:\n got %v\nwant %v", contenido, v.Contenido)
	}
}

func TestOtraClaveNoAbre(t *testing.T) {
	v, _ := leerVector(t)
	ajena, err := ecdh.X25519().GenerateKey(nil)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := Abrir(ajena, v.Sobre); !errors.Is(err, ErrNoAbre) {
		t.Fatalf("una clave ajena abrió el sobre (err = %v)", err)
	}
}

func TestUnTokenAlteradoNoAbre(t *testing.T) {
	v, privada := leerVector(t)
	crudo, err := base64.URLEncoding.DecodeString(v.Sobre.Token)
	if err != nil {
		t.Fatal(err)
	}
	// Un bit cambiado en el texto cifrado: el MAC tiene que detectarlo.
	crudo[40] ^= 0x01
	alterado := v.Sobre
	alterado.Token = base64.URLEncoding.EncodeToString(crudo)
	if _, err := Abrir(privada, alterado); !errors.Is(err, ErrNoAbre) {
		t.Fatalf("un token alterado se abrió (err = %v)", err)
	}
}

func TestVersionYEfimeraInvalidas(t *testing.T) {
	v, privada := leerVector(t)
	otra := v.Sobre
	otra.V = 2
	if _, err := Abrir(privada, otra); err == nil {
		t.Fatal("aceptó una versión de sobre desconocida")
	}
	otra = v.Sobre
	otra.Efimera = base64.StdEncoding.EncodeToString([]byte("corta"))
	if _, err := Abrir(privada, otra); err == nil {
		t.Fatal("aceptó una clave efímera mal formada")
	}
}
