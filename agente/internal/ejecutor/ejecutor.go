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
	"fmt"
	"log/slog"
	"net/http"
	"time"

	"github.com/sr-juanchii/passwd/agente/internal/cliente"
	"github.com/sr-juanchii/passwd/agente/internal/contrato"
	"github.com/sr-juanchii/passwd/agente/internal/helper"
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

// Rotador cambia y comprueba contraseñas de cuentas locales. La implementación
// real es internal/rotador, que se lo pide al helper root por su socket.
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
	// Lo que el journal dejó pendiente se resuelve y se entrega SIEMPRE, también
	// con una versión ya no admitida: el backend acepta el resultado de un
	// trabajo que entregó, y callarlo lo dejaría «sin confirmar».
	pendiente, err := e.Recuperar(ctx)
	if err != nil || pendiente {
		// Con un resultado aún sin entregar no se acepta trabajo nuevo.
		return time.Minute, err
	}
	if !saludo.VersionAdmitida {
		e.log().Warn("versión del agente por debajo de la mínima: no recibirá trabajos",
			"version", e.Version, "minima", saludo.VersionMinima)
		return intervalo, nil
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
		if errors.Is(err, helper.ErrSinCambios) {
			// El helper lo rechazó sin tocar la cuenta (fuera de la lista, la
			// actual del inventario no autentica…): ese es el motivo que hay que
			// contar, no un «no autentica» deducido después.
			e.log().Warn("el helper rechazó el cambio sin tocar la cuenta", "trabajo", t.ID, "error", err)
			return e.cerrar(ctx, t, Fallado, VerificacionNinguna, "no se cambió nada: "+err.Error())
		}
		e.log().Warn("el cambio no se aplicó", "trabajo", t.ID, "error", err)
	}
	return e.decidirYCerrar(ctx, t)
}

// decidirYCerrar comprueba qué contraseña vale y cierra el trabajo en consecuencia.
// La usan tanto el camino normal como la recuperación tras una caída. Si el
// helper no contesta no se concluye nada: el journal sigue «aplicando» y la
// recuperación lo reintenta.
func (e *Ejecutor) decidirYCerrar(ctx context.Context, t contrato.Trabajo) error {
	resultado, verificacion, detalle, err := e.decidir(ctx, t)
	if err != nil {
		e.log().Warn("no se puede saber qué contraseña quedó; se reintentará", "trabajo", t.ID, "error", err)
		return err
	}
	return e.cerrar(ctx, t, resultado, verificacion, detalle)
}

// cerrar anota el resultado en el journal y lo entrega.
func (e *Ejecutor) cerrar(ctx context.Context, t contrato.Trabajo, resultado, verificacion, detalle string) error {
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

// decidir dice qué contraseña quedó. Un «no autentica» del helper es una
// respuesta; un helper que no contesta no lo es, y entonces se devuelve error
// en vez de deducir nada ni restaurar a ciegas.
func (e *Ejecutor) decidir(ctx context.Context, t contrato.Trabajo) (string, string, string, error) {
	vale := func(password string) (bool, error) {
		ok, err := e.Rotador.Verificar(ctx, t.Usuario, password)
		if err != nil {
			return false, fmt.Errorf("el helper no pudo comprobar la cuenta: %w", err)
		}
		return ok, nil
	}
	ok, err := vale(t.Nueva)
	if err != nil {
		return "", "", "", err
	}
	if ok {
		return Aplicado, VerificacionLocal, "", nil
	}
	// La nueva no autentica: se deja la cuenta como estaba.
	if ok, err = vale(t.Actual); err != nil {
		return "", "", "", err
	} else if ok {
		return Fallado, VerificacionNinguna, "la contraseña nueva no se aplicó; la cuenta conserva la anterior", nil
	}
	if err := e.Rotador.Revertir(ctx, t.Usuario, t.Nueva, t.Actual); err != nil {
		e.log().Error("no se pudo revertir", "trabajo", t.ID, "error", err)
	}
	if ok, err = vale(t.Actual); err != nil {
		return "", "", "", err
	} else if ok {
		return Revertido, VerificacionNinguna, "la contraseña nueva no verificó y se restauró la anterior", nil
	}
	e.log().Error("ni la contraseña nueva ni la anterior autentican: requiere intervención manual",
		"trabajo", t.ID, "usuario", t.Usuario)
	return Fallado, VerificacionNinguna,
		"ni la contraseña nueva ni la anterior autentican la cuenta: requiere intervención manual", nil
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
	case http.StatusConflict, http.StatusNotFound, http.StatusForbidden,
		http.StatusBadRequest, http.StatusUnprocessableEntity:
		// Ya cerrado (p. ej. resuelto a mano), inexistente, ajeno, o un resultado
		// que el backend nunca admitirá: reintentarlo bloquearía al agente para
		// siempre. El backend lo verá «sin confirmar» y lo resolverá una persona.
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
