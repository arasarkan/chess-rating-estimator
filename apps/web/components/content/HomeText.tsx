import Link from "next/link";
import type { Lang } from "@/lib/i18n";

/** Ana sayfa metni (özet, amaç, prosedür, ön bulgular, veriler). Sayılar docs/results/ ile aynı tutulmalı. */
export default function HomeText({ lang }: { lang: Lang }) {
  return lang === "en" ? <En /> : <Tr />;
}

function Tr() {
  return (
    <>
      <div className="abstract">
        <p>
          <span className="abstract-label">Özet.</span>
          Çevrim içi derecelendirme sistemlerinde bir oyuncunun puanının oturması onlarca oyun gerektirir. Bu
          çalışmada, yaklaşık 25 dakikalık tek bir oturumda rapid derecelendirmesinin hangi kesinlikle tahmin
          edilebileceği incelenmektedir. Ölçüm iki kaynağa dayanır: madde tepki kuramına göre uyarlamalı olarak seçilen
          12–20 pozisyon sorusu ve insan oyunlarıyla eğitilmiş bir modele (Maia-2) karşı oynanan tek bir 10+5 oyun.
          Gözlemler Bayes kuralıyla birleştirilir; sonuç tek bir değer yerine %90 sonsal aralıkla raporlanır.
          Benzetim ve geçmiş Lichess oyunları üzerindeki ön değerlendirmede ortalama mutlak hata 63 puan, aralık
          kapsaması 0,91 bulunmuştur. Bu değerler henüz gerçek katılımcılarla doğrulanmamıştır.
        </p>
        <p className="keywords">
          <span className="abstract-label">Anahtar kelimeler:</span>
          uyarlamalı test, madde tepki kuramı, Bayes çıkarımı, satranç derecelendirmesi, Maia-2
        </p>
      </div>

      <h2>1. Amaç</h2>
      <p>
        Yeni bir hesabın derecelendirmesi Glicko benzeri sistemlerde ancak birkaç düzine oyundan sonra kararlı hâle
        gelir. Deneyimli bir antrenör ise bir oyuncuyu birkaç pozisyon ve tek bir oyunla kabaca değerlendirebilir.
        Çalışmanın sorusu, bu ikinci yaklaşımın ölçülebilir ve tekrarlanabilir bir biçime getirilip
        getirilemeyeceğidir:
      </p>
      <p>
        <em>
          Kısa, belirlenimci bir ölçüm, bir oyuncunun rapid derecelendirmesini ne kadar dar ve ne kadar iyi kalibre
          edilmiş bir aralıkla tahmin edebilir?
        </em>
      </p>

      <h2>2. Prosedür</h2>
      <ol>
        <li>
          <strong>Ön anket (isteğe bağlı).</strong> Oyun deneyimine ilişkin üç soru; önsel dağılımı yalnızca hafifçe
          kaydırır.
        </li>
        <li>
          <strong>Pozisyon soruları (12–20).</strong> Taktik, oyun sonu, savunma ve pozisyonel karar soruları. Her
          cevaptan sonra bir sonraki soru, güncel tahmin altında belirsizliği en çok azaltması beklenen soru olarak
          seçilir.
        </li>
        <li>
          <strong>Oyun (yalnızca tam protokol).</strong> Seviyesi güncel tahmine ayarlanmış Maia-2 modeline karşı tek
          bir 10+5 oyun. Değerlendirmede sonuçtan çok hamlelerin hangi güç düzeyine benzediği esas alınır.
        </li>
        <li>
          <strong>Rapor.</strong> Lichess, Chess.com ve FIDE ölçeklerinde tahmin ve aralık, alt beceriler ve oyunun
          kritik anları.
        </li>
      </ol>

      <h2>3. Ön bulgular</h2>
      <p className="table-caption">
        <b>Tablo 1.</b> Tahmin hatası ve aralık kapsaması (ayrıntılar: <Link href="/sonuclar">Bulgular</Link>).
      </p>
      <div className="table-wrap">
        <table className="data">
          <thead>
            <tr>
              <th>Koşul</th>
              <th className="num">MAE</th>
              <th className="num">%90 kapsama</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Tam protokol (benzetim + gerçek oyun)</td>
              <td className="num">63</td>
              <td className="num">0,91</td>
            </tr>
            <tr>
              <td>Yalnızca pozisyon soruları (benzetim)</td>
              <td className="num">69</td>
              <td className="num">0,91</td>
            </tr>
            <tr>
              <td>Yalnızca tek oyun (gerçek veri, n = 372)</td>
              <td className="num">230</td>
              <td className="num">0,91</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p className="table-note">
        MAE: ortalama mutlak hata (derecelendirme puanı). Kapsama: gerçek değerin %90 aralığa düşme oranı.
      </p>

      <h2>4. Toplanan veriler</h2>
      <p>
        Cevaplar, cevap süreleri, oyun hamleleri ve oyun sırasında sekmeden ayrılma bilgisi kaydedilir. Veriler
        yalnızca tahminin hesaplanması ve yöntemin geliştirilmesi için kullanılır. Hesap açılması gerekmez. Rapordan
        isteğe bağlı olarak bir Lichess ya da Chess.com hesabı bağlanabilir; bu durumda tahmin, gerçek
        derecelendirmeyle karşılaştırılarak doğrulama verisi olarak kullanılır.
      </p>
      <p>
        Hesaplamanın ayrıntıları <Link href="/yontem">Yöntem</Link>, değerlendirme ve sınırlılıklar{" "}
        <Link href="/sonuclar">Bulgular</Link> bölümündedir.
      </p>
    </>
  );
}

function En() {
  return (
    <>
      <div className="abstract">
        <p>
          <span className="abstract-label">Abstract.</span>
          In online rating systems, a player’s rating takes dozens of games to stabilise. This study examines how
          precisely a rapid rating can be estimated from a single session of about 25 minutes. The measurement draws
          on two sources: 12–20 chess problems selected adaptively under item response theory, and one 10+5 game
          against a model trained on human games (Maia-2). The observations are combined with Bayes’ rule, and the
          result is reported as a 90% credible interval rather than a single number. In a preliminary evaluation on
          simulated responses and historical Lichess games, the mean absolute error was 63 rating points and the
          interval coverage 0.91. These figures have not yet been validated with real participants.
        </p>
        <p className="keywords">
          <span className="abstract-label">Keywords:</span>
          adaptive testing, item response theory, Bayesian inference, chess rating, Maia-2
        </p>
      </div>

      <h2>1. Aim</h2>
      <p>
        Under Glicko-type systems, the rating of a new account only settles after several dozen games. An experienced
        coach, by contrast, can roughly assess a player from a few positions and a single game. The question of this
        study is whether that second approach can be made measurable and reproducible:
      </p>
      <p>
        <em>
          How narrow, and how well calibrated, an interval can a short, deterministic measurement give for a
          player’s rapid rating?
        </em>
      </p>

      <h2>2. Procedure</h2>
      <ol>
        <li>
          <strong>Pre-survey (optional).</strong> Three questions about playing experience; they shift the prior only
          slightly.
        </li>
        <li>
          <strong>Chess problems (12–20).</strong> Tactics, endgame, defence and positional decisions. After each
          answer, the next item is the one expected to reduce the uncertainty most under the current estimate.
        </li>
        <li>
          <strong>Game (full protocol only).</strong> One 10+5 game against Maia-2, set to the current estimate. The
          assessment rests on which strength level the moves resemble rather than on the result.
        </li>
        <li>
          <strong>Report.</strong> Estimate and interval on the Lichess, Chess.com and FIDE scales, sub-skills, and
          the critical moments of the game.
        </li>
      </ol>

      <h2>3. Preliminary results</h2>
      <p className="table-caption">
        <b>Table 1.</b> Estimation error and interval coverage (details: <Link href="/sonuclar">Findings</Link>).
      </p>
      <div className="table-wrap">
        <table className="data">
          <thead>
            <tr>
              <th>Condition</th>
              <th className="num">MAE</th>
              <th className="num">90% coverage</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Full protocol (simulation + real game)</td>
              <td className="num">63</td>
              <td className="num">0.91</td>
            </tr>
            <tr>
              <td>Chess problems only (simulation)</td>
              <td className="num">69</td>
              <td className="num">0.91</td>
            </tr>
            <tr>
              <td>Single game only (real data, n = 372)</td>
              <td className="num">230</td>
              <td className="num">0.91</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p className="table-note">
        MAE: mean absolute error (rating points). Coverage: share of true values falling inside the 90% interval.
      </p>

      <h2>4. Data collected</h2>
      <p>
        Answers, response times, game moves and whether the tab was left during the game are recorded. The data are
        used only to compute the estimate and to improve the method. No account is required. A Lichess or Chess.com
        account can optionally be linked from the report; the estimate is then compared with the actual rating and
        used as validation data.
      </p>
      <p>
        Details of the computation are in <Link href="/yontem">Method</Link>; the evaluation and limitations are in{" "}
        <Link href="/sonuclar">Findings</Link>.
      </p>
    </>
  );
}
