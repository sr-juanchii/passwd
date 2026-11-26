// Command passwd-agente-helper cambia y comprueba contraseñas de cuentas locales.
//
// Es el ÚNICO componente que corre como root. No escucha en la red ni tiene red
// (PrivateNetwork en su unidad): systemd lo arranca por cada conexión al socket
// local /run/passwd-agente/helper.sock (Accept=yes), le pasa la conexión como
// entrada y salida estándar, y el helper atiende una sola petición y termina.
//
// Las reglas están en internal/helper; aquí solo están las operaciones reales:
// PAM para verificar (servicio propio, solo pam_unix) y chpasswd para fijar.
package main

import (
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"os"
	"os/exec"
	"os/user"
	"strconv"
	"strings"
	"syscall"

	"github.com/msteinert/pam/v2"

	"github.com/sr-juanchii/passwd/agente/internal/helper"
)

const (
	rutaChpasswd = "/usr/sbin/chpasswd"
	rutaPAM      = "/etc/pam.d/" + helper.ServicioPAM
)

// version se fija al compilar con -ldflags "-X main.version=X.Y.Z".
var version = "dev"

type sistema struct{}

func (sistema) Existe(cuenta string) bool {
	_, err := user.Lookup(cuenta)
	return err == nil
}

// Verificar autentica la contraseña por PAM con el servicio propio del helper.
// Una contraseña incorrecta es «false», no un error.
func (sistema) Verificar(cuenta, password string) (bool, error) {
	transaccion, err := pam.StartFunc(helper.ServicioPAM, cuenta,
		func(estilo pam.Style, _ string) (string, error) {
			if estilo == pam.PromptEchoOff {
				return password, nil
			}
			return "", nil
		})
	if err != nil {
		return false, errors.New("no se pudo iniciar PAM")
	}
	defer func() { _ = transaccion.End() }()
	if err := transaccion.Authenticate(pam.Silent); err != nil {
		if errors.Is(err, pam.ErrAuth) || errors.Is(err, pam.ErrUserUnknown) {
			return false, nil
		}
		return false, errors.New("PAM no pudo completar la verificación")
	}
	return true, nil
}

// Fijar cambia la contraseña con chpasswd: ruta absoluta, entorno limpio y la
// contraseña por la entrada estándar, nunca en la línea de órdenes.
func (sistema) Fijar(cuenta, password string) error {
	orden := exec.Command(rutaChpasswd)
	orden.Env = []string{"PATH=/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL=C"}
	orden.Stdin = strings.NewReader(cuenta + ":" + password + "\n")
	salida, err := orden.CombinedOutput()
	if err != nil {
		motivo := strings.TrimSpace(string(salida))
		if len(motivo) > 200 {
			motivo = motivo[:200]
		}
		return fmt.Errorf("chpasswd falló: %s", motivo)
	}
	return nil
}

// llamante averigua quién está al otro lado de la entrada estándar.
func llamante() helper.Llamante {
	var st syscall.Stat_t
	if err := syscall.Fstat(0, &st); err == nil && st.Mode&syscall.S_IFMT == syscall.S_IFSOCK {
		if cred, err := syscall.GetsockoptUcred(0, syscall.SOL_SOCKET, syscall.SO_PEERCRED); err == nil {
			return helper.Llamante{EsSocket: true, UID: int(cred.Uid)}
		}
		// Un socket sin credenciales legibles no identifica a nadie.
		return helper.Llamante{EsSocket: true, UID: -1}
	}
	return helper.Llamante{UID: os.Getuid()}
}

func responder(r helper.Respuesta) {
	_ = json.NewEncoder(os.Stdout).Encode(r)
}

func main() {
	rutaConfig := flag.String("config", helper.RutaConfigPorDefecto, "configuración del helper (de root)")
	verVersion := flag.Bool("version", false, "muestra la versión")
	flag.Parse()
	if *verVersion {
		fmt.Println(version)
		return
	}
	if os.Geteuid() != 0 {
		responder(helper.Respuesta{Error: "el helper debe ejecutarse como root"})
		os.Exit(1)
	}
	if _, err := os.Stat(rutaPAM); err != nil {
		// Sin su servicio PAM, PAM caería en «other», que puede pedir otros
		// factores o contar fallos para bloquear la cuenta.
		responder(helper.Respuesta{Error: "falta " + rutaPAM})
		os.Exit(1)
	}
	cfg, err := helper.CargarConfig(*rutaConfig)
	if err != nil {
		responder(helper.Respuesta{Error: "configuración del helper: " + err.Error()})
		os.Exit(1)
	}
	agente, err := user.Lookup(cfg.UsuarioAgente)
	if err != nil {
		responder(helper.Respuesta{Error: "no existe el usuario del agente " + cfg.UsuarioAgente})
		os.Exit(1)
	}
	uid, err := strconv.Atoi(agente.Uid)
	if err != nil {
		responder(helper.Respuesta{Error: "UID del agente ilegible"})
		os.Exit(1)
	}
	h := &helper.Helper{Config: cfg, Sistema: sistema{}, UIDAgente: uid}
	respuesta := h.Atender(os.Stdin, llamante())
	responder(respuesta)
	if !respuesta.OK && respuesta.Error != "" {
		os.Exit(1)
	}
}
