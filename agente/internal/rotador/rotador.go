// Package rotador es el Rotador real del agente: pide al helper root, por su
// socket local, que verifique o cambie una contraseña.
//
// El agente no tiene privilegios ni los gana nunca (NoNewPrivileges y sin
// capacidades en su unidad): no hay sudo ni binarios setuid. La única forma de
// que una contraseña cambie es que el helper, que corre aparte como root y sin
// red, acepte la petición.
package rotador

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"time"

	"github.com/sr-juanchii/passwd/agente/internal/helper"
)

// TiempoMaximo por petición: PAM y chpasswd tardan milisegundos; más que esto es
// un helper colgado, y el ejecutor debe enterarse.
const TiempoMaximo = 30 * time.Second

// Socket es el rotador que habla con el helper.
type Socket struct {
	Ruta string
}

func (s *Socket) pedir(ctx context.Context, p helper.Peticion) (*helper.Respuesta, error) {
	ctx, cancelar := context.WithTimeout(ctx, TiempoMaximo)
	defer cancelar()
	var marcador net.Dialer
	conexion, err := marcador.DialContext(ctx, "unix", s.Ruta)
	if err != nil {
		return nil, errors.New("no se pudo contactar con el helper: ¿está activo passwd-agente-helper.socket?")
	}
	defer conexion.Close()
	if limite, ok := ctx.Deadline(); ok {
		_ = conexion.SetDeadline(limite)
	}
	if err := json.NewEncoder(conexion).Encode(p); err != nil {
		return nil, errors.New("no se pudo enviar la petición al helper")
	}
	linea, err := bufio.NewReader(io.LimitReader(conexion, helper.MaxPeticion)).ReadBytes('\n')
	if err != nil && !errors.Is(err, io.EOF) {
		return nil, errors.New("el helper no respondió")
	}
	var r helper.Respuesta
	if err := json.Unmarshal(linea, &r); err != nil {
		return nil, errors.New("respuesta del helper ilegible")
	}
	return &r, nil
}

// Aplicar cambia actual → nueva. El helper comprueba antes que actual vale.
func (s *Socket) Aplicar(ctx context.Context, usuario, actual, nueva string) error {
	r, err := s.pedir(ctx, helper.Peticion{Accion: helper.AccionAplicar, Cuenta: usuario, Actual: actual, Nueva: nueva})
	if err != nil {
		return err
	}
	if !r.OK && r.SinCambios {
		return fmt.Errorf("%s: %w", r.Error, helper.ErrSinCambios)
	}
	if !r.OK {
		return errors.New(r.Error)
	}
	return nil
}

// Verificar dice si la contraseña autentica la cuenta. Un «no» no es un error;
// un helper que no puede contestar, sí.
func (s *Socket) Verificar(ctx context.Context, usuario, password string) (bool, error) {
	r, err := s.pedir(ctx, helper.Peticion{Accion: helper.AccionVerificar, Cuenta: usuario, Password: password})
	if err != nil {
		return false, err
	}
	if r.Error != "" {
		return false, errors.New(r.Error)
	}
	return r.OK, nil
}

// Revertir vuelve a fijar la contraseña anterior.
func (s *Socket) Revertir(ctx context.Context, usuario, _, actual string) error {
	r, err := s.pedir(ctx, helper.Peticion{Accion: helper.AccionRestaurar, Cuenta: usuario, Valor: actual})
	if err != nil {
		return err
	}
	if !r.OK {
		return errors.New(r.Error)
	}
	return nil
}
