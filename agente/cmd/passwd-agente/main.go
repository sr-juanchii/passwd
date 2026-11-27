// Command passwd-agente es el agente de rotación de passwd para Linux.
//
//	passwd-agente enrolar --token <token de instalación> [--config ruta]
//	passwd-agente ejecutar [--config ruta]
//	passwd-agente version
//
// Ver docs/plan-rotacion-agentes.md §4 para lo que el agente puede y no puede
// hacer. Las contraseñas no las cambia él: se lo pide al helper root por su
// socket local. Sin helper configurado, solo late y envía telemetría.
package main

import (
	"bufio"
	"context"
	"errors"
	"flag"
	"fmt"
	"io"
	"io/fs"
	"log/slog"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"github.com/sr-juanchii/passwd/agente/internal/cliente"
	"github.com/sr-juanchii/passwd/agente/internal/config"
	"github.com/sr-juanchii/passwd/agente/internal/ejecutor"
	"github.com/sr-juanchii/passwd/agente/internal/identidad"
	"github.com/sr-juanchii/passwd/agente/internal/journal"
	"github.com/sr-juanchii/passwd/agente/internal/rotador"
	"github.com/sr-juanchii/passwd/agente/internal/telemetria"
)

// version se fija al compilar con -ldflags "-X main.version=X.Y.Z".
var version = "dev"

func main() {
	if len(os.Args) < 2 {
		uso()
		os.Exit(2)
	}
	var err error
	switch os.Args[1] {
	case "enrolar":
		err = enrolar(os.Args[2:])
	case "ejecutar":
		err = ejecutar(os.Args[2:])
	case "version", "--version":
		fmt.Println(version)
	default:
		uso()
		os.Exit(2)
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "passwd-agente:", err)
		os.Exit(1)
	}
}

func uso() {
	fmt.Fprintln(os.Stderr, `uso:
  passwd-agente enrolar --token - [--config ruta] [--forzar]   (el token, por la entrada estándar)
  passwd-agente ejecutar [--config ruta]
  passwd-agente version`)
}

func enrolar(args []string) error {
	banderas := flag.NewFlagSet("enrolar", flag.ContinueOnError)
	rutaConfig := banderas.String("config", config.RutaPorDefecto, "archivo de configuración")
	token := banderas.String("token", "", "token de instalación emitido en el panel (un solo uso); "+
		"«-» lo lee de la entrada estándar, para que no quede a la vista de ps")
	forzar := banderas.Bool("forzar", false, "sustituir una identidad existente")
	if err := banderas.Parse(args); err != nil {
		return err
	}
	if *token == "-" {
		leido, err := leerToken(os.Stdin)
		if err != nil {
			return err
		}
		*token = leido
	}
	if *token == "" {
		return errors.New("falta --token: emítalo desde el panel, en la ficha del activo")
	}
	cfg, err := config.Cargar(*rutaConfig)
	if err != nil {
		return err
	}
	if _, err := os.Stat(cfg.Identidad); err == nil && !*forzar {
		return fmt.Errorf("ya hay una identidad en %s: use --forzar para sustituirla", cfg.Identidad)
	} else if err != nil && !errors.Is(err, fs.ErrNotExist) {
		return err
	}
	privada, err := identidad.NuevaClave()
	if err != nil {
		return err
	}
	c, err := cliente.Nuevo(cfg, "", version)
	if err != nil {
		return err
	}
	host, _ := os.Hostname()
	ctx, cancelar := context.WithTimeout(context.Background(), time.Minute)
	defer cancelar()
	r, err := c.Enrolar(ctx, *token, identidad.ClavePublicaB64(privada), host, version)
	if err != nil {
		return fmt.Errorf("el backend rechazó el enrolamiento: %w", err)
	}
	id := &identidad.Identidad{AgenteID: r.AgenteID, Nombre: r.Nombre, Token: r.Token, TokenExpiraEn: r.TokenExpiraEn}
	id.ConClave(privada)
	if err := identidad.Guardar(cfg.Identidad, id); err != nil {
		return fmt.Errorf("enrolado, pero no se pudo guardar la identidad: %w", err)
	}
	// Un journal de una identidad anterior ya no es legible: se retira.
	_ = os.Remove(cfg.Journal)
	fmt.Printf("Agente «%s» enrolado. Identidad guardada en %s.\n", r.Nombre, cfg.Identidad)
	if r.Activo.Nombre != "" {
		// Compruébelo: si no es este servidor, el token salió de otra ficha.
		fmt.Printf("Vinculado en el inventario a: %s «%s».\n", r.Activo.Tipo, r.Activo.Nombre)
	}
	return nil
}

// leerToken lee el token de instalación de la primera línea de r. Acotado: un
// token cabe de sobra en 512 bytes, y nada justifica leer más de la entrada.
func leerToken(r io.Reader) (string, error) {
	linea, err := bufio.NewReader(io.LimitReader(r, 512)).ReadString('\n')
	if err != nil && !errors.Is(err, io.EOF) {
		return "", fmt.Errorf("no se pudo leer el token de la entrada estándar: %w", err)
	}
	return strings.TrimSpace(linea), nil
}

func ejecutar(args []string) error {
	banderas := flag.NewFlagSet("ejecutar", flag.ContinueOnError)
	rutaConfig := banderas.String("config", config.RutaPorDefecto, "archivo de configuración")
	if err := banderas.Parse(args); err != nil {
		return err
	}
	registro := slog.New(slog.NewTextHandler(os.Stderr, nil))
	cfg, err := config.Cargar(*rutaConfig)
	if err != nil {
		return err
	}
	id, err := identidad.Leer(cfg.Identidad)
	if err != nil {
		return fmt.Errorf("identidad: %w (¿falta enrolar el agente?)", err)
	}
	privada, err := id.Privada()
	if err != nil {
		return err
	}
	j, err := journal.Abrir(cfg.Journal, privada)
	if err != nil {
		return err
	}
	c, err := cliente.Nuevo(cfg, id.Token, version)
	if err != nil {
		return err
	}
	e := &ejecutor.Ejecutor{
		API: c, Journal: j, Privada: privada, Version: version,
		AntiThrash: cfg.AntiThrash(), Log: registro, Telemetria: telemetria.Recoger,
		AlRenovar: func(token, expira string) error {
			id.Token, id.TokenExpiraEn = token, expira
			return identidad.Guardar(cfg.Identidad, id)
		},
	}
	if cfg.Helper != "" {
		e.Rotador = &rotador.Socket{Ruta: cfg.Helper}
	}
	registro.Info("agente en marcha", "agente", id.Nombre, "version", version, "rotacion", e.Rotador != nil)
	ctx, parar := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer parar()
	if err := e.Ejecutar(ctx); err != nil && !errors.Is(err, context.Canceled) {
		return err
	}
	registro.Info("agente detenido")
	return nil
}
