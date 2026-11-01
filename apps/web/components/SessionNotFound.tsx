"use client";

import Link from "next/link";
import { useLang } from "./LangProvider";

/** Oturum yok ya da süresi doldu (API 404): yeniden denemek işe yaramaz, yeni oturuma yönlendir. */
export default function SessionNotFound() {
  const N = useLang().t.notFound;
  return (
    <div className="card" role="alert">
      <h2 style={{ marginTop: 0 }}>{N.title}</h2>
      <p className="muted">{N.text}</p>
      <Link className="btn" href="/">
        {N.start}
      </Link>
    </div>
  );
}
