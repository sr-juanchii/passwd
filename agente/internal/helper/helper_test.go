package helper

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

type sistemaFalso struct {
	cuentas map[string]string
	fijadas int
}

func (s *sistemaFalso) Existe(c string) bool { _, ok := s.cuentas[c]; return ok }
func (s *sistemaFalso) Verificar(c, p string) (bool, error) {
	return s.cuentas[c] == p, nil
}
func (s *sistemaFalso) Fijar(c, p string) error {
	if _, ok := s.cuentas[c]; !ok {
		panic("Fijar sobre una cuenta inexistente: el helper debió rechazarlo antes")
	}
	s.fijadas++
	s.cuentas[c] = p
	return nil
}

const uidAgente = 990

func nuevo() (*Helper, *sistemaFalso) {
	s := &sistemaFalso{cuentas: map[string]string{"deploy": "Actual-1", "fuera": "x"}}
	return &Helper{
		Config:    &Config{UsuarioAgente: "passwd-agente", Cuentas: []string{"deploy", "fantasma"}},
		Sistema:   s,
		UIDAgente: uidAgente,
	}, s
}

func pedir(t *testing.T, h *Helper, p Peticion, quien Llamante) Respuesta {
	t.Helper()
	datos, _ := json.Marshal(p)
	return h.Atender(strings.NewReader(string(datos)+"\n"), quien)
}

var agente = Llamante{EsSocket: true, UID: uidAgente}

func TestAplicarCompruebaLaActualYFijaLaNueva(t *testing.T) {
	h, s := nuevo()
	r := pedir(t, h, Peticion{Accion: AccionAplicar, Cuenta: "deploy", Actual: "Actual-1", Nueva: "Nueva-1"}, agente)
	if !r.OK || s.cuentas["deploy"] != "Nueva-1" {
		t.Fatalf("respuesta %+v, cuenta %q", r, s.cuentas["deploy"])
	}
}

func TestSiLaActualNoCoincideNoSeTocaNada(t *testing.T) {
	h, s := nuevo()
	r := pedir(t, h, Peticion{Accion: AccionAplicar, Cuenta: "deploy", Actual: "Otra", Nueva: "Nueva-1"}, agente)
	if r.OK || s.fijadas != 0 || s.cuentas["deploy"] != "Actual-1" {
		t.Fatalf("cambió con una contraseña actual que no coincide: %+v", r)
	}
}

func TestVerificarYRestaurar(t *testing.T) {
	h, s := nuevo()
	if r := pedir(t, h, Peticion{Accion: AccionVerificar, Cuenta: "deploy", Password: "Actual-1"}, agente); !r.OK {
		t.Fatalf("no verificó la correcta: %+v", r)
	}
	if r := pedir(t, h, Peticion{Accion: AccionVerificar, Cuenta: "deploy", Password: "mala"}, agente); r.OK || r.Error != "" {
		t.Fatalf("una contraseña incorrecta es «no», no un error: %+v", r)
	}
	if r := pedir(t, h, Peticion{Accion: AccionRestaurar, Cuenta: "deploy", Valor: "Vuelta-1"}, agente); !r.OK || s.cuentas["deploy"] != "Vuelta-1" {
		t.Fatalf("restaurar = %+v", r)
	}
}

func TestRechazos(t *testing.T) {
	casos := map[string]struct {
		p     Peticion
		quien Llamante
	}{
		"otro usuario por el socket":     {Peticion{Accion: AccionVerificar, Cuenta: "deploy", Password: "Actual-1"}, Llamante{EsSocket: true, UID: 1000}},
		"root por el socket":             {Peticion{Accion: AccionVerificar, Cuenta: "deploy", Password: "Actual-1"}, Llamante{EsSocket: true, UID: 0}},
		"no root fuera del socket":       {Peticion{Accion: AccionVerificar, Cuenta: "deploy", Password: "Actual-1"}, Llamante{UID: 1000}},
		"cuenta fuera de la lista":       {Peticion{Accion: AccionRestaurar, Cuenta: "fuera", Valor: "x"}, agente},
		"cuenta en la lista sin existir": {Peticion{Accion: AccionRestaurar, Cuenta: "fantasma", Valor: "x"}, agente},
		"cuenta con formato raro":        {Peticion{Accion: AccionRestaurar, Cuenta: "deploy;id", Valor: "x"}, agente},
		"acción desconocida":             {Peticion{Accion: "ejecutar", Cuenta: "deploy"}, agente},
		"salto de línea":                 {Peticion{Accion: AccionRestaurar, Cuenta: "deploy", Valor: "a\nb"}, agente},
		"contraseña vacía":               {Peticion{Accion: AccionRestaurar, Cuenta: "deploy"}, agente},
	}
	for nombre, caso := range casos {
		h, s := nuevo()
		if r := pedir(t, h, caso.p, caso.quien); r.OK || r.Error == "" {
			t.Errorf("%s: se aceptó (%+v)", nombre, r)
		}
		if s.fijadas != 0 {
			t.Errorf("%s: se fijó una contraseña", nombre)
		}
	}
}

func TestRootPuedeInvocarloAManoFueraDelSocket(t *testing.T) {
	h, _ := nuevo()
	if r := pedir(t, h, Peticion{Accion: AccionVerificar, Cuenta: "deploy", Password: "Actual-1"}, Llamante{UID: 0}); !r.OK {
		t.Fatalf("respuesta %+v", r)
	}
}

func TestUnaPeticionDesmedidaOConCamposExtraSeRechaza(t *testing.T) {
	h, _ := nuevo()
	enorme := `{"accion":"verificar","cuenta":"deploy","password":"` + strings.Repeat("a", MaxPeticion) + `"}` + "\n"
	if r := h.Atender(strings.NewReader(enorme), agente); r.OK {
		t.Fatal("aceptó una petición por encima del tope")
	}
	extra := `{"accion":"verificar","cuenta":"deploy","password":"Actual-1","comando":"rm"}` + "\n"
	if r := h.Atender(strings.NewReader(extra), agente); r.OK {
		t.Fatal("aceptó un campo desconocido")
	}
}

func TestLaRespuestaNuncaLlevaUnaContrasena(t *testing.T) {
	h, _ := nuevo()
	for _, p := range []Peticion{
		{Accion: AccionAplicar, Cuenta: "deploy", Actual: "Secreta-Mal", Nueva: "Secreta-Nueva"},
		{Accion: AccionRestaurar, Cuenta: "fuera", Valor: "Secreta-Valor"},
	} {
		datos, _ := json.Marshal(pedir(t, h, p, agente))
		if strings.Contains(string(datos), "Secreta") {
			t.Fatalf("la respuesta contiene una contraseña: %s", datos)
		}
	}
}

func TestLaConfiguracionDebeSerDeRootYNoEscribiblePorOtros(t *testing.T) {
	ruta := filepath.Join(t.TempDir(), "helper.json")
	if err := os.WriteFile(ruta, []byte(`{"usuario_agente":"passwd-agente","cuentas":["deploy"]}`), 0o644); err != nil {
		t.Fatal(err)
	}
	if os.Geteuid() == 0 {
		if _, err := CargarConfig(ruta); err != nil {
			t.Fatalf("una configuración de root 0644 es válida: %v", err)
		}
		_ = os.Chmod(ruta, 0o666)
		if _, err := CargarConfig(ruta); err == nil {
			t.Fatal("aceptó una configuración escribible por otros")
		}
		return
	}
	if _, err := CargarConfig(ruta); err == nil {
		t.Fatal("aceptó una configuración que no es de root")
	}
}

func TestLosRechazosDicenQueNoSeTocoNadaYUnFalloAlFijarNo(t *testing.T) {
	h, _ := nuevo()
	r := pedir(t, h, Peticion{Accion: AccionAplicar, Cuenta: "fuera", Actual: "x", Nueva: "y"}, agente)
	if r.OK || !r.SinCambios {
		t.Fatalf("cuenta fuera de la lista: %+v", r)
	}
	r = pedir(t, h, Peticion{Accion: AccionAplicar, Cuenta: "deploy", Actual: "Otra", Nueva: "y"}, agente)
	if r.OK || !r.SinCambios {
		t.Fatalf("actual que no coincide: %+v", r)
	}

	h.Sistema = &sistemaQueFallaAlFijar{sistemaFalso{cuentas: map[string]string{"deploy": "Actual-1"}}}
	r = pedir(t, h, Peticion{Accion: AccionAplicar, Cuenta: "deploy", Actual: "Actual-1", Nueva: "y"}, agente)
	if r.OK || r.SinCambios {
		t.Fatalf("un fallo de chpasswd no puede prometer que no se tocó nada: %+v", r)
	}
}

type sistemaQueFallaAlFijar struct{ sistemaFalso }

func (s *sistemaQueFallaAlFijar) Fijar(string, string) error { return errors.New("chpasswd: fallo") }
