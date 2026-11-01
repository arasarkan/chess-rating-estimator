"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api, errorMessage, local } from "@/lib/api";
import Turnstile, { TURNSTILE_SITEKEY } from "@/components/Turnstile";
import type { Mode, Survey } from "@/lib/types";
import HomeText from "@/components/content/HomeText";
import { useLang } from "@/components/LangProvider";
import { STUDY } from "@/lib/i18n";

// Değerler API anket sözlüğüyle birebir aynı (test_survey_contract.py); etiketler i18n sözlüğünden aynı sırayla.
const YEARS = ["", "lt1", "1-3", "3-10", "gt10"];
const GPW = ["", "0", "1-5", "6-20", "gt20"];
const TOURN = ["", "none", "club", "rated"];

export default function Home() {
  const router = useRouter();
  const { lang, t } = useLang();
  const s = STUDY[lang];
  const f = t.form;
  const [mode, setMode] = useState<Mode>("full");
  const [years, setYears] = useState("");
  const [gpw, setGpw] = useState("");
  const [tourn, setTourn] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [captcha, setCaptcha] = useState<string | null>(null);

  async function start() {
    setBusy(true);
    setErr(null);
    const survey: Survey = {};
    if (years) survey.years_playing = years;
    if (gpw) survey.games_per_week = gpw;
    if (tourn) survey.tournament = tourn;
    try {
      const res = await api.createSession({
        mode,
        survey: Object.keys(survey).length ? survey : undefined,
        turnstile_token: captcha ?? undefined,
      });
      local.setMode(res.session_id, mode);
      router.push(`/test/${encodeURIComponent(res.session_id)}`);
    } catch (e) {
      setErr(errorMessage(e));
      setBusy(false);
    }
  }

  const select = (id: string, label: string, value: string, set: (v: string) => void, values: string[], labels: string[]) => (
    <label htmlFor={id}>
      {label}
      <select id={id} value={value} onChange={(e) => set(e.target.value)}>
        {values.map((v, k) => (
          <option key={v} value={v}>
            {labels[k]}
          </option>
        ))}
      </select>
    </label>
  );

  return (
    <div className="home">
      <article className="paper">
        <header className="paper-head">
          <h1>{s.title}</h1>
          <p className="paper-subtitle">{s.subtitle}</p>
        </header>
        <HomeText lang={lang} />
      </article>

      <aside className="card start-panel" aria-labelledby="start-heading">
        <h2 id="start-heading">{f.heading}</h2>
        <fieldset className="field-group">
          <legend>{f.protocol}</legend>
          <label className="radio">
            <input type="radio" name="mode" checked={mode === "full"} onChange={() => setMode("full")} />
            <div>
              {f.full}
              <span>{f.fullDesc}</span>
            </div>
          </label>
          <label className="radio">
            <input type="radio" name="mode" checked={mode === "short"} onChange={() => setMode("short")} />
            <div>
              {f.short}
              <span>{f.shortDesc}</span>
            </div>
          </label>
        </fieldset>

        <fieldset className="field-group">
          <legend>
            {f.survey} <span className="muted small">({f.optional})</span>
          </legend>
          <div className="survey">
            {select("q-years", f.years, years, setYears, YEARS, f.yearsOpts)}
            {select("q-gpw", f.gpw, gpw, setGpw, GPW, f.gpwOpts)}
            {select("q-tourn", f.tourn, tourn, setTourn, TOURN, f.tournOpts)}
          </div>
        </fieldset>

        {err && <div className="error">{err}</div>}
        <Turnstile onToken={setCaptcha} />
        <button className="btn btn-block" onClick={start} disabled={busy || (!!TURNSTILE_SITEKEY && !captcha)}>
          {busy ? f.starting : f.start}
        </button>
        <p className="muted small" style={{ marginBottom: 0 }}>
          {f.note}
        </p>
      </aside>
    </div>
  );
}
