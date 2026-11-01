import io

import chess.pgn

from chessdex.bank.pgnstream import split_games

PGN = """[Event "Rated Rapid game"]
[Site "https://lichess.org/AAAA"]
[WhiteElo "800"]
[BlackElo "820"]

1. e4 { [%clk 0:10:00] } e5 { [%clk 0:10:00] } 2. Nf3 Nc6 1-0

[Event "Rated Blitz game"]
[Site "https://lichess.org/BBBB"]
[WhiteElo "2400"]
[BlackElo "2390"]

1. d4 d5 2. c4 0-1

[Event "Rated Rapid game"]
[Site "https://lichess.org/CCCC"]
[WhiteElo "1500"]
[BlackElo "1510"]

1. c4 e5 1/2-1/2
"""


def test_headers_and_moves_come_from_same_game():
    games = list(split_games(io.StringIO(PGN)))
    assert [g.headers["Site"][-4:] for g in games] == ["AAAA", "BBBB", "CCCC"]
    assert [g.headers["WhiteElo"] for g in games] == ["800", "2400", "1500"]
    first = [m.uci() for m in games[0].parse().mainline_moves()]
    second = [m.uci() for m in games[1].parse().mainline_moves()]
    assert first == ["e2e4", "e7e5", "g1f3", "b8c6"]
    assert second == ["d2d4", "d7d5", "c2c4"]
    assert games[0].parse().headers["Site"].endswith("AAAA")


def test_regression_read_headers_consumes_whole_game():
    """Hatanın kendisini belgeler: read_headers sonrası read_game SONRAKİ oyunu okur."""
    h = io.StringIO(PGN)
    chess.pgn.read_headers(h)
    g = chess.pgn.read_game(h)
    assert g.headers["Site"].endswith("BBBB")
