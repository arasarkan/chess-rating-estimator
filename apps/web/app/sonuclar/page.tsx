import type { Metadata } from "next";
import ResultsText from "@/components/content/ResultsText";
import { getLang } from "@/lib/lang-server";

const HEAD = {
  tr: { title: "Bulgular ve sınırlılıklar", lead: "Benzetim ve geçmiş Lichess oyunları üzerinde ön değerlendirme." },
  en: { title: "Findings and limitations", lead: "Preliminary evaluation on simulated responses and historical Lichess games." },
};

export async function generateMetadata(): Promise<Metadata> {
  const h = HEAD[await getLang()];
  return { title: h.title, description: h.lead };
}

export default async function ResultsPage() {
  const lang = await getLang();
  const h = HEAD[lang];
  return (
    <article className="paper">
      <header className="paper-head">
        <h1>{h.title}</h1>
        <p className="paper-subtitle">{h.lead}</p>
      </header>
      <ResultsText lang={lang} />
    </article>
  );
}
