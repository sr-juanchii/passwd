//go:build integracion

// Prueba de integración REAL: cuentas Linux de verdad, PAM de verdad, chpasswd
// de verdad y el helper compilado, servido por conexión como lo hará systemd
// (Accept=yes). Necesita root, por eso va tras la etiqueta «integracion»:
//
//	go build -o /tmp/helper ./cmd/passwd-agente-helper
//	sudo PASSWD_INTEGRACION=1 PASSWD_HELPER_BIN=/tmp/helper go test -tags integracion -run Integracion ./internal/ejecutor/
//
// Con PASSWD_INTEGRACION=1 la falta de un requisito es un FALLO, no un salto:
// en la CI no puede pasar en verde sin haberse ejecutado.
package ejecutor

import (
	"context"
	"crypto/rand"
	"encoding/json"
	"fmt"
	"net"
	"os"
	"os/exec"
	"os/user"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/sr-juanchii/passwd/agente/internal/cliente"
	"github.com/sr-juanchii/passwd/agente/internal/contrato"
	"github.com/sr-juanchii/passwd/agente/internal/identidad"
	"github.com/sr-juanchii/passwd/agente/internal/journal"
	"github.com/sr-juanchii/passwd/agente/internal/rotador"
)

const (
	rutaPAM        = "/etc/pam.d/passwd-agente-helper"
	contenidoPAM   = "auth     required  pam_unix.so nodelay\naccount  required  pam_unix.so\n"
	passwordInicio = "Inicial-Integracion-2026!"
)

func requisitos(t *testing.T) string {
	t.Helper()
	parar := t.Skip
	if os.Getenv("PASSWD_INTEGRACION") == "1" {
		parar = t.Fatal
	}
	if os.Geteuid() != 0 {
		parar("la prueba de integración necesita root")
	}
	bin := os.Getenv("PASSWD_HELPER_BIN")
	if bin == "" {
		parar("falta PASSWD_HELPER_BIN con la ruta del helper compilado")
	}
	return bin
}

func ejecutar(t *testing.T, nombre string, entrada string, args ...string) {
	t.Helper()
	orden := exec.Command(nombre, args...)
	orden.Stdin = strings.NewReader(entrada)
	if salida, err := orden.CombinedOutput(); err != nil {
		t.Fatalf("%s %v: %v\n%s", nombre, args, err, salida)
	}
}

// cuentaReal crea una cuenta local con la contraseña inicial y la borra al acabar.
func cuentaReal(t *testing.T) string {
	t.Helper()
	sufijo := make([]byte, 4)
	_, _ = rand.Read(sufijo)
	nombre := fmt.Sprintf("pai%x", sufijo)
	ejecutar(t, "useradd", "", "-M", "-N", "-s", "/usr/sbin/nologin", nombre)
	t.Cleanup(func() { _ = exec.Command("userdel", nombre).Run() })
	ejecutar(t, "chpasswd", nombre+":"+passwordInicio+"\n")
	return nombre
}

func servicioPAM(t *testing.T) {
	t.Helper()
	if _, err := os.Stat(rutaPAM); err == nil {
		return
	}
	if err := os.WriteFile(rutaPAM, []byte(contenidoPAM), 0o644); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.Remove(rutaPAM) })
}

// servirHelper escucha en un socket y, por cada conexión, ejecuta el helper con
// la conexión como entrada y salida estándar: lo mismo que systemd con Accept=yes.
func servirHelper(t *testing.T, bin, usuarioAgente string, cuentas []string) string {
	t.Helper()
	servicioPAM(t)
	dir := t.TempDir()
	cfg := filepath.Join(dir, "helper.json")
	datos, _ := json.Marshal(map[string]any{"usuario_agente": usuarioAgente, "cuentas": cuentas})
	if err := os.WriteFile(cfg, datos, 0o644); err != nil {
		t.Fatal(err)
	}
	sock := filepath.Join(dir, "helper.sock")
	escucha, err := net.Listen("unix", sock)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = escucha.Close() })
	go func() {
		for {
			conexion, err := escucha.Accept()
			if err != nil {
				return
			}
			go func() {
				defer conexion.Close()
				archivo, err := conexion.(*net.UnixConn).File()
				if err != nil {
					return
				}
				defer archivo.Close()
				orden := exec.Command(bin, "--config", cfg)
				orden.Stdin, orden.Stdout = archivo, archivo
				_ = orden.Run()
			}()
		}
	}()
	return sock
}

func vale(t *testing.T, r *rotador.Socket, cuenta, password string) bool {
	t.Helper()
	ok, err := r.Verificar(context.Background(), cuenta, password)
	if err != nil {
		t.Fatalf("verificar %s: %v", cuenta, err)
	}
	return ok
}

func ejecutorReal(t *testing.T, rot Rotador) (*Ejecutor, *apiFalsa) {
	t.Helper()
	privada, _ := identidad.NuevaClave()
	j, err := journal.Abrir(filepath.Join(t.TempDir(), "journal.bin"), privada)
	if err != nil {
		t.Fatal(err)
	}
	api := &apiFalsa{}
	return &Ejecutor{API: api, Journal: j, Rotador: rot, Privada: privada, Version: "1.4.0",
		AntiThrash: time.Hour, Ahora: time.Now}, api
}

func trabajoPara(t *testing.T, e *Ejecutor, id int64, cuenta, nueva string) contrato.Trabajo {
	t.Helper()
	return contrato.Trabajo{ID: id, Tipo: contrato.TipoRotarCuenta, Usuario: cuenta, Nueva: nueva,
		Actual: passwordInicio, ExpiraEn: time.Now().UTC().Add(10 * time.Minute).Format(contrato.FormatoFecha)}
}

func TestIntegracionCicloCompletoSobreUnaCuentaReal(t *testing.T) {
	bin := requisitos(t)
	cuenta := cuentaReal(t)
	rot := &rotador.Socket{Ruta: servirHelper(t, bin, "root", []string{cuenta})}
	e, api := ejecutorReal(t, rot)
	tr := trabajoPara(t, e, 1, cuenta, "Nueva-Integracion-2026!x")
	api.pendiente = sellado(t, e, tr)

	if _, err := e.Ciclo(context.Background()); err != nil {
		t.Fatal(err)
	}
	if len(api.resultados) != 1 || api.resultados[0].estado != Aplicado {
		t.Fatalf("resultados = %+v", api.resultados)
	}
	if !vale(t, rot, cuenta, tr.Nueva) || vale(t, rot, cuenta, passwordInicio) {
		t.Fatal("PAM no confirma la contraseña nueva en la cuenta real")
	}
}

// estropeador aplica de verdad y luego deja la cuenta con otra contraseña, de
// modo que la nueva no verifica y el ejecutor tiene que revertir.
type estropeador struct{ *rotador.Socket }

func (r estropeador) Aplicar(ctx context.Context, u, actual, nueva string) error {
	if err := r.Socket.Aplicar(ctx, u, actual, nueva); err != nil {
		return err
	}
	return r.Socket.Revertir(ctx, u, nueva, "Estropeada-Por-La-Prueba-1")
}

func TestIntegracionRevierteSiLaNuevaNoVerifica(t *testing.T) {
	bin := requisitos(t)
	cuenta := cuentaReal(t)
	rot := &rotador.Socket{Ruta: servirHelper(t, bin, "root", []string{cuenta})}
	e, api := ejecutorReal(t, estropeador{rot})
	tr := trabajoPara(t, e, 2, cuenta, "Nueva-Integracion-2026!y")
	api.pendiente = sellado(t, e, tr)

	_, _ = e.Ciclo(context.Background())
	if len(api.resultados) != 1 || api.resultados[0].estado != Revertido {
		t.Fatalf("resultados = %+v", api.resultados)
	}
	if !vale(t, rot, cuenta, passwordInicio) {
		t.Fatal("tras revertir, la contraseña anterior no vuelve a valer en la cuenta real")
	}
}

func TestIntegracionRecuperaTrasUnReinicio(t *testing.T) {
	bin := requisitos(t)
	cuenta := cuentaReal(t)
	rot := &rotador.Socket{Ruta: servirHelper(t, bin, "root", []string{cuenta})}
	e, api := ejecutorReal(t, rot)
	tr := trabajoPara(t, e, 3, cuenta, "Nueva-Integracion-2026!z")
	// El agente murió tras aplicar: la cuenta ya tiene la nueva y el journal dice «aplicando».
	if err := rot.Aplicar(context.Background(), cuenta, passwordInicio, tr.Nueva); err != nil {
		t.Fatal(err)
	}
	_ = e.Journal.Guardar(&journal.Estado{EnCurso: &journal.Entrada{Trabajo: tr, Fase: journal.FaseAplicando}})

	if _, err := e.Ciclo(context.Background()); err != nil {
		t.Fatal(err)
	}
	if len(api.resultados) != 1 || api.resultados[0] != (resultado{3, Aplicado, VerificacionLocal, ""}) {
		t.Fatalf("resultados = %+v", api.resultados)
	}
	estado, _ := e.Journal.Leer()
	if estado.EnCurso != nil {
		t.Fatal("el journal no se purgó tras recuperar")
	}
}

func TestIntegracionRechazosDelHelper(t *testing.T) {
	bin := requisitos(t)
	listada := cuentaReal(t)
	fuera := cuentaReal(t)
	inexistente := "paino0000"
	rot := &rotador.Socket{Ruta: servirHelper(t, bin, "root", []string{listada, inexistente})}
	ctx := context.Background()

	if err := rot.Aplicar(ctx, inexistente, passwordInicio, "Nueva-1x!"); err == nil {
		t.Fatal("aceptó una cuenta que no existe")
	}
	if _, err := user.Lookup(inexistente); err == nil {
		t.Fatal("el helper CREÓ una cuenta")
	}

	sombraAntes := lineaSombra(t, fuera)
	if err := rot.Revertir(ctx, fuera, "", "Nueva-1x!"); err == nil {
		t.Fatal("cambió una cuenta fuera de la lista")
	}
	if lineaSombra(t, fuera) != sombraAntes {
		t.Fatal("la cuenta fuera de la lista cambió en /etc/shadow")
	}

	if err := rot.Aplicar(ctx, listada, "No-Es-La-Actual-1", "Nueva-1x!"); err == nil {
		t.Fatal("cambió la contraseña sin que la actual coincidiera")
	}
	if !vale(t, rot, listada, passwordInicio) {
		t.Fatal("la cuenta cambió pese a que la actual no coincidía")
	}
}

func TestIntegracionSoloAtiendeAlUsuarioDelAgente(t *testing.T) {
	bin := requisitos(t)
	cuenta := cuentaReal(t)
	// El helper espera al usuario «nobody»; quien llama es root: debe negarse.
	rot := &rotador.Socket{Ruta: servirHelper(t, bin, "nobody", []string{cuenta})}
	if _, err := rot.Verificar(context.Background(), cuenta, passwordInicio); err == nil ||
		!strings.Contains(err.Error(), "no autorizada") {
		t.Fatalf("atendió a un usuario que no es el del agente (err = %v)", err)
	}
}

func lineaSombra(t *testing.T, cuenta string) string {
	t.Helper()
	datos, err := os.ReadFile("/etc/shadow")
	if err != nil {
		t.Fatal(err)
	}
	for _, linea := range strings.Split(string(datos), "\n") {
		if strings.HasPrefix(linea, cuenta+":") {
			return linea
		}
	}
	t.Fatalf("%s no está en /etc/shadow", cuenta)
	return ""
}

// sellado prepara el trabajo como lo serviría el backend: sellado al agente.
func sellado(t *testing.T, e *Ejecutor, tr contrato.Trabajo) *cliente.RespTrabajo {
	t.Helper()
	return &cliente.RespTrabajo{TrabajoID: tr.ID, Sobre: sellar(t, e.Privada.PublicKey(), tr)}
}
