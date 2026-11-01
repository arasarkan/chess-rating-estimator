"use client";

import { useRouter } from "next/navigation";
import { LANG_COOKIE, type Lang } from "@/lib/i18n";
import { useLang } from "./LangProvider";

/** TR / EN seçici: çerezi yazar ve sunucu bileşenlerini yeniden çizer (oturum durumu korunur). */
export default function LangSwitch() {
  const { lang, t } = useLang();
  const router = useRouter();
  const set = (l: Lang) => {
    if (l === lang) return;
    document.cookie = `${LANG_COOKIE}=${l}; path=/; max-age=31536000; samesite=lax`;
    router.refresh();
  };
  return (
    <div className="lang" role="group" aria-label={t.nav.lang}>
      {(["tr", "en"] as const).map((l) => (
        <button key={l} type="button" aria-pressed={lang === l} onClick={() => set(l)} lang={l}>
          {l.toUpperCase()}
        </button>
      ))}
    </div>
  );
}
