"use client"; // Los error boundaries deben ser Client Components

// Error boundary de la raíz: captura fallos del propio root layout, que el
// error.tsx de segmento no cubre. Debe definir sus propias etiquetas <html>/<body>.
export default function GlobalError({
  error,
  unstable_retry,
}: {
  error: Error & { digest?: string };
  unstable_retry: () => void;
}) {
  return (
    <html lang="es">
      <body
        style={{
          display: "flex",
          minHeight: "100vh",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: "1rem",
          fontFamily: "system-ui, sans-serif",
          textAlign: "center",
          padding: "2rem",
        }}
      >
        <h1 style={{ fontSize: "1.25rem", fontWeight: 600 }}>Algo salió mal</h1>
        <p style={{ color: "#666", fontSize: "0.9rem" }}>
          Ocurrió un error inesperado. {error.digest ? `(ref. ${error.digest})` : ""}
        </p>
        <button
          onClick={() => unstable_retry()}
          style={{
            padding: "0.5rem 1rem",
            borderRadius: "0.5rem",
            border: "1px solid #ccc",
            cursor: "pointer",
            background: "transparent",
          }}
        >
          Reintentar
        </button>
      </body>
    </html>
  );
}
