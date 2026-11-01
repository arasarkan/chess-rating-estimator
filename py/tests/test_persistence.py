"""Kalıcılık: API yeniden başlasa da oturumlar ve maçlar sürer; tekrarlanan istekler çift sayılmaz."""
import chess

from chessdex.api.engine import Engine
from chessdex.api.store import SessionStore
from chessdex.bank.models import BankItem

MATE1 = "6k1/5ppp/8/8/8/8/8/R5K1 w - - 0 1"


class NoEngine:
    available = False
    nodes = 0

    def analyse(self, fen):
        return None


def bank():
    return [BankItem(id=f"m{i}", source="t", fen=MATE1, solution=["a1a8"], puzzle_rating=r)
            for i, r in enumerate(range(600, 2600, 50))]


def make(db):
    e = Engine(bank=bank(), db_path=str(db))
    e.analyzer = NoEngine()
    return e


def answer_all(e, s):
    while not e.next_item(s)["done"]:
        it = e.next_item(s)["item"]
        b = chess.Board(it["fen"])
        mv = next(m.uci() for m in b.legal_moves if (b.copy(), b.push(m), b.is_checkmate(), b.pop())[2])
        e.respond(s, it["token"], [mv], 1000)


def test_session_survives_restart_mid_items(tmp_path):
    db = tmp_path / "s.db"
    e1 = make(db)
    s = e1.create("short")
    first = e1.next_item(s)["item"]                     # bekleyen senaryo diske yazıldı
    e2 = make(db)                                       # "yeniden başlatma"
    s2 = e2.get(s.id)
    again = e2.next_item(s2)["item"]
    assert again["token"] == first["token"] and again["fen"] == first["fen"]   # aynı senaryo, aynı token
    answer_all(e2, s2)
    rep = e2.report(s2)
    assert rep["estimate"]["stage"] == "done"
    e3 = make(db)
    assert e3.report(e3.get(s.id))["estimate"] == rep["estimate"]


def test_game_survives_restart_and_duplicate_moves_ignored(tmp_path):
    db = tmp_path / "g.db"
    e1 = make(db)
    s = e1.create("full")
    answer_all(e1, s)
    g = e1.start_game(s)
    b = chess.Board()
    user_white = g.user_color == "white"
    ply = 0
    while ply < 50:
        mv = sorted(m.uci() for m in b.legal_moves)[0] if b.turn == chess.WHITE else \
            sorted(m.uci() for m in b.legal_moves)[-1]
        if (b.turn == chess.WHITE) == user_white:
            e1.user_move(g.id, ply, b.fen(), mv, 3000, 500_000)
            e1.user_move(g.id, ply, b.fen(), mv, 3000, 500_000)      # yeniden deneme: yok sayılmalı
        b.push_uci(mv)
        ply += 1
        if ply == 25:                                                # maçın ortasında yeniden başlat
            for f in e1.sessions[s.id].game.futures:
                f.result()
            e1 = make(db)
            assert e1.games[g.id].id == s.id
    sess = e1.game_session(g.id)
    assert len(sess.game.moves) == len({m["ply"] for m in sess.game.moves}) == 25
    e1.finish(g.id, "1-0", "resign", None)
    e1.finish(g.id, "1-0", "resign", None)                           # tekrarlanan finish: idempotent
    rep = e1.report(sess)
    assert rep["estimate"]["stage"] == "done" and rep["flags"].count("short_game") <= 1
    try:
        e1.user_move(g.id, 99, b.fen(), "e2e4", 1, 1)
        raise AssertionError("bitmiş oyuna hamle kabul edildi")
    except ValueError:
        pass


def test_store_ttl_and_corrupt_rows(tmp_path):
    st = SessionStore(tmp_path / "x.db")
    e = Engine(bank=bank())
    s = e.create("short")
    st.save(s)
    assert len(st.load_all(ttl_s=3600)) == 1
    assert st.load_all(ttl_s=3600, now=s.last_active + 7200) == [] and st.count() == 0   # süresi doldu → silindi
    st.save(s)
    st._db.execute("UPDATE sessions SET data = ?", (b"bozuk",))
    assert st.load_all(ttl_s=3600) == [] and st.count() == 0                            # bozuk kayıt atlanır


def test_next_item_reports_server_elapsed_time(tmp_path):
    e = make(tmp_path / "t.db")
    s = e.create("short")
    first = e.next_item(s)["item"]
    assert 0 <= first["elapsed_ms"] < 1000
    s.pending.shown_at -= 5.0                     # 5 sn önce gösterilmiş gibi (sayfa yenilendi)
    again = e.next_item(s)["item"]
    assert again["token"] == first["token"] and again["elapsed_ms"] >= 5000
