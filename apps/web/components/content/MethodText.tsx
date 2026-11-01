import Link from "next/link";
import PosteriorDemo from "@/components/PosteriorDemo";
import type { Lang } from "@/lib/i18n";

/** Yöntem bölümü. Sabitler py/chessdex (measure/*, engines/*) ile aynı tutulmalı; kod değişirse burası da güncellenir. */
export default function MethodText({ lang }: { lang: Lang }) {
  return lang === "en" ? <En /> : <Tr />;
}

function Eq({ no, children }: { no: number; children: React.ReactNode }) {
  return (
    <div className="eq">
      <div className="eq-body">{children}</div>
      <div className="eq-no">({no})</div>
    </div>
  );
}

const REFS = [
  "Elo, A. E. (1978). The Rating of Chessplayers, Past and Present. Arco.",
  "Glickman, M. E. (1999). Parameter estimation in large dynamic paired comparison experiments. Journal of the Royal Statistical Society: Series C, 48(3), 377–394.",
  "Lord, F. M. (1980). Applications of Item Response Theory to Practical Testing Problems. Lawrence Erlbaum.",
  "Samejima, F. (1969). Estimation of latent ability using a response pattern of graded scores. Psychometrika Monograph Supplement, 17.",
  "van der Linden, W. J., & Glas, C. A. W. (Eds.). (2010). Elements of Adaptive Testing. Springer.",
  "Regan, K. W., & Haworth, G. M. (2011). Intrinsic chess ratings. Proceedings of the AAAI Conference on Artificial Intelligence, 25(1), 834–839.",
  "McIlroy-Young, R., Sen, S., Kleinberg, J., & Anderson, A. (2020). Aligning superhuman AI with human behavior: Chess as a model system. Proceedings of KDD 2020, 1677–1687.",
  "Tang, Z., Jiao, D., McIlroy-Young, R., Kleinberg, J., Sen, S., & Anderson, A. (2024). Maia-2: A unified model for human-AI alignment in chess. Advances in Neural Information Processing Systems 37.",
  "Lichess.org. Open database: puzzles (CC0). https://database.lichess.org/",
  "The Stockfish developers. Stockfish 19. https://stockfishchess.org/",
];

function Refs({ title }: { title: string }) {
  return (
    <>
      <h2 id="kaynaklar">{title}</h2>
      <ol className="refs">
        {REFS.map((r) => (
          <li key={r}>{r}</li>
        ))}
      </ol>
    </>
  );
}

function Tr() {
  return (
    <>
      <nav className="toc" aria-label="İçindekiler">
        <strong>İçindekiler</strong>
        <ol>
          <li><a href="#model">Gizil güç ve önsel dağılım</a></li>
          <li><a href="#sorular">Pozisyon soruları ve madde tepki modeli</a></li>
          <li><a href="#uyarlama">Uyarlamalı soru seçimi ve durdurma</a></li>
          <li><a href="#oyun">Oyun verisinin olabilirliği</a></li>
          <li><a href="#birlestirme">Birleştirme ve raporlama</a></li>
          <li><a href="#tekrar">Tekrarlanabilirlik ve veri bütünlüğü</a></li>
        </ol>
      </nav>

      <h2 id="model">1. Gizil güç ve önsel dağılım</h2>
      <p>
        Oyuncunun gücü θ, Lichess rapid ölçeğinde gizil bir değişken olarak ele alınır. θ, 400–3000 aralığında 10
        puan adımlı 261 noktalık bir ızgara üzerinde ayrık bir dağılımla temsil edilir. Önsel dağılım N(1500, 800²)
        olarak seçilmiştir. Daha dar bir önselin (sd = 450) uç güç düzeylerindeki oyuncuları ortalamaya doğru
        çektiği geçmiş oyun verisinde gözlenmiş, bu nedenle önsel bilinçli olarak geniş tutulmuştur.
      </p>
      <p>
        Ön anket cevaplandığında önsel ortalaması en fazla birkaç yüz puan kaydırılır ve standart sapma 700’e
        indirilir. Anket etkileri bilinçli olarak zayıf tutulmuştur ve henüz veriyle kestirilmemiştir.
      </p>
      <p>Her gözlem x için sonsal dağılım Bayes kuralıyla güncellenir; sayısal kararlılık için hesap log uzayında yapılır:</p>
      <Eq no={1}>log p(θ | x₁…xₙ) = log p(θ) + Σᵢ log p(xᵢ | θ) + sabit</Eq>

      <h2 id="sorular">2. Pozisyon soruları ve madde tepki modeli</h2>
      <p>
        Soru bankası yaklaşık 50 bin pozisyondan oluşur. Taktik, oyun sonu ve savunma soruları Lichess bulmaca
        veritabanından alınmıştır; yalnızca çok sayıda çözülmüş (1000’den fazla; seyrek bantlarda 300’den fazla), beğeni oranı yüksek ve
        derecelendirme sapması düşük (RD &lt; 80; seyrek bantlarda &lt; 90) bulmacalar kullanılmıştır. En fazla yedi taşlı pozisyonlar
        tablebase ile denetlenmiş; birden fazla doğru cevabı olanlar bankadan çıkarılmıştır.
      </p>
      <p>
        Pozisyonel karar soruları gerçek rapid oyunlarından seçilmiştir: Stockfish değerlendirmesinin ±250 santipiyon
        içinde olduğu, en iyi hamlenin alma ya da şah olmadığı pozisyonlar. Katılımcı birkaç şık arasından seçim
        yapar; şıklar en iyi hamleye göre kazanma olasılığı kaybıyla 0–3 arası puanlanır.
      </p>
      <p>
        Cevap olasılığı, madde tepki kuramının üç parametreli lojistik modelinin Elo ölçeğine uyarlanmış biçimiyle
        verilir:
      </p>
      <Eq no={2}>P(doğru | θ) = c + (1 − c) · 1 / (1 + 10^(−a(θ − b)/400))</Eq>
      <p>
        Burada b sorunun zorluğu (gücü b olan bir oyuncu soruyu yaklaşık yarı yarıya çözer), a ayırt edicilik, c ise
        şansla doğru cevap olasılığıdır. Bulmacalarda b, bulmaca derecelendirmesinden 200 çıkarılarak türetilmiştir.
        10 tabanı ve 400 ölçeği Elo beklenen skor formülüyle aynıdır; böylece zorluk ve güç aynı ölçekte okunur.
        Cevap süresi sıralı (graded) bir modelle işlenir: yanlış, yavaş doğru ve hızlı doğru üç ayrı kategoridir ve
        hızlı doğru cevap için eşik 150 puan yukarı kaydırılır (Samejima, 1969). Pozisyonel sorularda 0–3 puan aynı
        biçimde dört kategori olarak modellenir.
      </p>
      <figure>
        <PosteriorDemo />
        <figcaption>
          <b>Şekil 1.</b> Denklem (1) ve (2)’nin sadeleştirilmiş etkileşimli gösterimi (a = 1, c = 0,02). Dolu eğri
          sonsal dağılımı, gölgeli bölge %90 aralığı, kesikli eğri seçili sorunun her θ için doğru çözülme
          olasılığını gösterir. Tahmine uzak zorluktaki sorular dağılımı az değiştirir.
        </figcaption>
      </figure>

      <h2 id="uyarlama">3. Uyarlamalı soru seçimi ve durdurma</h2>
      <p>
        Her adımda, sonsal ortalamanın ±450 puan çevresindeki adaylar arasından beklenen sonsal varyansı en küçük
        olan sorular belirlenir (van der Linden ve Glas, 2010). Aynı soruların her katılımcıya gösterilmemesi için en
        iyi beş aday arasından sabit tohumlu rastgele seçim yapılır. Tür oranları hedef paylara (taktik %40,
        pozisyonel %25, oyun sonu %20, savunma %15) yakın tutulur.
      </p>
      <p>Ölçüm aşağıdaki koşullardan biri sağlandığında sona erer:</p>
      <ul>
        <li>en az 12 sorudan sonra sonsal standart sapma 70 puanın altına inmişse;</li>
        <li>20 soruya ulaşılmışsa;</li>
        <li>kısa protokolde, en az 6 sorudan sonra sunucuda ölçülen toplam cevap süresi 6,5 dakikayı aşmışsa.</li>
      </ul>

      <h2 id="oyun">4. Oyun verisinin olabilirliği</h2>
      <p>
        Bulmaca çözme ile oyun oynama aynı beceri değildir. Tam protokolde ikinci bir bilgi kaynağı olarak, seviyesi
        soru aşamasının sonsal ortancasına ayarlanmış Maia-2 modeline karşı tek bir 10+5 oyun oynanır. Maia-2, belirli
        bir güç düzeyindeki insanın hangi hamleyi seçeceğini tahmin etmek üzere Lichess oyunlarıyla eğitilmiş bir
        sinir ağıdır (McIlroy-Young vd., 2020; Tang vd., 2024). Oyundan iki olabilirlik türetilir:
      </p>
      <ol>
        <li>
          <strong>Hamle seçimi.</strong> Katılımcının her hamlesi için P_Maia(hamle | θ) her ızgara noktasında
          hesaplanır. Modelin en üst kovası 2137’dir; bunun üstünde log-olasılık, son iki kovanın eğiminin yarısıyla en fazla 600 puan dışdeğerlenir.
        </li>
        <li>
          <strong>Hamle kalitesi.</strong> Her hamleden önce ve sonra pozisyon Stockfish 19 ile sabit düğüm sayısında
          analiz edilir; hamlenin kazanma olasılığında yol açtığı kayıp kategorilere ayrılır ve P_SF(kayıp | θ),
          geçmiş oyunlardan öğrenilmiş bir modelle hesaplanır. Bu yaklaşım, hamle kalitesinden güç çıkarımı yapan
          önceki çalışmalarla akrabadır (Regan ve Haworth, 2011).
        </li>
      </ol>
      <p>Aşağıdaki hamleler hesaba katılmaz:</p>
      <ul>
        <li>tek yasal hamlenin bulunduğu ya da hamlenin her güç düzeyinde 0,9’dan yüksek olasılıkla oynandığı zorunlu durumlar;</li>
        <li>saatte 30 saniyeden az süre kalmışken oynanan hamleler.</li>
      </ul>
      <p>
        Analiz edilebilir hamle sayısı 15’in altındaysa oyun tahmine katılmaz. Oyun sonucu yalnızca zayıf bir ek
        olabilirlik (ağırlık 0,5) olarak kullanılır. Dışlama kuralları ve ağırlıklar 1.238 geçmiş Lichess rapid oyununun
        %70’i üzerinde seçilmiş, kalan %30’unda sınanmıştır.
      </p>

      <h2 id="birlestirme">5. Birleştirme ve raporlama</h2>
      <p>
        Aynı oyundaki hamleler birbirinden bağımsız olmadığından, oyun olabilirlikleri λ katsayılarıyla
        yumuşatılır; tam ağırlıkla sayılmaları aşırı dar aralıklara yol açar:
      </p>
      <Eq no={3}>
        log p(θ | veri) = log p(θ) + Σ log P(cevap | θ) + 0,7 · Σ log P_Maia(hamle | θ) + 0,2 · Σ log P_SF(kayıp | θ) + sabit
      </Eq>
      <p>Raporda şu nicelikler verilir:</p>
      <ul>
        <li><strong>Tahmin:</strong> sonsal dağılımın ortancası.</li>
        <li><strong>%90 aralık:</strong> sonsal dağılımın 5. ve 95. yüzdelikleri.</li>
        <li>
          <strong>Chess.com ve FIDE:</strong> doğrusal dönüşümle (Chess.com ≈ 1,14 · L − 514; FIDE ≈ 0,86 · L + 110)
          hesaplanır; dönüşüm belirsizliği (sd 100 ve 150) aralığa eklenir. Katsayılar yaklaşık değerlerdir.
        </li>
        <li>
          <strong>Alt beceriler:</strong> yalnızca ilgili türdeki sorulardan hesaplanır; %90 aralığı 400 puandan geniş
          olanlar gösterilmez.
        </li>
        <li>
          <strong>Kritik anlar:</strong> kazanma olasılığının en çok düştüğü hamleler ve Maia-2’ye göre o güç düzeyinde
          en olası hamle.
        </li>
      </ul>

      <h2 id="tekrar">6. Tekrarlanabilirlik ve veri bütünlüğü</h2>
      <ul>
        <li>
          Ölçümü etkileyen tüm hesaplar sunucuda yapılır; istemci yalnızca hamleyi ve süreyi iletir. Doğru cevaplar
          istemciye cevaptan önce gönderilmez.
        </li>
        <li>
          Stockfish sabit düğüm sayısı ve tek iş parçacığıyla, rastgele seçimler sabit tohumla çalışır. Aynı girdiler
          aynı sonucu verir; bu, her değişiklikte sabit bir referans oturumla otomatik olarak denetlenir.
        </li>
        <li>
          Sonucun yorumunu etkileyebilecek durumlar (kısa oyun, sekme değişimi, motor hamlelerine alışılmadık benzerlik)
          raporda yorum notu olarak belirtilir; tahmini değiştirmez.
        </li>
        <li>Her rapor, hesabı üreten model sürümünü içerir.</li>
      </ul>
      <p>
        Değerlendirme sonuçları ve sınırlılıklar <Link href="/sonuclar">Bulgular</Link> bölümündedir.
      </p>

      <Refs title="Kaynaklar" />
    </>
  );
}

function En() {
  return (
    <>
      <nav className="toc" aria-label="Contents">
        <strong>Contents</strong>
        <ol>
          <li><a href="#model">Latent strength and prior</a></li>
          <li><a href="#sorular">Chess problems and the item response model</a></li>
          <li><a href="#uyarlama">Adaptive item selection and stopping</a></li>
          <li><a href="#oyun">Likelihood of the game data</a></li>
          <li><a href="#birlestirme">Combination and reporting</a></li>
          <li><a href="#tekrar">Reproducibility and data integrity</a></li>
        </ol>
      </nav>

      <h2 id="model">1. Latent strength and prior</h2>
      <p>
        A player’s strength θ is treated as a latent variable on the Lichess rapid scale. θ is represented by a
        discrete distribution on a grid of 261 points from 400 to 3000 in steps of 10. The prior is N(1500, 800²). A
        narrower prior (sd = 450) was observed in historical game data to pull players at the extremes towards the
        mean, so the prior is deliberately wide.
      </p>
      <p>
        If the pre-survey is answered, the prior mean is shifted by at most a few hundred points and the standard
        deviation reduced to 700. The survey effects are deliberately weak and have not yet been estimated from data.
      </p>
      <p>For each observation x the posterior is updated with Bayes’ rule; for numerical stability the computation is carried out in log space:</p>
      <Eq no={1}>log p(θ | x₁…xₙ) = log p(θ) + Σᵢ log p(xᵢ | θ) + const</Eq>

      <h2 id="sorular">2. Chess problems and the item response model</h2>
      <p>
        The item bank contains about 50,000 positions. Tactics, endgame and defence items come from the Lichess puzzle
        database; only puzzles attempted many times (over 1,000; over 300 for sparse bands), with high popularity and a
        low rating deviation (RD &lt; 80; &lt; 90 for sparse bands) were used. Positions with at most seven pieces were checked against
        endgame tablebases, and those with more than one correct answer were removed.
      </p>
      <p>
        Positional items were selected from real rapid games: positions where the Stockfish evaluation lies within
        ±250 centipawns and the best move is neither a capture nor a check. The participant chooses among several
        options, each scored 0–3 by its loss of win probability relative to the best move.
      </p>
      <p>The response probability is the three-parameter logistic model of item response theory, adapted to the Elo scale:</p>
      <Eq no={2}>P(correct | θ) = c + (1 − c) · 1 / (1 + 10^(−a(θ − b)/400))</Eq>
      <p>
        Here b is the item difficulty (a player of strength b solves it about half the time), a the discrimination,
        and c the probability of a correct guess. For puzzles, b is the puzzle rating minus 200. The base 10 and the
        scale 400 are those of the Elo expected-score formula, so difficulty and strength are read on the same scale.
        Response time is handled with a graded model: incorrect, slow correct and fast correct are three categories,
        with the threshold for a fast correct answer shifted up by 150 points (Samejima, 1969). For positional items,
        the 0–3 score is modelled in the same way as four categories.
      </p>
      <figure>
        <PosteriorDemo />
        <figcaption>
          <b>Figure 1.</b> A simplified interactive illustration of equations (1) and (2) (a = 1, c = 0.02). The solid
          curve is the posterior, the shaded region the 90% interval, and the dashed curve the probability of solving
          the selected item at each θ. Items far from the current estimate change the distribution little.
        </figcaption>
      </figure>

      <h2 id="uyarlama">3. Adaptive item selection and stopping</h2>
      <p>
        At each step, among candidates within ±450 points of the posterior mean, the items with the smallest expected
        posterior variance are identified (van der Linden &amp; Glas, 2010). So that every participant does not see the
        same items, one of the best five candidates is drawn at random with a fixed seed. Item types are kept close to
        target shares (tactics 40%, positional 25%, endgame 20%, defence 15%).
      </p>
      <p>The measurement stops when one of the following holds:</p>
      <ul>
        <li>after at least 12 items, the posterior standard deviation is below 70 points;</li>
        <li>20 items have been given;</li>
        <li>in the short protocol, after at least 6 items, the total response time measured on the server exceeds 6.5 minutes.</li>
      </ul>

      <h2 id="oyun">4. Likelihood of the game data</h2>
      <p>
        Solving puzzles and playing games are not the same skill. In the full protocol, as a second source of
        information, one 10+5 game is played against Maia-2, set to the posterior median after the problem phase.
        Maia-2 is a neural network trained on Lichess games to predict which move a human of a given strength will
        choose (McIlroy-Young et al., 2020; Tang et al., 2024). Two likelihoods are derived from the game:
      </p>
      <ol>
        <li>
          <strong>Move choice.</strong> For each of the participant’s moves, P_Maia(move | θ) is computed at every grid
          point. The model’s highest bucket is 2137; above it, the log-probability is extrapolated at half the slope of the last two buckets, by at most 600 points.
        </li>
        <li>
          <strong>Move quality.</strong> The position before and after each move is analysed by Stockfish 19 at a fixed
          node count; the loss in win probability is binned into categories and P_SF(loss | θ) is computed with a
          model learned from historical games. This relates to earlier work inferring strength from move quality
          (Regan &amp; Haworth, 2011).
        </li>
      </ol>
      <p>The following moves are not counted:</p>
      <ul>
        <li>forced situations: a single legal move, or a move played with probability above 0.9 at every strength level;</li>
        <li>moves played with less than 30 seconds on the clock.</li>
      </ul>
      <p>
        If fewer than 15 moves remain analysable, the game is not used. The game result enters only as a weak
        additional likelihood (weight 0.5). The exclusion rules and weights were chosen on 70% of 1,238 historical
        Lichess rapid games and tested on the remaining 30%.
      </p>

      <h2 id="birlestirme">5. Combination and reporting</h2>
      <p>
        Moves within one game are not independent, so the game likelihoods are tempered by λ coefficients; counting
        them at full weight produces intervals that are too narrow:
      </p>
      <Eq no={3}>
        log p(θ | data) = log p(θ) + Σ log P(answer | θ) + 0.7 · Σ log P_Maia(move | θ) + 0.2 · Σ log P_SF(loss | θ) + const
      </Eq>
      <p>The report gives the following quantities:</p>
      <ul>
        <li><strong>Estimate:</strong> the posterior median.</li>
        <li><strong>90% interval:</strong> the 5th and 95th posterior percentiles.</li>
        <li>
          <strong>Chess.com and FIDE:</strong> linear conversions (Chess.com ≈ 1.14 · L − 514; FIDE ≈ 0.86 · L + 110),
          with the conversion uncertainty (sd 100 and 150) added to the interval. The coefficients are approximate.
        </li>
        <li>
          <strong>Sub-skills:</strong> computed from the items of the corresponding type only; those with a 90%
          interval wider than 400 points are not shown.
        </li>
        <li>
          <strong>Critical moments:</strong> the moves with the largest drop in win probability, and the most likely
          move at that strength according to Maia-2.
        </li>
      </ul>

      <h2 id="tekrar">6. Reproducibility and data integrity</h2>
      <ul>
        <li>
          All computations that affect the measurement run on the server; the client only sends the move and the
          time. Correct answers are not sent to the client before the response.
        </li>
        <li>
          Stockfish runs with a fixed node count and a single thread, and random choices use fixed seeds. The same
          inputs give the same result; this is checked automatically against a fixed reference session on every change.
        </li>
        <li>
          Circumstances that may affect interpretation (a short game, tab switching, unusual similarity to engine
          moves) are listed in the report as notes; they do not change the estimate.
        </li>
        <li>Every report records the model version that produced it.</li>
      </ul>
      <p>
        Evaluation results and limitations are in <Link href="/sonuclar">Findings</Link>.
      </p>

      <Refs title="References" />
    </>
  );
}
