import { cookies, headers } from "next/headers";
import { LANG_COOKIE, langFromAccept, parseLang, type Lang } from "./i18n";

/** Sunucu bileşenleri için arayüz dili: önce çerez, yoksa Accept-Language. */
export async function getLang(): Promise<Lang> {
  const c = parseLang((await cookies()).get(LANG_COOKIE)?.value);
  if (c) return c;
  return langFromAccept((await headers()).get("accept-language"));
}
