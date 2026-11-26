// Package archivo escribe archivos de estado de forma atómica y con permisos
// cerrados. La identidad y el journal del agente nunca deben quedar a medio
// escribir: un corte de luz entre dos escrituras no puede dejar un token
// truncado ni un trabajo ilegible.
package archivo

import (
	"fmt"
	"os"
	"path/filepath"
)

// EscribirAtomico escribe datos en ruta con permisos perm: archivo temporal en
// el mismo directorio, fsync, renombrado y fsync del directorio.
func EscribirAtomico(ruta string, datos []byte, perm os.FileMode) error {
	dir := filepath.Dir(ruta)
	tmp, err := os.CreateTemp(dir, "."+filepath.Base(ruta)+".*")
	if err != nil {
		return err
	}
	nombre := tmp.Name()
	limpiar := func() { _ = os.Remove(nombre) }
	if err := tmp.Chmod(perm); err != nil {
		tmp.Close()
		limpiar()
		return err
	}
	if _, err := tmp.Write(datos); err != nil {
		tmp.Close()
		limpiar()
		return err
	}
	if err := tmp.Sync(); err != nil {
		tmp.Close()
		limpiar()
		return err
	}
	if err := tmp.Close(); err != nil {
		limpiar()
		return err
	}
	if err := os.Rename(nombre, ruta); err != nil {
		limpiar()
		return err
	}
	d, err := os.Open(dir)
	if err != nil {
		return fmt.Errorf("renombrado, pero no se pudo sincronizar el directorio: %w", err)
	}
	defer d.Close()
	return d.Sync()
}

// ExigirPrivado falla si el archivo es legible o escribible por alguien más que
// su dueño. Un secreto con permisos abiertos ya no es un secreto: mejor parar
// que seguir usándolo como si nada.
func ExigirPrivado(ruta string) error {
	info, err := os.Stat(ruta)
	if err != nil {
		return err
	}
	if info.Mode().Perm()&0o077 != 0 {
		return fmt.Errorf("%s tiene permisos %#o: deben ser 0600", ruta, info.Mode().Perm())
	}
	return nil
}
