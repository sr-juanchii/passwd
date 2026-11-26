package main

import (
	"strings"
	"testing"
)

func TestElTokenSeLeeDeLaEntradaSinQuedarEnLaLineaDeOrdenes(t *testing.T) {
	casos := map[string]string{
		"abc123\n":             "abc123",
		"  abc123  \r\n":       "abc123",
		"abc123":               "abc123",
		"abc123\nlo-que-sigue": "abc123",
		"":                     "",
	}
	for entrada, esperado := range casos {
		obtenido, err := leerToken(strings.NewReader(entrada))
		if err != nil || obtenido != esperado {
			t.Errorf("%q: %q, %v", entrada, obtenido, err)
		}
	}
	// Acotado: una entrada desmedida no se lee entera.
	largo, _ := leerToken(strings.NewReader(strings.Repeat("x", 10_000)))
	if len(largo) > 512 {
		t.Fatalf("leyó %d bytes", len(largo))
	}
}
