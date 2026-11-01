"use client";

import { useEffect, useState } from "react";
import { api, errorMessage } from "@/lib/api";
import type { Report } from "@/lib/types";
import { useLang } from "./LangProvider";

/** İsteğe bağlı, açık rızalı Lichess hesap bağlama (pilot kalibrasyonu için doğrulanmış rating). */
export default function AccountLink({ sid, report, onLinked }: { sid: string; report: Report; onLinked?: () => void }) {
  const A = useLang().t.account;
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ text: string; ok: boolean } | null>(null);
  const [ccUser, setCcUser] = useState("");
  const [ccCode, setCcCode] = useState<string | null>(null);
  const [ccBusy, setCcBusy] = useState(false);
  const [ccErr, setCcErr] = useState<string | null>(null);

  const ccStart = async () => {
    setCcBusy(true);
    setCcErr(null);
    try {
      setCcCode((await api.chesscomStart(sid, ccUser.trim())).code);
    } catch (e) {
      setCcErr(errorMessage(e));
    } finally {
      setCcBusy(false);
    }
  };

  const ccVerify = async () => {
    setCcBusy(true);
    setCcErr(null);
    try {
      await api.chesscomVerify(sid);
      setNotice({ text: A.chesscomOk, ok: true });
      onLinked?.();
    } catch (e) {
      setCcErr(errorMessage(e));
    } finally {
      setCcBusy(false);
    }
  };

  useEffect(() => {
    const status = new URLSearchParams(window.location.search).get("link");
    if (status === "ok") setNotice({ text: A.lichessOk, ok: true });
    else if (status === "denied") setNotice({ text: A.lichessDenied, ok: false });
    else if (status === "failed") setNotice({ text: A.lichessFailed, ok: false });
  }, [A]);

  const start = async () => {
    setBusy(true);
    setErr(null);
    try {
      const { authorize_url } = await api.linkLichess(sid);
      window.location.assign(authorize_url);
    } catch (e) {
      setErr(errorMessage(e));
      setBusy(false);
    }
  };

  const ext = report.external;
  const cmp = report.comparison;
  return (
    <div>
      <h2>{A.heading}</h2>
      {notice && <div className={notice.ok ? "feedback ok" : "error"}>{notice.text}</div>}
      {ext ? (
        <>
          <p>
            {ext.platform === "chesscom" ? "Chess.com" : "Lichess"}: <strong>{ext.username}</strong> · rapid{" "}
            <strong>{ext.rating ?? "—"}</strong>
            {ext.rd != null && <span className="muted"> (RD {ext.rd}, {ext.games ?? 0} {A.games})</span>}
          </p>
          {cmp && (
            <p className="muted">
              {cmp.scale === "chesscom" ? A.diffChesscom : A.diff}:{" "}
              {cmp.difference > 0 ? "+" : ""}
              {cmp.difference} · {A.inside(cmp.inside_90)}
            </p>
          )}
          <p className="muted small">
            {ext.calibration_eligible
              ? A.eligible
              : `${A.ineligible} ${ext.ineligible_reasons.join(", ")}.`}
          </p>
        </>
      ) : (
        <>
          <p className="muted">{A.intro}</p>
          {err && <div className="error">{err}</div>}
          <button type="button" className="btn" onClick={start} disabled={busy}>
            {busy ? A.redirecting : A.linkLichess}
          </button>

          <h3 style={{ marginTop: 20 }}>{A.orChesscom}</h3>
          {!ccCode ? (
            <div className="row">
              <label htmlFor="cc-user" className="muted small">
                {A.ccUser}
              </label>
              <input
                id="cc-user"
                value={ccUser}
                onChange={(e) => setCcUser(e.target.value)}
                maxLength={25}
                autoComplete="off"
                placeholder={A.ccPlaceholder}
              />
              <button type="button" className="btn btn-small" onClick={ccStart} disabled={ccBusy || ccUser.trim().length < 3}>
                {A.getCode}
              </button>
            </div>
          ) : (
            <>
              <p>
                {A.ccInstr} <code>{ccCode}</code>
              </p>
              <button type="button" className="btn btn-small" onClick={ccVerify} disabled={ccBusy}>
                {ccBusy ? A.verifying : A.verify}
              </button>
            </>
          )}
          {ccErr && <div className="error">{ccErr}</div>}
        </>
      )}
    </div>
  );
}
