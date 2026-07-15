// Transición de página del flujo de autenticación (DESIGN.md §5): el template
// remonta en cada navegación y re-dispara la entrada (fade + rise, 240ms). Sin
// flags experimentales; respeta prefers-reduced-motion (el keyframe vive tras
// la media query en globals.css).
export default function Template({ children }: { children: React.ReactNode }) {
  return <div className="anim-page-in">{children}</div>;
}
