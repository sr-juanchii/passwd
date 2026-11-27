package contrato

import (
	"errors"
	"testing"
	"time"
)

var ahora = time.Date(2026, 11, 26, 10, 0, 0, 0, time.UTC)

func valido() Trabajo {
	return Trabajo{ID: 42, Tipo: TipoRotarCuenta, Usuario: "deploy", Nueva: "Nueva-2026!x",
		Actual: "Actual-2026!x", ExpiraEn: "2026-11-26T10:15:00"}
}

func ctx() Contexto { return Contexto{Ahora: ahora, AntiThrash: time.Hour} }

func TestUnTrabajoValidoPasa(t *testing.T) {
	if err := Validar(valido(), ctx()); err != nil {
		t.Fatal(err)
	}
}

func TestRechazosDelContrato(t *testing.T) {
	casos := map[string]struct {
		mutar func(*Trabajo, *Contexto)
		err   error
	}{
		"tipo desconocido": {func(t *Trabajo, _ *Contexto) { t.Tipo = "ejecutar_comando" }, ErrTipo},
		"tipo vacío":       {func(t *Trabajo, _ *Contexto) { t.Tipo = "" }, ErrTipo},
		"vencido":          {func(t *Trabajo, _ *Contexto) { t.ExpiraEn = "2026-11-26T09:59:59" }, ErrVencido},
		"justo al vencer":  {func(t *Trabajo, _ *Contexto) { t.ExpiraEn = "2026-11-26T10:00:00" }, ErrVencido},
		"concurrente":      {func(_ *Trabajo, c *Contexto) { c.EnCurso = 7 }, ErrConcurrente},
		"usuario raro":     {func(t *Trabajo, _ *Contexto) { t.Usuario = "root;reboot" }, ErrUsuario},
		"usuario vacío":    {func(t *Trabajo, _ *Contexto) { t.Usuario = "" }, ErrUsuario},
		"salto de línea":   {func(t *Trabajo, _ *Contexto) { t.Nueva = "a\nb" }, ErrPassword},
		"NUL":              {func(t *Trabajo, _ *Contexto) { t.Actual = "a\x00b" }, ErrPassword},
		"anti-thrash": {func(_ *Trabajo, c *Contexto) {
			c.Ultima = func(string) (time.Time, bool) { return ahora.Add(-10 * time.Minute), true }
		}, ErrAntiThrash},
	}
	for nombre, caso := range casos {
		trabajo, contexto := valido(), ctx()
		caso.mutar(&trabajo, &contexto)
		if err := Validar(trabajo, contexto); !errors.Is(err, caso.err) {
			t.Errorf("%s: err = %v, se esperaba %v", nombre, err, caso.err)
		}
	}
}

func TestElMismoTrabajoEnCursoNoEsConcurrente(t *testing.T) {
	c := ctx()
	c.EnCurso = 42
	if err := Validar(valido(), c); err != nil {
		t.Fatalf("una re-entrega del mismo trabajo se tomó por concurrente: %v", err)
	}
}

func TestPasadoElIntervaloLocalSePuedeRotar(t *testing.T) {
	c := ctx()
	c.Ultima = func(string) (time.Time, bool) { return ahora.Add(-2 * time.Hour), true }
	if err := Validar(valido(), c); err != nil {
		t.Fatal(err)
	}
}

func TestUnaEmergenciaSaltaElAntiThrashLocal(t *testing.T) {
	// La vía de emergencia, autorizada y auditada en el backend, es la única
	// excepción al intervalo mínimo: el agente la respeta igual que el backend.
	c := ctx()
	c.Ultima = func(string) (time.Time, bool) { return ahora.Add(-10 * time.Minute), true }
	urgente := valido()
	urgente.Emergencia = true
	if err := Validar(urgente, c); err != nil {
		t.Fatalf("una emergencia se frenó por el anti-thrash local: %v", err)
	}
	if err := Validar(valido(), c); !errors.Is(err, ErrAntiThrash) {
		t.Fatalf("sin emergencia debía frenarse: %v", err)
	}
}
