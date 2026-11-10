import Image from "next/image";

// QR de alta de la aplicación autenticadora + clave para entrada manual.
export function QrTotp({ qr, secreto }: { qr: string; secreto: string }) {
  return (
    <>
      {qr && (
        <div className="my-1 flex justify-center">
          {/* El QR va SIEMPRE sobre blanco, también en oscuro (DESIGN.md §7). */}
          <div className="rounded-xl bg-white p-3 ring-1 ring-foreground/10">
            <Image src={qr} alt="Código QR de alta de la aplicación autenticadora" width={200} height={200} unoptimized />
          </div>
        </div>
      )}
      {secreto && (
        <div className="rounded-lg border bg-muted/40 px-3.5 py-3">
          <div className="text-[11px] font-medium tracking-[0.06em] text-muted-foreground uppercase">
            Entrada manual
          </div>
          <div className="mt-1 font-mono text-[13px] break-all">{secreto}</div>
        </div>
      )}
    </>
  );
}
