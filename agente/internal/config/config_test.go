package config

import (
	"os"
	"path/filepath"
	"testing"
)

func escribir(t *testing.T, contenido string) string {
	t.Helper()
	ruta := filepath.Join(t.TempDir(), "config.json")
	if err := os.WriteFile(ruta, []byte(contenido), 0o600); err != nil {
		t.Fatal(err)
	}
	return ruta
}

func TestHttpsSeAceptaYCompletaLosValoresPorDefecto(t *testing.T) {
	c, err := Cargar(escribir(t, `{"backend": "https://passwd.ejemplo.org"}`))
	if err != nil {
		t.Fatal(err)
	}
	if c.Identidad == "" || c.Journal == "" || c.AntiThrashMin != 60 {
		t.Fatalf("valores por defecto sin completar: %+v", c)
	}
}

func TestHttpSoloHaciaLoopback(t *testing.T) {
	for _, ok := range []string{"http://127.0.0.1:8000", "http://localhost:8000", "http://[::1]:8000"} {
		if _, err := Cargar(escribir(t, `{"backend": "`+ok+`"}`)); err != nil {
			t.Errorf("%s debería aceptarse: %v", ok, err)
		}
	}
	for _, malo := range []string{"http://passwd.ejemplo.org", "http://10.0.0.5", "ftp://x", "https://u:p@x.org", "nada"} {
		if _, err := Cargar(escribir(t, `{"backend": "`+malo+`"}`)); err == nil {
			t.Errorf("%s debería rechazarse", malo)
		}
	}
}

func TestUnaClaveDesconocidaSeRechaza(t *testing.T) {
	if _, err := Cargar(escribir(t, `{"backend": "https://x.org", "backnd": "errata"}`)); err == nil {
		t.Fatal("una errata en la configuración pasó en silencio")
	}
}
