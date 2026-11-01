"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useLang } from "./LangProvider";
import LangSwitch from "./LangSwitch";

/** Üst menü. Oturum akışındayken (soru/oyun/rapor) "Çalışma" bağlantısı etkin görünür. */
export default function Nav() {
  const { t } = useLang();
  const path = usePathname() ?? "/";
  const inStudy = path === "/" || /^\/(test|play|report)\//.test(path);
  const links = [
    { href: "/", label: t.nav.study, active: inStudy },
    { href: "/yontem", label: t.nav.method, active: path.startsWith("/yontem") },
    { href: "/sonuclar", label: t.nav.results, active: path.startsWith("/sonuclar") },
  ];
  return (
    <nav className="nav" aria-label={t.nav.aria}>
      {links.map((l) => (
        <Link key={l.href} href={l.href} aria-current={l.active ? "page" : undefined}>
          {l.label}
        </Link>
      ))}
      <LangSwitch />
    </nav>
  );
}
