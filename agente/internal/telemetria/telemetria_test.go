package telemetria

import (
	"context"
	"encoding/json"
	"strings"
	"testing"
)

func TestRecogerEnEsteHostDevuelveAlgoAcotado(t *testing.T) {
	d := Recoger(context.Background())
	if d.RAMPct == nil || d.UptimeS == nil {
		t.Fatalf("no se leyeron métricas básicas: %+v", d)
	}
	datos, _ := json.Marshal(d)
	if len(datos) > MaxBytes {
		t.Fatalf("la telemetría ocupa %d bytes, tope %d", len(datos), MaxBytes)
	}
}

func TestAcotarRecortaYLoDice(t *testing.T) {
	d := Datos{SistemaOperativo: strings.Repeat("x", 500)}
	for i := 0; i < 100; i++ {
		d.Discos = append(d.Discos, Disco{Montaje: "/" + strings.Repeat("m", 300)})
	}
	a := Acotar(d)
	if !a.Recortada {
		t.Fatal("recortó sin decirlo")
	}
	if len([]rune(a.SistemaOperativo)) != LargoTexto || len(a.Discos) > MaxDiscos {
		t.Fatalf("no acotó: SO %d, discos %d", len(a.SistemaOperativo), len(a.Discos))
	}
	if datos, _ := json.Marshal(a); len(datos) > MaxBytes {
		t.Fatalf("%d bytes tras acotar", len(datos))
	}
}

func TestSinNadaQueRecortarNoSeMarca(t *testing.T) {
	if Acotar(Datos{SistemaOperativo: "Debian 13", Discos: []Disco{{Montaje: "/"}}}).Recortada {
		t.Fatal("marcó recortada una telemetría que cabía")
	}
}
