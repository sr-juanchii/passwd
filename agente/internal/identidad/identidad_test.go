package identidad

import (
	"os"
	"path/filepath"
	"testing"
)

func TestGuardarYLeerConservaLaClave(t *testing.T) {
	ruta := filepath.Join(t.TempDir(), "identidad.json")
	privada, err := NuevaClave()
	if err != nil {
		t.Fatal(err)
	}
	i := &Identidad{AgenteID: 7, Nombre: "agente-1", Token: "tok"}
	i.ConClave(privada)
	if err := Guardar(ruta, i); err != nil {
		t.Fatal(err)
	}
	info, _ := os.Stat(ruta)
	if info.Mode().Perm() != 0o600 {
		t.Fatalf("permisos %#o, se esperaba 0600", info.Mode().Perm())
	}
	leida, err := Leer(ruta)
	if err != nil {
		t.Fatal(err)
	}
	recuperada, err := leida.Privada()
	if err != nil || !recuperada.Equal(privada) {
		t.Fatalf("la clave privada no sobrevive al viaje: %v", err)
	}
}

func TestUnArchivoConPermisosAbiertosNoSeLee(t *testing.T) {
	ruta := filepath.Join(t.TempDir(), "identidad.json")
	i := &Identidad{Token: "tok", ClavePrivada: "x"}
	if err := Guardar(ruta, i); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(ruta, 0o644); err != nil {
		t.Fatal(err)
	}
	if _, err := Leer(ruta); err == nil {
		t.Fatal("se leyó una identidad legible por otros usuarios")
	}
}

func TestLaRenovacionReescribeSinDejarTemporales(t *testing.T) {
	dir := t.TempDir()
	ruta := filepath.Join(dir, "identidad.json")
	i := &Identidad{Token: "viejo", ClavePrivada: "x"}
	if err := Guardar(ruta, i); err != nil {
		t.Fatal(err)
	}
	i.Token = "nuevo"
	if err := Guardar(ruta, i); err != nil {
		t.Fatal(err)
	}
	leida, err := Leer(ruta)
	if err != nil || leida.Token != "nuevo" {
		t.Fatalf("token tras renovar = %v (%v)", leida, err)
	}
	entradas, _ := os.ReadDir(dir)
	if len(entradas) != 1 {
		t.Fatalf("quedaron archivos temporales: %v", entradas)
	}
}
