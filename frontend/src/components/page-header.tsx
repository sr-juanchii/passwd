import Link from "next/link";
import { ChevronRight } from "lucide-react";

export interface Miga {
  label: string;
  href?: string;
}

export function PageHeader({
  titulo,
  descripcion,
  migas,
  acciones,
}: {
  titulo: React.ReactNode;
  descripcion?: React.ReactNode;
  migas?: Miga[];
  acciones?: React.ReactNode;
}) {
  return (
    <div className="mb-6 space-y-2">
      {migas && migas.length > 0 && (
        <nav className="flex flex-wrap items-center gap-1 text-sm text-muted-foreground">
          {migas.map((m, i) => (
            <span key={i} className="flex items-center gap-1">
              {i > 0 && <ChevronRight className="h-3.5 w-3.5" />}
              {m.href ? (
                <Link href={m.href} className="hover:text-foreground">
                  {m.label}
                </Link>
              ) : (
                <span className="text-foreground">{m.label}</span>
              )}
            </span>
          ))}
        </nav>
      )}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight">{titulo}</h1>
          {descripcion && <p className="text-sm text-muted-foreground">{descripcion}</p>}
        </div>
        {acciones && <div className="flex flex-wrap items-center gap-2">{acciones}</div>}
      </div>
    </div>
  );
}
