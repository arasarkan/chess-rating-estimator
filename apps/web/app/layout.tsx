import type { Metadata, Viewport } from "next";
import Link from "next/link";
import "chessground/assets/chessground.base.css";
import "chessground/assets/chessground.brown.css";
import "chessground/assets/chessground.cburnett.css";
import "./globals.css";
import LangProvider from "@/components/LangProvider";
import Nav from "@/components/Nav";
import { DICT, STUDY } from "@/lib/i18n";
import { getLang } from "@/lib/lang-server";

export async function generateMetadata(): Promise<Metadata> {
  const s = STUDY[await getLang()];
  const site = process.env.NEXT_PUBLIC_SITE_URL; // paylaşım görselinin mutlak adresi için (yayında tanımlanmalı)
  return {
    metadataBase: site ? new URL(site) : undefined,
    title: { default: s.title, template: `%s — ${s.title}` },
    description: s.subtitle,
    openGraph: { title: s.title, description: s.subtitle, type: "website" },
    twitter: { card: "summary_large_image", title: s.title, description: s.subtitle },
  };
}

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
};

const MOCK = process.env.NEXT_PUBLIC_MOCK === "1";

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const lang = await getLang();
  const s = STUDY[lang];
  const t = DICT[lang];
  return (
    <html lang={lang}>
      <body>
        <LangProvider lang={lang}>
          <header className="masthead">
            <div className="masthead-inner">
              <div className="masthead-title">
                <Link href="/" className="study-title">
                  {s.title}
                </Link>
                <span className="study-meta">
                  {s.meta}
                  {MOCK && " · MOCK"}
                </span>
              </div>
              <Nav />
            </div>
          </header>
          <main className="container">{children}</main>
          <footer className="footer">
            <div className="footer-inner">
              <p>{t.footer.disclaimer}</p>
              <p>
                {t.footer.sources} <a href="https://database.lichess.org/#puzzles">{t.footer.puzzles}</a> ·{" "}
                <a href="https://github.com/CSSLab/maia2">Maia-2</a> · <a href="https://stockfishchess.org/">Stockfish</a>
              </p>
            </div>
          </footer>
        </LangProvider>
      </body>
    </html>
  );
}
