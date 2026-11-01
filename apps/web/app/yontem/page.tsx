import type { Metadata } from "next";
import MethodText from "@/components/content/MethodText";
import { getLang } from "@/lib/lang-server";

const HEAD = {
  tr: { title: "Yöntem", lead: "Gözlem modeli, uyarlamalı soru seçimi, oyun verisinin olabilirliği ve raporlama." },
  en: { title: "Method", lead: "Observation model, adaptive item selection, likelihood of the game data, and reporting." },
};

export async function generateMetadata(): Promise<Metadata> {
  const h = HEAD[await getLang()];
  return { title: h.title, description: h.lead };
}

export default async function MethodPage() {
  const lang = await getLang();
  const h = HEAD[lang];
  return (
    <article className="paper">
      <header className="paper-head">
        <h1>{h.title}</h1>
        <p className="paper-subtitle">{h.lead}</p>
      </header>
      <MethodText lang={lang} />
    </article>
  );
}
