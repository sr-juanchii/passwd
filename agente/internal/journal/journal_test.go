package journal

import (
	"bytes"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/sr-juanchii/passwd/agente/internal/contrato"
	"github.com/sr-juanchii/passwd/agente/internal/identidad"
)

func nuevo(t *testing.T) (*Journal, string) {
	t.Helper()
	privada, err := identidad.NuevaClave()
	if err != nil {
		t.Fatal(err)
	}
	ruta := filepath.Join(t.TempDir(), "journal.bin")
	j, err := Abrir(ruta, privada)
	if err != nil {
		t.Fatal(err)
	}
	return j, ruta
}

func TestGuardaCifradoYPurga(t *testing.T) {
	j, ruta := nuevo(t)
	e, err := j.Leer()
	if err != nil || e.EnCurso != nil {
		t.Fatalf("un journal nuevo debe estar vacío: %v %v", e, err)
	}
	e.EnCurso = &Entrada{Trabajo: contrato.Trabajo{ID: 1, Usuario: "deploy", Nueva: "Secreta-Nueva-2026", Actual: "Secreta-Actual-2026"}, Fase: FaseAplicando}
	if err := j.Guardar(e); err != nil {
		t.Fatal(err)
	}
	crudo, _ := os.ReadFile(ruta)
	if bytes.Contains(crudo, []byte("Secreta")) || bytes.Contains(crudo, []byte("deploy")) {
		t.Fatal("el journal contiene datos en claro")
	}
	info, _ := os.Stat(ruta)
	if info.Mode().Perm() != 0o600 {
		t.Fatalf("permisos %#o", info.Mode().Perm())
	}
	leido, err := j.Leer()
	if err != nil || leido.EnCurso.Trabajo.Nueva != "Secreta-Nueva-2026" {
		t.Fatalf("no sobrevive al viaje: %v", err)
	}

	ahora := time.Date(2026, 11, 26, 10, 0, 0, 0, time.UTC)
	if err := j.Purgar("deploy", ahora); err != nil {
		t.Fatal(err)
	}
	leido, _ = j.Leer()
	if leido.EnCurso != nil || !leido.Ultimas["deploy"].Equal(ahora) {
		t.Fatalf("tras purgar: %+v", leido)
	}
}

func TestOtraIdentidadNoLeeElJournal(t *testing.T) {
	j, ruta := nuevo(t)
	if err := j.Guardar(&Estado{EnCurso: &Entrada{Fase: FaseAplicando}}); err != nil {
		t.Fatal(err)
	}
	otra, _ := identidad.NuevaClave()
	ajeno, _ := Abrir(ruta, otra)
	if _, err := ajeno.Leer(); err == nil {
		t.Fatal("otra identidad leyó el journal")
	}
}

func TestUnJournalConPermisosAbiertosNoSeLee(t *testing.T) {
	j, ruta := nuevo(t)
	if err := j.Guardar(&Estado{}); err != nil {
		t.Fatal(err)
	}
	_ = os.Chmod(ruta, 0o644)
	if _, err := j.Leer(); err == nil {
		t.Fatal("se leyó un journal con permisos abiertos")
	}
}
