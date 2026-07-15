import { PageSkeleton } from "@/components/ui/page-skeleton";

// Fallback instantáneo al navegar a cualquier página del shell mientras carga
// su código; cada página muestra después su propio skeleton de datos.
export default function Loading() {
  return <PageSkeleton variante="tabla" />;
}
