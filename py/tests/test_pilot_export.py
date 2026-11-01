import json

from chessdex.api.engine import Engine
from chessdex.bank.models import BankItem
from chessdex.sim.pilot_export import main, metrics, rows_from_db
from tests.test_accounts import FakeLichess, state_and_challenge

MATE1 = "6k1/5ppp/8/8/8/8/8/R5K1 w - - 0 1"


def test_export_only_finished_verified_and_anonymized(tmp_path):
    db = tmp_path / "s.db"
    e = Engine(bank=[BankItem(id=f"m{i}", source="t", fen=MATE1, solution=["a1a8"], puzzle_rating=r)
                     for i, r in enumerate(range(600, 2600, 100))], db_path=str(db))
    done = e.create("short")
    state, _, _ = state_and_challenge(e.link_start(done))
    e.link_callback("kod", state, FakeLichess())
    while not e.next_item(done)["done"]:
        e.respond(done, e.next_item(done)["item"]["token"], ["a1a8"], 1000)
    e.report(done)
    e.create("short")                                         # bitmemiş, hesapsız: dışarıda kalmalı
    rows = rows_from_db(str(db), salt="tuz")
    assert len(rows) == 1
    r = rows[0]
    assert r["session"] != done.id and "Oyuncu" not in json.dumps(r)          # anonim
    assert r["verified"]["rating"] == 1734 and r["calibration_eligible"]
    assert r["responses"] and set(r["responses"][0]) == {"item_id", "transform", "score", "elapsed_ms", "kind"}
    m = metrics(rows)
    assert m["n_eligible"] == 1 and "mae" in m and "coverage90" in m
    out = tmp_path / "p.jsonl"
    assert main([str(db), str(out)]) == 0 and len(out.read_text(encoding="utf-8").splitlines()) == 1


def test_metrics_empty():
    assert metrics([]) == {"n_eligible": 0}
