"""Web formu ↔ API anket sözleşmesi: formdaki her alan/şık API'de tanımlı ve önseli etkiler.

Önceki hata: web `years_playing` ve `lt1/gt10/...` gönderirken API `years` ve `<1/10+/...` bekliyordu; anket hiç etki
etmiyordu (katı doğrulamadan sonra da oturum oluşturmayı 422 ile bozuyordu)."""
import re
from pathlib import Path

from chessdex.measure.posterior import Posterior
from chessdex.measure.prior import SURVEY_EFFECTS, default_prior, survey_prior

PAGE = Path(__file__).resolve().parents[2] / "apps" / "web" / "app" / "page.tsx"


def web_survey():
    src = PAGE.read_text(encoding="utf-8")
    keys = re.findall(r"survey\.(\w+)\s*=", src)
    # şık değerleri düz diziler (etiketler dile göre i18n sözlüğünde, aynı sırayla)
    blocks = re.findall(r"const (?:YEARS|GPW|TOURN) = \[([^\]]*)\]", src)
    values = [[v for v in re.findall(r"\"([^\"]*)\"", b) if v] for b in blocks]
    return keys, values


def test_web_keys_and_values_known_to_api():
    keys, values = web_survey()
    assert keys == ["years_playing", "games_per_week", "tournament"]
    assert len(values) == 3
    for key, vals in zip(keys, values):
        assert set(vals) == set(SURVEY_EFFECTS[key]), (key, vals)


def test_web_answers_shift_prior_monotonically():
    """Formdaki şıklar düşükten yükseğe sıralı; önsel ortalaması aynı sırayla artmalı, uç cevaplar belirgin etkili olmalı."""
    base = Posterior(default_prior()).mean()
    keys, values = web_survey()
    for key, vals in zip(keys, values):
        means = [Posterior(survey_prior({key: v})).mean() for v in vals]
        assert means == sorted(means) and means[0] < means[-1], (key, means)
        assert means[0] < base - 30, (key, means[0] - base)
