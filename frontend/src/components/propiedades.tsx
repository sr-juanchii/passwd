import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export interface Propiedad {
  etiqueta: string;
  valor: React.ReactNode;
}

export function Propiedades({ titulo, items }: { titulo?: string; items: Propiedad[] }) {
  const visibles = items.filter((p) => p.valor !== "" && p.valor !== null && p.valor !== undefined);
  if (visibles.length === 0) return null;
  return (
    <Card>
      {titulo && (
        <CardHeader>
          <CardTitle className="text-base">{titulo}</CardTitle>
        </CardHeader>
      )}
      <CardContent>
        <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-2">
          {visibles.map((p) => (
            <div key={p.etiqueta} className="flex flex-col">
              <dt className="text-xs uppercase tracking-wide text-muted-foreground">{p.etiqueta}</dt>
              <dd className="text-sm">{p.valor}</dd>
            </div>
          ))}
        </dl>
      </CardContent>
    </Card>
  );
}
