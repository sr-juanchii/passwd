package ejecutor

import (
	"context"
	"crypto/aes"
	"crypto/cipher"
	"crypto/ecdh"
	"crypto/hkdf"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/binary"
	"encoding/json"
	"errors"
	"path/filepath"
	"testing"
	"time"

	"github.com/sr-juanchii/passwd/agente/internal/cliente"
	"github.com/sr-juanchii/passwd/agente/internal/contrato"
	"github.com/sr-juanchii/passwd/agente/internal/identidad"
	"github.com/sr-juanchii/passwd/agente/internal/journal"
	"github.com/sr-juanchii/passwd/agente/internal/sobre"
)

var ahora = time.Date(2026, 11, 26, 10, 0, 0, 0, time.UTC)

// --- Sellado de prueba: lo mismo que hace el backend en Python. -------------

func sellar(t *testing.T, destino *ecdh.PublicKey, contenido any) sobre.Sobre {
	t.Helper()
	efimera, _ := ecdh.X25519().GenerateKey(rand.Reader)
	compartido, _ := efimera.ECDH(destino)
	salt := append(append([]byte{}, efimera.PublicKey().Bytes()...), destino.Bytes()...)
	clave, _ := hkdf.Key(sha256.New, compartido, salt, sobre.Info, 32)
	claro, _ := json.Marshal(contenido)
	relleno := aes.BlockSize - len(claro)%aes.BlockSize
	for i := 0; i < relleno; i++ {
		claro = append(claro, byte(relleno))
	}
	iv := make([]byte, aes.BlockSize)
	_, _ = rand.Read(iv)
	bloque, _ := aes.NewCipher(clave[16:])
	cifrado := make([]byte, len(claro))
	cipher.NewCBCEncrypter(bloque, iv).CryptBlocks(cifrado, claro)
	cuerpo := []byte{0x80}
	cuerpo = binary.BigEndian.AppendUint64(cuerpo, uint64(ahora.Unix()))
	cuerpo = append(append(cuerpo, iv...), cifrado...)
	firma := hmac.New(sha256.New, clave[:16])
	firma.Write(cuerpo)
	token := base64.URLEncoding.EncodeToString(append(cuerpo, firma.Sum(nil)...))
	return sobre.Sobre{V: 1, Efimera: base64.StdEncoding.EncodeToString(efimera.PublicKey().Bytes()), Token: token}
}

// --- Dobles de prueba. ------------------------------------------------------

type resultado struct {
	id                            int64
	estado, verificacion, detalle string
}

type apiFalsa struct {
	pendiente   *cliente.RespTrabajo
	resultados  []resultado
	fallosRed   int // los primeros N Resultado fallan por red
	token       string
	tokenNuevo  *string
	telemetrias int
}

func (a *apiFalsa) Saludo(context.Context, string) (*cliente.RespSaludo, error) {
	return &cliente.RespSaludo{IntervaloMin: 15, VersionAdmitida: true, TokenNuevo: a.tokenNuevo}, nil
}
func (a *apiFalsa) Pendiente(context.Context) (*cliente.RespTrabajo, error) {
	p := a.pendiente
	a.pendiente = nil
	return p, nil
}
func (a *apiFalsa) Resultado(_ context.Context, id int64, estado, verificacion, detalle string) error {
	if a.fallosRed > 0 {
		a.fallosRed--
		return errors.New("conexión rechazada")
	}
	a.resultados = append(a.resultados, resultado{id, estado, verificacion, detalle})
	return nil
}
func (a *apiFalsa) Telemetria(context.Context, any) error { a.telemetrias++; return nil }
func (a *apiFalsa) SetToken(t string)                     { a.token = t }

// rotadorFalso guarda la contraseña de cada cuenta en memoria.
type rotadorFalso struct {
	cuentas    map[string]string
	estropea   bool   // Aplicar deja una contraseña que no es la nueva
	alAplicar  func() // se llama al entrar en Aplicar, antes de tocar la cuenta
	aplicados  int
	revertidos int
}

func (r *rotadorFalso) Aplicar(_ context.Context, u, actual, nueva string) error {
	r.aplicados++
	if r.alAplicar != nil {
		r.alAplicar()
	}
	if r.cuentas[u] != actual {
		return errors.New("la contraseña actual no coincide")
	}
	if r.estropea {
		r.cuentas[u] = "algo-que-no-es-la-nueva"
		return nil
	}
	r.cuentas[u] = nueva
	return nil
}
func (r *rotadorFalso) Verificar(_ context.Context, u, p string) (bool, error) {
	return r.cuentas[u] == p, nil
}
func (r *rotadorFalso) Revertir(_ context.Context, u, _, actual string) error {
	r.revertidos++
	r.cuentas[u] = actual
	return nil
}

type escenario struct {
	e   *Ejecutor
	api *apiFalsa
	rot *rotadorFalso
}

func nuevo(t *testing.T) *escenario {
	t.Helper()
	privada, _ := identidad.NuevaClave()
	j, err := journal.Abrir(filepath.Join(t.TempDir(), "journal.bin"), privada)
	if err != nil {
		t.Fatal(err)
	}
	api := &apiFalsa{}
	rot := &rotadorFalso{cuentas: map[string]string{"deploy": "Actual-2026!x"}}
	return &escenario{
		e: &Ejecutor{API: api, Journal: j, Rotador: rot, Privada: privada, Version: "1.4.0",
			AntiThrash: time.Hour, Ahora: func() time.Time { return ahora }},
		api: api, rot: rot,
	}
}

func (s *escenario) trabajo(t *testing.T, id int64, cambios func(*contrato.Trabajo)) *cliente.RespTrabajo {
	t.Helper()
	tr := contrato.Trabajo{ID: id, Tipo: contrato.TipoRotarCuenta, Usuario: "deploy",
		Nueva: "Nueva-2026!x", Actual: "Actual-2026!x", ExpiraEn: "2026-11-26T10:15:00"}
	if cambios != nil {
		cambios(&tr)
	}
	return &cliente.RespTrabajo{TrabajoID: id, Sobre: sellar(t, s.e.Privada.PublicKey(), tr)}
}

func (s *escenario) journalVacio(t *testing.T) {
	t.Helper()
	estado, err := s.e.Journal.Leer()
	if err != nil || estado.EnCurso != nil {
		t.Fatalf("el journal debería estar purgado: %+v %v", estado, err)
	}
}

// --- Pruebas. ---------------------------------------------------------------

func TestAplicaVerificaYConfirma(t *testing.T) {
	s := nuevo(t)
	s.api.pendiente = s.trabajo(t, 1, nil)
	if _, err := s.e.Ciclo(context.Background()); err != nil {
		t.Fatal(err)
	}
	if s.rot.cuentas["deploy"] != "Nueva-2026!x" {
		t.Fatal("no aplicó la contraseña nueva")
	}
	if len(s.api.resultados) != 1 || s.api.resultados[0] != (resultado{1, Aplicado, VerificacionLocal, ""}) {
		t.Fatalf("resultados = %+v", s.api.resultados)
	}
	s.journalVacio(t)
}

func TestSiLaNuevaNoVerificaRevierte(t *testing.T) {
	s := nuevo(t)
	s.rot.estropea = true
	s.api.pendiente = s.trabajo(t, 2, nil)
	if _, err := s.e.Ciclo(context.Background()); err != nil {
		t.Fatal(err)
	}
	if s.rot.cuentas["deploy"] != "Actual-2026!x" || s.rot.revertidos != 1 {
		t.Fatalf("no revirtió: %v (revertidos %d)", s.rot.cuentas, s.rot.revertidos)
	}
	if s.api.resultados[0].estado != Revertido {
		t.Fatalf("resultado = %+v", s.api.resultados[0])
	}
	s.journalVacio(t)
}

func TestUnTrabajoQueIncumpleElContratoNoSeEjecuta(t *testing.T) {
	s := nuevo(t)
	s.api.pendiente = s.trabajo(t, 3, func(tr *contrato.Trabajo) { tr.Tipo = "ejecutar_comando" })
	if _, err := s.e.Ciclo(context.Background()); err != nil {
		t.Fatal(err)
	}
	if s.rot.aplicados != 0 {
		t.Fatal("ejecutó un trabajo de tipo desconocido")
	}
	if r := s.api.resultados[0]; r.estado != Fallado || r.detalle != contrato.ErrTipo.Error() {
		t.Fatalf("resultado = %+v", r)
	}
}

func TestUnTrabajoVencidoNoSeAplica(t *testing.T) {
	s := nuevo(t)
	s.api.pendiente = s.trabajo(t, 4, func(tr *contrato.Trabajo) { tr.ExpiraEn = "2026-11-26T09:00:00" })
	_, _ = s.e.Ciclo(context.Background())
	if s.rot.aplicados != 0 || s.api.resultados[0].estado != Fallado {
		t.Fatalf("aplicó un trabajo vencido: %+v", s.api.resultados)
	}
}

func TestElAntiThrashLocalFrenaLaSegundaRotacion(t *testing.T) {
	s := nuevo(t)
	s.api.pendiente = s.trabajo(t, 5, nil)
	_, _ = s.e.Ciclo(context.Background())
	s.api.pendiente = s.trabajo(t, 6, func(tr *contrato.Trabajo) {
		tr.Actual, tr.Nueva = "Nueva-2026!x", "Otra-2026!x"
	})
	_, _ = s.e.Ciclo(context.Background())
	if s.rot.aplicados != 1 || s.api.resultados[1].detalle != contrato.ErrAntiThrash.Error() {
		t.Fatalf("aplicados %d, resultados %+v", s.rot.aplicados, s.api.resultados)
	}
}

func TestUnSobreAjenoSeRechazaSinTocarNada(t *testing.T) {
	s := nuevo(t)
	otra, _ := identidad.NuevaClave()
	tr := s.trabajo(t, 7, nil)
	tr.Sobre = sellar(t, otra.PublicKey(), contrato.Trabajo{ID: 7})
	s.api.pendiente = tr
	_, _ = s.e.Ciclo(context.Background())
	if s.rot.aplicados != 0 || s.api.resultados[0].estado != Fallado {
		t.Fatalf("resultados = %+v", s.api.resultados)
	}
}

func TestTrasUnaCaidaRecuperaYConfirmaLoAplicado(t *testing.T) {
	s := nuevo(t)
	tr := contrato.Trabajo{ID: 8, Tipo: contrato.TipoRotarCuenta, Usuario: "deploy",
		Nueva: "Nueva-2026!x", Actual: "Actual-2026!x", ExpiraEn: "2026-11-26T10:15:00"}
	// El agente murió justo después de aplicar: el journal dice «aplicando» y la
	// cuenta ya tiene la nueva.
	_ = s.e.Journal.Guardar(&journal.Estado{EnCurso: &journal.Entrada{Trabajo: tr, Fase: journal.FaseAplicando}})
	s.rot.cuentas["deploy"] = "Nueva-2026!x"

	if _, err := s.e.Ciclo(context.Background()); err != nil {
		t.Fatal(err)
	}
	if s.api.resultados[0] != (resultado{8, Aplicado, VerificacionLocal, ""}) {
		t.Fatalf("resultado = %+v", s.api.resultados)
	}
	s.journalVacio(t)
}

func TestTrasUnaCaidaAntesDeAplicarInformaQueNoSeAplico(t *testing.T) {
	s := nuevo(t)
	tr := contrato.Trabajo{ID: 9, Tipo: contrato.TipoRotarCuenta, Usuario: "deploy",
		Nueva: "Nueva-2026!x", Actual: "Actual-2026!x", ExpiraEn: "2026-11-26T10:15:00"}
	_ = s.e.Journal.Guardar(&journal.Estado{EnCurso: &journal.Entrada{Trabajo: tr, Fase: journal.FaseAplicando}})

	_, _ = s.e.Ciclo(context.Background())
	if s.api.resultados[0].estado != Fallado || s.rot.cuentas["deploy"] != "Actual-2026!x" {
		t.Fatalf("resultado = %+v, cuenta = %v", s.api.resultados, s.rot.cuentas)
	}
	s.journalVacio(t)
}

func TestSinRedElResultadoEsperaEnElJournalYNoSeAceptaOtroTrabajo(t *testing.T) {
	s := nuevo(t)
	s.api.fallosRed = 2 // falla la entrega del ciclo 1 y el reintento del ciclo 2
	s.api.pendiente = s.trabajo(t, 10, nil)
	_, _ = s.e.Ciclo(context.Background())
	estado, _ := s.e.Journal.Leer()
	if estado.EnCurso == nil || estado.EnCurso.Resultado != Aplicado {
		t.Fatalf("el resultado no quedó guardado para reintentar: %+v", estado.EnCurso)
	}

	// Ciclo 2: la entrega vuelve a fallar. Con un resultado sin entregar, el
	// trabajo 11 ni siquiera se pide.
	s.api.pendiente = s.trabajo(t, 11, nil)
	_, _ = s.e.Ciclo(context.Background())
	if s.api.pendiente == nil || len(s.api.resultados) != 0 {
		t.Fatalf("pidió trabajo nuevo con un resultado pendiente: %+v", s.api.resultados)
	}

	// Ciclo 3: la red vuelve; se entrega el 10 y solo entonces se atiende el 11.
	_, _ = s.e.Ciclo(context.Background())
	if len(s.api.resultados) < 1 || s.api.resultados[0] != (resultado{10, Aplicado, VerificacionLocal, ""}) {
		t.Fatalf("resultados = %+v", s.api.resultados)
	}
	if s.rot.aplicados != 1 {
		t.Fatalf("aplicados = %d", s.rot.aplicados)
	}
}

func TestLaIdentidadRenovadaSePersisteYSeUsa(t *testing.T) {
	s := nuevo(t)
	nuevoToken := "renovado"
	s.api.tokenNuevo = &nuevoToken
	var guardado string
	s.e.AlRenovar = func(token, _ string) error { guardado = token; return nil }
	_, _ = s.e.Ciclo(context.Background())
	if guardado != "renovado" || s.api.token != "renovado" {
		t.Fatalf("guardado %q, en uso %q", guardado, s.api.token)
	}
}

func TestSinRotadorSoloLateYNoPideTrabajos(t *testing.T) {
	s := nuevo(t)
	s.e.Rotador = nil
	s.api.pendiente = s.trabajo(t, 12, nil)
	_, _ = s.e.Ciclo(context.Background())
	if s.api.pendiente == nil {
		t.Fatal("pidió un trabajo sin tener con qué ejecutarlo")
	}
}

func TestElJournalSeEscribeAntesDeTocarLaCuenta(t *testing.T) {
	// Es lo que hace posible la recuperación: si el agente muere dentro de
	// Aplicar, al rearrancar el journal ya sabe qué estaba haciendo.
	s := nuevo(t)
	var visto *journal.Entrada
	s.rot.alAplicar = func() {
		estado, err := s.e.Journal.Leer()
		if err == nil {
			visto = estado.EnCurso
		}
	}
	s.api.pendiente = s.trabajo(t, 13, nil)
	_, _ = s.e.Ciclo(context.Background())
	if visto == nil || visto.Fase != journal.FaseAplicando || visto.Trabajo.ID != 13 {
		t.Fatalf("al aplicar, el journal no registraba el trabajo: %+v", visto)
	}
}
