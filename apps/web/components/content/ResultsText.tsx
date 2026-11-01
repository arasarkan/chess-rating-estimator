import Link from "next/link";
import type { Lang } from "@/lib/i18n";

/** Bulgular ve sınırlılıklar. Sayılar docs/results/{extremes,backtest,short_mode}.md ile aynı tutulmalı. */
export default function ResultsText({ lang }: { lang: Lang }) {
  return lang === "en" ? <En /> : <Tr />;
}

// Bant, ort. kayıp, büyük hata oranı, Maia-2 en iyi açıklayan seviye (backtest.md)
const SIGNALS: [string, string, string, number][] = [
  ["600–899", "5.7", "6.3", 903],
  ["900–1199", "5.1", "4.8", 903],
  ["1200–1499", "5.1", "4.6", 1350],
  ["1500–1799", "4.5", "3.5", 1650],
  ["1800–2099", "3.8", "2.3", 1950],
  ["2100–2399", "3.2", "1.8", 2137],
  ["2400–2699", "2.0", "0.8", 2137],
];
// sn/soru, ort. soru, MAE, kapsama, ort. genişlik (short_mode.md)
const SHORT: [string, string, number, string, number][] = [
  ["≤ 20", "19.8", 69, "0.90", 280],
  ["30", "13.0", 86, "0.91", 354],
  ["45", "9.0", 107, "0.90", 432],
  ["60", "7.0", 120, "0.91", 516],
];

function num(v: string | number, lang: Lang) {
  return lang === "tr" ? String(v).replace(".", ",") : String(v);
}

function MainTable({ lang }: { lang: Lang }) {
  const tr = lang === "tr";
  const rows: [string, string, string, string, boolean][] = tr
    ? [
        ["Tam protokol (benzetim cevapları + gerçek oyun)", "62,7", "0,911", "271", true],
        ["Yalnızca pozisyon soruları (benzetim, ~20 soru)", "69,1", "0,905", "285", false],
        ["Yalnızca tek oyun (gerçek veri)", "230 [208–251]", "0,911 [0,88–0,94]", "950", false],
        ["Veri yok (yalnızca önsel)", "532", "–", "–", false],
      ]
    : [
        ["Full protocol (simulated answers + real game)", "62.7", "0.911", "271", true],
        ["Chess problems only (simulation, ~20 items)", "69.1", "0.905", "285", false],
        ["Single game only (real data)", "230 [208–251]", "0.911 [0.88–0.94]", "950", false],
        ["No data (prior only)", "532", "–", "–", false],
      ];
  return (
    <>
      <p className="table-caption">
        <b>{tr ? "Tablo 1." : "Table 1."}</b>{" "}
        {tr
          ? "Test kümesinde tahmin hatası ve %90 aralık kapsaması (n = 372 oyuncu; köşeli parantez: %95 bootstrap aralığı)."
          : "Estimation error and 90% interval coverage on the test set (n = 372 players; brackets: 95% bootstrap interval)."}
      </p>
      <div className="table-wrap">
        <table className="data">
          <thead>
            <tr>
              <th>{tr ? "Koşul" : "Condition"}</th>
              <th className="num">MAE</th>
              <th className="num">{tr ? "Kapsama" : "Coverage"}</th>
              <th className="num">{tr ? "Ort. genişlik" : "Mean width"}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([c, m, k, w, hl]) => (
              <tr key={c} className={hl ? "hl" : undefined}>
                <td>{c}</td>
                <td className="num">{m}</td>
                <td className="num">{k}</td>
                <td className="num">{w}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="table-note">
        {tr
          ? "Çalışma planında belirlenen hedefler: MAE ≤ 150, kapsama 0,87–0,93, her 300 puanlık bantta ortalama sapma ≤ 50. Tam protokolde en büyük bant sapması 23,3 (2400+)."
          : "Targets set in the study plan: MAE ≤ 150, coverage 0.87–0.93, mean bias ≤ 50 in every 300-point band. Largest band bias under the full protocol: 23.3 (2400+)."}
      </p>
    </>
  );
}

function SignalsTable({ lang }: { lang: Lang }) {
  const tr = lang === "tr";
  return (
    <>
      <p className="table-caption">
        <b>{tr ? "Tablo 2." : "Table 2."}</b>{" "}
        {tr
          ? "Geçmiş Lichess rapid oyunlarında hamle düzeyindeki sinyallerin derecelendirmeyle ilişkisi."
          : "Relationship between move-level signals and rating in historical Lichess rapid games."}
      </p>
      <div className="table-wrap">
        <table className="data">
          <thead>
            <tr>
              <th>{tr ? "Derecelendirme bandı" : "Rating band"}</th>
              <th className="num">{tr ? "Ort. kayıp / hamle (%)" : "Mean loss / move (%)"}</th>
              <th className="num">{tr ? "Büyük hata oranı (%)" : "Blunder rate (%)"}</th>
              <th className="num">{tr ? "Maia-2 en uyumlu seviye" : "Best-fitting Maia-2 level"}</th>
            </tr>
          </thead>
          <tbody>
            {SIGNALS.map(([b, l, e, m]) => (
              <tr key={b}>
                <td>{b}</td>
                <td className="num">{num(l, lang)}</td>
                <td className="num">{num(e, lang)}</td>
                <td className="num">{m}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="table-note">
        {tr
          ? "Kayıp: hamlenin kazanma olasılığında yol açtığı düşüş (Stockfish 19). Büyük hata: kazanma olasılığını %30’dan fazla düşüren hamle. Son sütun: oyuncunun hamlelerini en yüksek olasılıkla açıklayan Maia-2 seviyesi (bant ortalaması). Oyun başına bu seviye ile gerçek derecelendirme arasındaki korelasyon r = 0,69."
          : "Loss: drop in win probability caused by the move (Stockfish 19). Blunder: a move reducing win probability by more than 30%. Last column: the Maia-2 level that explains the player’s moves with the highest likelihood (band average). Per-game correlation between this level and the actual rating: r = 0.69."}
      </p>
    </>
  );
}

function ShortTable({ lang }: { lang: Lang }) {
  const tr = lang === "tr";
  return (
    <>
      <p className="table-caption">
        <b>{tr ? "Tablo 3." : "Table 3."}</b>{" "}
        {tr
          ? "Kısa protokolde cevap hızına göre sonuçlar (benzetim, 600 sanal katılımcı, θ ~ U(400, 2800))."
          : "Short-protocol results by response speed (simulation, 600 virtual participants, θ ~ U(400, 2800))."}
      </p>
      <div className="table-wrap">
        <table className="data">
          <thead>
            <tr>
              <th>{tr ? "Süre / soru (sn)" : "Time / item (s)"}</th>
              <th className="num">{tr ? "Ort. soru" : "Mean items"}</th>
              <th className="num">MAE</th>
              <th className="num">{tr ? "Kapsama" : "Coverage"}</th>
              <th className="num">{tr ? "Ort. genişlik" : "Mean width"}</th>
            </tr>
          </thead>
          <tbody>
            {SHORT.map(([s, n, m, k, w]) => (
              <tr key={s}>
                <td>{s}</td>
                <td className="num">{num(n, lang)}</td>
                <td className="num">{m}</td>
                <td className="num">{num(k, lang)}</td>
                <td className="num">{w}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function Tr() {
  return (
    <>
      <h2>1. Değerlendirme tasarımı</h2>
      <p>İki ölçüt kullanılmıştır:</p>
      <ul>
        <li>
          <strong>Ortalama mutlak hata (MAE):</strong> tahmin ile gerçek derecelendirme arasındaki mutlak farkın
          ortalaması.
        </li>
        <li>
          <strong>Kapsama:</strong> gerçek derecelendirmenin %90 aralığın içinde kalma oranı. İyi kalibre edilmiş bir
          yöntemde 0,90’a yakın olmalıdır; daha düşük değer aşırı dar, daha yüksek değer gereğinden geniş aralıklara
          işaret eder.
        </li>
      </ul>
      <p>Üç deney yürütülmüştür:</p>
      <ol>
        <li>
          <strong>Benzetim.</strong> Gücü bilinen sanal katılımcılar, Denklem (2)’deki modele göre cevap üretir. Bu
          deney seçim ve durdurma kurallarını sınar; modelin kendisi yanlışsa bunu ortaya koyamaz.
        </li>
        <li>
          <strong>Geçmiş oyunlar.</strong> Ağustos 2026 Lichess veritabanından, derecelendirmesi kararlı oyunculara ait
          1.238 rapid oyun (600–2699 arası her 100 puanlık bantta yaklaşık 60). Bu deney oyun verisinin tek başına ne
          kadar bilgi taşıdığını ölçer. Ayarlar oyunların %70’i üzerinde seçilmiş, sonuçlar kalan %30’dan (372 oyun)
          raporlanmıştır.
        </li>
        <li>
          <strong>Birleşik değerlendirme.</strong> Aynı 372 oyuncu için, gerçek derecelendirmelerinde üretilen benzetim
          cevapları ile kendi gerçek oyunları birlikte kullanılmıştır.
        </li>
      </ol>

      <h2>2. Ana sonuçlar</h2>
      <MainTable lang="tr" />
      <p>
        İlk iki satır benzetim cevaplarına dayandığından iyimser kabul edilmelidir: gerçek katılımcıların cevapları
        modelin varsaydığından daha gürültülü olacaktır. Üçüncü satır tamamen gerçek veriye dayanır ve tek bir oyunun
        gücü kabaca ayırt ettiğini, ancak tek başına dar bir tahmin için yetersiz kaldığını gösterir. Oyunun katkısı,
        pozisyon sorularının ölçmediği oyun içi karar verme becerisini tahmine eklemesidir.
      </p>

      <h2>3. Oyun sinyalleri</h2>
      <SignalsTable lang="tr" />
      <p>
        Hamle başına ortalama kayıp ve büyük hata oranı derecelendirmeyle düzenli biçimde azalır; ancak ilişki 600–1500
        arasında zayıftır. Maia-2’nin en uyumlu seviyesi 900’ün altında ve 2137’nin üstünde doygunluğa ulaşır; uç
        bantlardaki tahmin sapmasının başlıca kaynağı budur.
      </p>

      <h2>4. Kısa protokol</h2>
      <ShortTable lang="tr" />
      <p>
        Süre sınırı nedeniyle yavaş cevap veren katılımcı daha az soru görür. Aralık genişliği buna göre artar; kapsama
        her hızda 0,90 civarında kalır.
      </p>

      <h2>5. Sınırlılıklar</h2>
      <ul>
        <li>
          <strong>Madde parametreleri insan cevaplarıyla kestirilmemiştir.</strong> Zorluk değerleri Lichess bulmaca
          derecelendirmelerinden sabit bir kaydırmayla türetilmiştir. Lichess’te zamana karşı çözülen bir bulmaca ile
          bu ortamda çözülen bir soru farklı davranabilir. Sonuçlardaki en büyük belirsizlik kaynağı budur.
        </li>
        <li>
          <strong>Pozisyonel sorular geçicidir.</strong> Ayırt edicilikleri gerçek oyun kararlarıyla sınanmış ve
          abartılı bulunmuştur; etkileri bu nedenle yarıya indirilmiştir (a × 0,5). Kesin değer pilot veriyle
          belirlenecektir.
        </li>
        <li>
          <strong>Uç bantlarda ortalamaya çekilme.</strong> Tek oyunla çok zayıf oyuncular yaklaşık 200 puan yüksek,
          çok güçlü oyuncular yaklaşık 250 puan düşük tahmin edilmektedir. Aralıklar bu sapmayı büyük ölçüde kapsar
          (uç bantlarda kapsama 0,81–0,96).
        </li>
        <li>
          <strong>Ölçek dönüşümleri yaklaşıktır.</strong> Chess.com ve FIDE dönüşümleri eşleştirilmiş hesap verisiyle
          kurulmamıştır.
        </li>
        <li>
          <strong>Anket etkileri varsayımsaldır</strong> ve bu nedenle küçük tutulmuştur.
        </li>
        <li>
          <strong>Kapsam yalnızca çevrim içi rapid derecelendirmesidir.</strong> Blitz, klasik ve tahta başı
          derecelendirmeler için ayrı doğrulama gerekir.
        </li>
        <li>
          <strong>Hile tespiti yapılmaz.</strong> Sekme değişimi ve motor benzerliği yalnızca yorum notu olarak
          raporlanır.
        </li>
      </ul>

      <h2>6. Önceki çalışmalarla ilişki</h2>
      <p>
        Uyarlamalı test ve madde tepki kuramı eğitim ölçmesinde yerleşik yöntemlerdir; hamle kalitesinden güç çıkarımı
        (Regan ve Haworth, 2011) ve insan hamle seçimini modelleme (Maia, Maia-2) ayrı ayrı incelenmiştir. Bu
        çalışmanın katkısı, bu bileşenleri tek, belirlenimci ve belirsizliğini açıkça raporlayan bir ölçümde
        birleştirmek ve aralıkların kalibrasyonunu değerlendirmektir. Mevcut derecelendirme tahmin araçlarıyla aynı
        oyuncular üzerinde karşılaştırma yapılmamıştır; bu nedenle göreli üstünlük iddia edilmez.
      </p>

      <h2>7. Sonraki aşama: pilot çalışma</h2>
      <p>
        Ölçümü tamamlayıp Lichess ya da Chess.com hesabını bağlayan katılımcıların tahminleri gerçek
        derecelendirmeleriyle karşılaştırılacaktır. Bu veriyle madde parametreleri insan cevaplarından yeniden
        kestirilecek, ölçek dönüşümleri eşleştirilmiş verilerle kurulacak ve yukarıdaki tablolar gerçek katılımcılarla
        yeniden hesaplanacaktır. Katılım için <Link href="/">çalışma sayfasına</Link> gidilebilir.
      </p>
    </>
  );
}

function En() {
  return (
    <>
      <h2>1. Evaluation design</h2>
      <p>Two criteria are used:</p>
      <ul>
        <li>
          <strong>Mean absolute error (MAE):</strong> the average absolute difference between the estimate and the
          actual rating.
        </li>
        <li>
          <strong>Coverage:</strong> the share of actual ratings that fall inside the 90% interval. For a
          well-calibrated method it should be close to 0.90; lower values indicate overconfident intervals, higher
          values needlessly wide ones.
        </li>
      </ul>
      <p>Three experiments were run:</p>
      <ol>
        <li>
          <strong>Simulation.</strong> Virtual participants of known strength generate answers according to the model
          in equation (2). This tests the selection and stopping rules; it cannot reveal errors in the model itself.
        </li>
        <li>
          <strong>Historical games.</strong> 1,238 rapid games by players with stable ratings from the August 2026
          Lichess database (about 60 per 100-point band from 600 to 2699). This measures how much information the game
          data carry on their own. Settings were chosen on 70% of the games and results are reported on the remaining
          30% (372 games).
        </li>
        <li>
          <strong>Combined evaluation.</strong> For the same 372 players, simulated answers generated at their actual
          rating were combined with their own real game.
        </li>
      </ol>

      <h2>2. Main results</h2>
      <MainTable lang="en" />
      <p>
        The first two rows rest on simulated answers and should be regarded as optimistic: real participants will
        answer more noisily than the model assumes. The third row is based entirely on real data; it shows that a
        single game separates strength levels roughly but is not enough for a narrow estimate on its own. The
        contribution of the game is to add in-game decision making, which the chess problems do not measure.
      </p>

      <h2>3. Game signals</h2>
      <SignalsTable lang="en" />
      <p>
        Mean loss per move and the blunder rate decrease steadily with rating, although the relationship is weak
        between 600 and 1500. The best-fitting Maia-2 level saturates below 900 and above 2137; this is the main source
        of bias in the extreme bands.
      </p>

      <h2>4. Short protocol</h2>
      <ShortTable lang="en" />
      <p>
        Because of the time limit, slower participants see fewer items. The interval widens accordingly, and coverage
        stays around 0.90 at every speed.
      </p>

      <h2>5. Limitations</h2>
      <ul>
        <li>
          <strong>Item parameters have not been estimated from human responses.</strong> Difficulties were derived
          from Lichess puzzle ratings by a fixed offset. A puzzle solved against the clock on Lichess may behave
          differently from an item in this setting. This is the largest source of uncertainty in the results.
        </li>
        <li>
          <strong>Positional items are provisional.</strong> Their discrimination was tested against real game
          decisions and found to be overstated; their effect was therefore halved (a × 0.5). The final value will be
          set from pilot data.
        </li>
        <li>
          <strong>Shrinkage at the extremes.</strong> From a single game, very weak players are estimated about 200
          points too high and very strong players about 250 points too low. The intervals largely cover this bias
          (coverage 0.81–0.96 in the extreme bands).
        </li>
        <li>
          <strong>Scale conversions are approximate.</strong> The Chess.com and FIDE conversions were not built from
          paired account data.
        </li>
        <li>
          <strong>Survey effects are assumed</strong> and therefore kept small.
        </li>
        <li>
          <strong>The scope is online rapid only.</strong> Blitz, classical and over-the-board ratings need separate
          validation.
        </li>
        <li>
          <strong>No cheat detection.</strong> Tab switching and engine similarity are reported only as notes.
        </li>
      </ul>

      <h2>6. Relation to previous work</h2>
      <p>
        Adaptive testing and item response theory are established methods in educational measurement; inferring
        strength from move quality (Regan &amp; Haworth, 2011) and modelling human move choice (Maia, Maia-2) have been
        studied separately. The contribution of this study is to combine these components in a single deterministic
        measurement that reports its uncertainty explicitly, and to evaluate the calibration of its intervals. No
        comparison with existing rating-estimation tools on the same players has been made, so no claim of relative
        superiority is made.
      </p>

      <h2>7. Next stage: pilot study</h2>
      <p>
        For participants who complete the measurement and link a Lichess or Chess.com account, estimates will be
        compared with actual ratings. These data will be used to re-estimate the item parameters from human responses,
        build the scale conversions from paired data, and recompute the tables above with real participants. To take
        part, see the <Link href="/">study page</Link>.
      </p>
    </>
  );
}
