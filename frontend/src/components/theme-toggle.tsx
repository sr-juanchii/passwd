"use client";

import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";

export function ThemeToggle() {
  const { theme, setTheme, resolvedTheme } = useTheme();
  const [montado, setMontado] = useState(false);
  useEffect(() => setMontado(true), []);

  const actual = theme === "system" ? resolvedTheme : theme;
  const alternar = () => setTheme(actual === "dark" ? "light" : "dark");

  return (
    <Button
      variant="ghost"
      size="icon-lg"
      onClick={alternar}
      aria-label="Cambiar tema claro/oscuro"
      title="Cambiar tema"
    >
      {montado && actual === "dark" ? <Sun className="size-4" /> : <Moon className="size-4" />}
    </Button>
  );
}
