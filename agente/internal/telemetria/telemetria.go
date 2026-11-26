// Package telemetria recoge métricas AGREGADAS del propio host (§4.4).
//
// Solo uso de CPU, memoria y disco, tiempo encendido y datos de hardware y
// sistema. Nada de procesos, usuarios, sesiones ni rutas más allá del punto de
// montaje de cada disco (§4.1, prohibición 9). Y nunca dispara nada: la
// telemetría informa, no decide (prohibición 5).
//
// El tamaño se acota AQUÍ, antes de enviar: el backend rechaza lo que supera
// su tope en vez de ampliarlo, así que un agente que no recortara se quedaría
// sin informar. Si hubo que recortar, se dice en Recortada.
package telemetria

import (
	"context"
	"encoding/json"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/shirou/gopsutil/v4/cpu"
	"github.com/shirou/gopsutil/v4/disk"
	"github.com/shirou/gopsutil/v4/host"
	"github.com/shirou/gopsutil/v4/mem"
)

// Topes del contenido, por debajo de los del backend (32 discos, 16 KB).
const (
	MaxDiscos  = 32
	LargoTexto = 120
	MaxBytes   = 12 * 1024
)

// Disco es un sistema de archivos montado.
type Disco struct {
	Montaje         string `json:"montaje"`
	SistemaArchivos string `json:"sistema_archivos"`
	TotalBytes      *int64 `json:"total_bytes"`
	UsadoPct        *int   `json:"usado_pct"`
}

// Datos es el cuerpo de POST /api/agent/telemetria.
type Datos struct {
	CPUPct           *int    `json:"cpu_pct"`
	RAMPct           *int    `json:"ram_pct"`
	DiscoPct         *int    `json:"disco_pct"`
	UptimeS          *int64  `json:"uptime_s"`
	SistemaOperativo string  `json:"sistema_operativo"`
	Kernel           string  `json:"kernel"`
	CPUModelo        string  `json:"cpu_modelo"`
	RAMTotal         *int64  `json:"ram_total"`
	Discos           []Disco `json:"discos"`
	Recortada        bool    `json:"recortada"`
}

func entero(v float64) *int {
	n := int(v + 0.5)
	return &n
}

func int64p(v uint64) *int64 {
	n := int64(v)
	return &n
}

// Recoger toma una instantánea. Lo que no se puede leer queda vacío: una
// métrica que falta no debe impedir el latido.
func Recoger(ctx context.Context) Datos {
	var d Datos
	if p, err := cpu.PercentWithContext(ctx, time.Second, false); err == nil && len(p) == 1 {
		d.CPUPct = entero(p[0])
	}
	if m, err := mem.VirtualMemoryWithContext(ctx); err == nil {
		d.RAMPct = entero(m.UsedPercent)
		d.RAMTotal = int64p(m.Total)
	}
	if u, err := disk.UsageWithContext(ctx, "/"); err == nil {
		d.DiscoPct = entero(u.UsedPercent)
	}
	if h, err := host.InfoWithContext(ctx); err == nil {
		d.UptimeS = int64p(h.Uptime)
		d.SistemaOperativo = strings.TrimSpace(h.Platform + " " + h.PlatformVersion)
		d.Kernel = h.KernelVersion
	}
	if infos, err := cpu.InfoWithContext(ctx); err == nil && len(infos) > 0 {
		d.CPUModelo = infos[0].ModelName
	}
	if particiones, err := disk.PartitionsWithContext(ctx, false); err == nil {
		for _, p := range particiones {
			disco := Disco{Montaje: p.Mountpoint, SistemaArchivos: p.Fstype}
			if u, err := disk.UsageWithContext(ctx, p.Mountpoint); err == nil {
				disco.TotalBytes = int64p(u.Total)
				disco.UsadoPct = entero(u.UsedPercent)
			}
			d.Discos = append(d.Discos, disco)
		}
	}
	return Acotar(d)
}

func recortar(s string) string {
	s = strings.ToValidUTF8(s, "")
	if utf8.RuneCountInString(s) <= LargoTexto {
		return s
	}
	return string([]rune(s)[:LargoTexto])
}

// Acotar aplica los topes y marca Recortada si tuvo que quitar algo.
func Acotar(d Datos) Datos {
	textos := []*string{&d.SistemaOperativo, &d.Kernel, &d.CPUModelo}
	for _, t := range textos {
		if r := recortar(*t); r != *t {
			*t, d.Recortada = r, true
		}
	}
	if len(d.Discos) > MaxDiscos {
		d.Discos, d.Recortada = d.Discos[:MaxDiscos], true
	}
	for i := range d.Discos {
		d.Discos[i].Montaje = recortar(d.Discos[i].Montaje)
		d.Discos[i].SistemaArchivos = recortar(d.Discos[i].SistemaArchivos)
	}
	// Último recurso: si aun así no cabe, se envía lo esencial sin discos.
	for tam(d) > MaxBytes && len(d.Discos) > 0 {
		d.Discos, d.Recortada = d.Discos[:len(d.Discos)/2], true
	}
	return d
}

func tam(d Datos) int {
	datos, _ := json.Marshal(d)
	return len(datos)
}
