import type { Metadata } from "next";
import { Fraunces, IBM_Plex_Sans, Source_Serif_4 } from "next/font/google";
import Link from "next/link";
import "./globals.css";

const fraunces = Fraunces({
  variable: "--font-fraunces",
  subsets: ["latin"],
  axes: ["opsz"],
});

const plexSans = IBM_Plex_Sans({
  variable: "--font-plex",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
});

const sourceSerif = Source_Serif_4({
  variable: "--font-source-serif",
  subsets: ["latin"],
  style: ["normal", "italic"],
});

export const metadata: Metadata = {
  title: "CLUMI — Analizador de papers",
  description:
    "Analizador personal de papers con agentes, editor y chatbot. El humano siempre decide.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="es"
      className={`${fraunces.variable} ${plexSans.variable} ${sourceSerif.variable} h-full antialiased`}
    >
      <body className="relative z-10 flex min-h-full flex-col">
        <header className="sticky top-0 z-40 border-b border-line bg-paper/85 backdrop-blur">
          <div className="mx-auto flex h-14 w-full max-w-7xl items-center justify-between px-5">
            <Link href="/" className="group flex items-baseline gap-2">
              <span className="font-display text-xl font-semibold tracking-tight text-ink">
                CLU<span className="text-accent">MI</span>
              </span>
              <span className="hidden text-[11px] uppercase tracking-[0.18em] text-ink-faint sm:inline">
                revisión de papers con agentes
              </span>
            </Link>
            <nav className="flex items-center gap-1 text-sm">
              <Link
                href="/"
                className="rounded-md px-3 py-1.5 font-medium text-ink-soft transition-colors hover:bg-paper-sunken hover:text-ink"
              >
                Biblioteca
              </Link>
              <Link
                href="/settings"
                className="rounded-md px-3 py-1.5 font-medium text-ink-soft transition-colors hover:bg-paper-sunken hover:text-ink"
              >
                Configuración
              </Link>
            </nav>
          </div>
        </header>
        <main className="flex min-h-0 flex-1 flex-col">{children}</main>
      </body>
    </html>
  );
}
