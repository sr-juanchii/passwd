// Package ejecutor es el bucle del agente y el protocolo de dos fases.
//
//	latido → telemetría → ¿trabajo? → validar → journal «aplicando»
//	      → Aplicar → Verificar(nueva) ─ok─→ journal «aplicado» → informar → purgar
//	                                   └no─→ Revertir → Verificar(actual)
//	                                         → journal «revertido» → informar → purgar
//
// El journal se escribe ANTES de tocar la cuenta y se purga DESPUÉS de que el
// backend acepte el resultado. Si el agente muere en medio, al rearrancar
// recupera: comprueba qué contraseña vale de verdad y lo informa. Nunca un
// estado indeterminado en silencio (docs/plan-rotacion-agentes.md §2.2).
//
// Las contraseñas no se escriben nunca en el registro.
package ejecutor

import (
	"context"
	"crypto/ecdh"
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"time"

	"github.com/sr-juanchii/passwd/agente/internal/cliente"
	"github.com/sr-juanchii/passwd/agente/internal/contrato"
	"github.com/sr-juanchii/passwd/agente/internal/journal"
	"github.com/sr-juanchii/passwd/agente/internal/sobre"
	"github.com/sr-juanchii/passwd/agente/internal/telemetria"
)

// Resultados que entiende el backend.
const (
	Aplicado  = "aplicado"
	Revertido = "revertido"
	Fallado   = "fallado"

	VerificacionLocal   = "local"
	VerificacionNinguna = "ninguna"
)

// IntervaloPorDefecto se usa hasta que el backend indique otro.
const IntervaloPorDefecto = 15 * time.Minute

// Rotador cambia y comprueba contraseñas de cuentas locales. Su implementación
// real (helper root de acción única + PAM) llega en el commit 4b.
type Rotador interface {
	Aplicar(ctx context.Context, usuario, actual, nueva string) error
	Verificar(ctx context.Context, usuario, password string) (bool, error)
	Revertir(ctx context.Context, usuario, nueva, actual string) error
}

// API es lo que el ejecutor necesita del backend (lo cumple *cliente.Cliente).
type API interface {
	Saludo(ctx context.Context, version string) (*cliente.RespSaludo, error)
	Pendiente(ctx context.Context) (*cliente.RespTrabajo, error)
	Resultado(ctx context.Context, trabajoID int64, estado, verificacion, detalle string) error
	Telemetria(ctx context.Context, datos any) error
	SetToken(token string)
}

// Ejecutor reúne lo necesario para un ciclo.
type Ejecutor struct {
	API        API
	Journal    *journal.Journal
	Rotador    Rotador // nil: sin rotación, solo latido y telemetría
	Privada    *ecdh.PrivateKey
	Version    string
	AntiThrash time.Duration
	Log        *slog.Logger
	// AlRenovar persiste un token renovado. Si falla, el agente sigue con el
	// nuevo en memoria, pero lo perderá al reiniciarse: se registra como error.
	AlRenovar func(token, expira string) error
	// Inyectables para las pruebas.
	Ahora      func() time.Time
	Telemetria func(ctx context.Context) telemetria.Datos
}

func (e *Ejecutor) ahora() time.Time {
	if e.Ahora != nil {
		return e.Ahora()
	}
	return time.Now()
}

func (e *Ejecutor) log() *slog.Logger {
	if e.Log != nil {
		return e.Log
	}
	return slog.Default()
}

// Ejecutar repite el ciclo hasta que ctx se cancela.
func (e *Ejecutor) Ejecutar(ctx context.Context) error {
	espera := time.Duration(0)
	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(espera):
		}
		intervalo, err := e.Ciclo(ctx)
		if err != nil {
			e.log().Error("ciclo del agente", "error", err)
		}
		espera = intervalo
	}
}

// Ciclo hace una vuelta completa y devuelve cuánto esperar hasta la siguiente.
func (e *Ejecutor) Ciclo(ctx context.Context) (time.Duration, error) {
	saludo, err := e.API.Saludo(ctx, e.Version)
	if err != nil {
		if cliente.Codigo(err) == http.StatusUnauthorized {
			return IntervaloPorDefecto, errors.New("el backend no reconoce la identidad del agente: " +
				"si caducó o se revocó, vuelva a enrolarlo desde el panel")
		}
		return time.Minute, err
	}
	intervalo := IntervaloPorDefecto
	if saludo.IntervaloMin > 0 {
		intervalo = time.Duration(saludo.IntervaloMin) * time.Minute
	}
	if saludo.TokenNuevo != nil && *saludo.TokenNuevo != "" {
		expira := ""
		if saludo.TokenExpiraEn != nil {
			expira = *saludo.TokenExpiraEn
		}
		if e.AlRenovar != nil {
			if err := e.AlRenovar(*saludo.TokenNuevo, expira); err != nil {
				e.log().Error("no se pudo guardar la identidad renovada: se perderá al reiniciar", "error", err)
			}
		}
		e.API.SetToken(*saludo.TokenNuevo)
	}

	if e.Telemetria != nil {
		if err := e.API.Telemetria(ctx, e.Telemetria(ctx)); err != nil {
			e.log().Warn("telemetría no enviada", "error", err)
		}
	}

	if e.Rotador == nil {
		return intervalo, nil
	}
	if !saludo.VersionAdmitida {
		e.log().Warn("versión del agente por debajo de la mínima: no recibirá trabajos",
			"version", e.Version, "minima", saludo.VersionMinima)
		return intervalo, nil
	}
	pendiente, err := e.Recuperar(ctx)
	if err != nil || pendiente {
		// Con un resultado aún sin entregar no se acepta trabajo nuevo.
		return time.Minute, err
	}
	trabajo, err := e.API.Pendiente(ctx)
	if err != nil || trabajo == nil {
		return intervalo, err
	}
	return intervalo, e.Procesar(ctx, trabajo)
}

// Procesar ejecuta un trabajo recién recibido.
func (e *Ejecutor) Procesar(ctx context.Context, recibido *cliente.RespTrabajo) error {
	claro, err := sobre.Abrir(e.Privada, recibido.Sobre)
	if err != nil {
		return e.informarRechazo(ctx, recibido.TrabajoID, "sobre ilegible para este agente")
	}
	var t contrato.Trabajo
	if err := json.Unmarshal(claro, &t); err != nil {
		return e.informarRechazo(ctx, recibido.TrabajoID, "contenido del trabajo ilegible")
	}
	if t.ID != recibido.TrabajoID {
		return e.informarRechazo(ctx, recibido.TrabajoID, "el sobre no corresponde a este trabajo")
	}

	estado, err := e.Journal.Leer()
	if err != nil {
		return err
	}
	var enCurso int64
	if estado.EnCurso != nil {
		enCurso = estado.EnCurso.Trabajo.ID
	}
	err = contrato.Validar(t, contrato.Contexto{
		Ahora: e.ahora(), EnCurso: enCurso, AntiThrash: e.AntiThrash,
		Ultima: func(u string) (time.Time, bool) { v, ok := estado.Ultimas[u]; return v, ok },
	})
	if err != nil {
		e.log().Warn("trabajo rechazado por el contrato", "trabajo", t.ID, "motivo", err)
		return e.informarRechazo(ctx, t.ID, err.Error())
	}
	if estado.EnCurso != nil && estado.EnCurso.Trabajo.ID == t.ID {
		// Re-entrega de un trabajo que el journal ya conoce: lo resuelve la recuperación.
		_, err := e.Recuperar(ctx)
		return err
	}

	// Fase 1: dejar constancia ANTES de tocar la cuenta.
	estado.EnCurso = &journal.Entrada{Trabajo: t, Fase: journal.FaseAplicando}
	if err := e.Journal.Guardar(estado); err != nil {
		return e.informarRechazo(ctx, t.ID, "no se pudo escribir el journal: no se toca la cuenta sin él")
	}
	e.log().Info("aplicando rotación", "trabajo", t.ID, "usuario", t.Usuario)
	if err := e.Rotador.Aplicar(ctx, t.Usuario, t.Actual, t.Nueva); err != nil {
		e.log().Warn("el cambio no se aplicó", "trabajo", t.ID, "error", err)
	}
	return e.decidirYCerrar(ctx, t)
}

// decidirYCerrar comprueba qué contraseña vale y cierra el trabajo en consecuencia.
// La usan tanto el camino normal como la recuperación tras una caída.
func (e *Ejecutor) decidirYCerrar(ctx context.Context, t contrato.Trabajo) error {
	resultado, verificacion, detalle := e.decidir(ctx, t)
	estado, err := e.Journal.Leer()
	if err != nil {
		return err
	}
	estado.EnCurso = &journal.Entrada{Trabajo: t, Fase: journal.FaseCerrada,
		Resultado: resultado, Verificacion: verificacion, Detalle: detalle}
	if err := e.Journal.Guardar(estado); err != nil {
		return err
	}
	return e.informar(ctx, estado.EnCurso)
}

func (e *Ejecutor) decidir(ctx context.Context, t contrato.Trabajo) (string, string, string) {
	if ok, err := e.Rotador.Verificar(ctx, t.Usuario, t.Nueva); err == nil && ok {
		return Aplicado, VerificacionLocal, ""
	}
	// La nueva no autentica: se deja la cuenta como estaba.
	if ok, err := e.Rotador.Verificar(ctx, t.Usuario, t.Actual); err == nil && ok {
		return Fallado, VerificacionNinguna, "la contraseña nueva no se aplicó; la cuenta conserva la anterior"
	}
	if err := e.Rotador.Revertir(ctx, t.Usuario, t.Nueva, t.Actual); err != nil {
		e.log().Error("no se pudo revertir", "trabajo", t.ID, "error", err)
	}
	if ok, err := e.Rotador.Verificar(ctx, t.Usuario, t.Actual); err == nil && ok {
		return Revertido, VerificacionNinguna, "la contraseña nueva no verificó y se restauró la anterior"
	}
	e.log().Error("ni la contraseña nueva ni la anterior autentican: requiere intervención manual",
		"trabajo", t.ID, "usuario", t.Usuario)
	return Fallado, VerificacionNinguna,
		"ni la contraseña nueva ni la anterior autentican la cuenta: requiere intervención manual"
}

// Recuperar resuelve lo que el journal dejó a medias. Devuelve true si queda un
// resultado por entregar (el backend no respondió), en cuyo caso no conviene
// aceptar trabajo nuevo.
func (e *Ejecutor) Recuperar(ctx context.Context) (bool, error) {
	estado, err := e.Journal.Leer()
	if err != nil {
		return true, err
	}
	entrada := estado.EnCurso
	if entrada == nil {
		return false, nil
	}
	if entrada.Fase == journal.FaseAplicando {
		e.log().Warn("recuperando un trabajo interrumpido", "trabajo", entrada.Trabajo.ID)
		if err := e.decidirYCerrar(ctx, entrada.Trabajo); err != nil {
			return true, err
		}
	} else if err := e.informar(ctx, entrada); err != nil {
		return true, err
	}
	estado, err = e.Journal.Leer()
	return err != nil || estado.EnCurso != nil, err
}

// informar entrega el resultado y, si el backend lo acepta o ya lo tenía, purga.
func (e *Ejecutor) informar(ctx context.Context, entrada *journal.Entrada) error {
	err := e.API.Resultado(ctx, entrada.Trabajo.ID, entrada.Resultado, entrada.Verificacion, entrada.Detalle)
	switch cliente.Codigo(err) {
	case 0:
		if err != nil {
			return err // red: se reintenta en el siguiente ciclo, el journal lo guarda
		}
	case http.StatusConflict, http.StatusNotFound, http.StatusForbidden:
		// Ya cerrado (p. ej. resuelto a mano), inexistente o ajeno: nada que entregar.
		e.log().Warn("el backend no acepta el resultado; se descarta", "trabajo", entrada.Trabajo.ID, "error", err)
	default:
		return err
	}
	rotada := ""
	if entrada.Resultado == Aplicado {
		rotada = entrada.Trabajo.Usuario
	}
	e.log().Info("trabajo cerrado", "trabajo", entrada.Trabajo.ID, "resultado", entrada.Resultado)
	return e.Journal.Purgar(rotada, e.ahora())
}

// informarRechazo cierra como «fallado» un trabajo que no se llega a ejecutar.
// No toca el journal: no hay nada aplicado que recordar.
func (e *Ejecutor) informarRechazo(ctx context.Context, trabajoID int64, motivo string) error {
	err := e.API.Resultado(ctx, trabajoID, Fallado, VerificacionNinguna, motivo)
	if cliente.Codigo(err) == http.StatusConflict {
		return nil
	}
	return err
}
