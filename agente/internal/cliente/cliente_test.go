package cliente

import (
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"encoding/pem"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"

	"github.com/sr-juanchii/passwd/agente/internal/config"
)

func cfg(t *testing.T, url string) *config.Config {
	t.Helper()
	return &config.Config{Backend: url}
}

func TestSaludoPendienteYResultado(t *testing.T) {
	var autorizacion string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		autorizacion = r.Header.Get("Authorization")
		switch r.URL.Path {
		case "/api/agent/saludo":
			_ = json.NewEncoder(w).Encode(map[string]any{"token_nuevo": "renovado", "intervalo_min": 15, "version_admitida": true})
		case "/api/agent/trabajos/pendiente":
			w.WriteHeader(http.StatusNoContent)
		case "/api/agent/trabajos/9/resultado":
			w.WriteHeader(http.StatusConflict)
			_, _ = w.Write([]byte(`{"detail": "Este trabajo ya está en «aplicado»."}`))
		default:
			http.NotFound(w, r)
		}
	}))
	defer srv.Close()

	c, err := Nuevo(cfg(t, srv.URL), "tok", "1.4.0")
	if err != nil {
		t.Fatal(err)
	}
	s, err := c.Saludo(context.Background(), "1.4.0")
	if err != nil || s.TokenNuevo == nil || *s.TokenNuevo != "renovado" || !s.VersionAdmitida {
		t.Fatalf("saludo = %+v, %v", s, err)
	}
	if autorizacion != "Bearer tok" {
		t.Fatalf("Authorization = %q", autorizacion)
	}
	trabajo, err := c.Pendiente(context.Background())
	if err != nil || trabajo != nil {
		t.Fatalf("204 debe ser «sin trabajo»: %v %v", trabajo, err)
	}
	err = c.Resultado(context.Background(), 9, "aplicado", "local", "")
	if Codigo(err) != http.StatusConflict {
		t.Fatalf("se esperaba 409, err = %v", err)
	}
}

func TestNoSigueRedirecciones(t *testing.T) {
	var llegoAlDestino bool
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/robar" {
			llegoAlDestino = true
			return
		}
		http.Redirect(w, r, "/robar", http.StatusFound)
	}))
	defer srv.Close()
	c, _ := Nuevo(cfg(t, srv.URL), "tok", "1.4.0")
	if _, err := c.Saludo(context.Background(), "1.4.0"); Codigo(err) != http.StatusFound {
		t.Fatalf("err = %v", err)
	}
	if llegoAlDestino {
		t.Fatal("el cliente siguió la redirección (y con ella, su token)")
	}
}

func servidorTLS(t *testing.T) (*httptest.Server, string, string) {
	t.Helper()
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(map[string]any{"intervalo_min": 15})
	}))
	certificado := srv.Certificate()
	ca := filepath.Join(t.TempDir(), "ca.pem")
	if err := os.WriteFile(ca, pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: certificado.Raw}), 0o600); err != nil {
		t.Fatal(err)
	}
	suma := sha256.Sum256(certificado.RawSubjectPublicKeyInfo)
	return srv, ca, base64.StdEncoding.EncodeToString(suma[:])
}

func TestTLSConCAPropiaYPin(t *testing.T) {
	srv, ca, pin := servidorTLS(t)
	defer srv.Close()

	sinCA, _ := Nuevo(&config.Config{Backend: srv.URL}, "tok", "1.4.0")
	if _, err := sinCA.Saludo(context.Background(), "1.4.0"); err == nil {
		t.Fatal("aceptó un certificado de una CA en la que no confía")
	}

	conCA, _ := Nuevo(&config.Config{Backend: srv.URL, CAFile: ca, PinSHA256: pin}, "tok", "1.4.0")
	if _, err := conCA.Saludo(context.Background(), "1.4.0"); err != nil {
		t.Fatalf("con la CA y el pin correctos debe conectar: %v", err)
	}

	otroPin := sha256.Sum256([]byte("otra clave"))
	pinMalo, _ := Nuevo(&config.Config{Backend: srv.URL, CAFile: ca,
		PinSHA256: base64.StdEncoding.EncodeToString(otroPin[:])}, "tok", "1.4.0")
	if _, err := pinMalo.Saludo(context.Background(), "1.4.0"); err == nil {
		t.Fatal("conectó con un pin que no coincide")
	}
}

func TestLaRespuestaDesmedidaSeCorta(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write(make([]byte, maxRespuesta+10))
	}))
	defer srv.Close()
	c, _ := Nuevo(cfg(t, srv.URL), "tok", "1.4.0")
	if _, err := c.Saludo(context.Background(), "1.4.0"); err == nil {
		t.Fatal("aceptó una respuesta por encima del tope")
	}
}
