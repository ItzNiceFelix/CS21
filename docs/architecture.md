# Arsitektur Refactor — Cegukan Seeker (cs_core)

> Sumber perilaku baseline: `docs/spec-current.md`. Dokumen ini merancang refactor BESAR.
> Tidak menulis kode implementasi. Fokus batas modul, kontrak, keputusan, trade-off, migrasi, fase.

---

## 1. Ringkasan Masalah & Prinsip Desain

### Masalah teridentifikasi dari baseline

| # | Masalah | Bukti (spec-current) |
|---|---|---|
| M1 | Scoring terduplikasi 3x (E/IE/AE) dengan divergensi label & highlight | §6 |
| M2 | `classify_text` + `ALL_PATTERNS_COMBINED` scan tiap segmen dua kali | §1.2, §1.5, `cs20_engine.py:811,819` |
| M3 | Regex scoring per segmen × per tier × per pattern (N×M loop tanpa short-circuit) | `classify_text` E666–675 |
| M4 | VTT di-parse penuh ke memori, dibuang setelah 1 video, tanpa cache | IE260–330, AE133–156 |
| M5 | Kamus regex manual 7 bahasa = maintenance meledak; varian typo manual | §2 |
| M6 | Anti-typo berbasis regex morph (`ce+g+[uo]+k+...`) = rawan over-fit & FP | §2.1 TYPO |
| M7 | Tier `(?!)` no-op tetap hidup di `tier_counts` | §2, Open Q#2 |
| M8 | `pat.sub` highlight bisa menyisipkan span ke dalam span; hanya E yang highlight | §6.2 #1, Open Q#6 |
| M9 | Clustering pakai span hit (bukan durasi video) — intensional? | §4, Open Q#4 |
| M10 | Chatseeker punya definisi keyword kedua (JSON-quoted vs plain) | §7, Open Q#8 |
| M11 | `_analyze_fallback` hasil berbeda total tanpa penanda status | §6.2 #10, Open Q#10 |
| M12 | Tidak ada test apa pun | §10 |

### Prinsip desain (dipakai untuk memutuskan semua trade-off)

1. **Satu sumber kebenaran scoring.** Eksak satu fungsi `score_and_classify()` melayani E/IE/AE/search/fallback. Divergensi label sengaja diseragamkan.
2. **Determinisme & auditability.** Input segmen + config bahasa → output identik, byte-for-byte, di semua engine. Bisa dibandingkan vs baseline.
3. **Degradasi anggun tanpa dependency.** Inti (exact+kode sederhana) harus jalan pure-stdlib. RapidFuzz/symspellpy opsional, terdeteksi runtime, fallback `difflib.SequenceMatcher`.
4. **Kompatibel Termux/ARM64.** Utamakan wheel musllinux aarch64; sediakan jalur pure-Python. Lazy import dependency berat; jangan import di startup.
5. **Satu pass per segmen.** Prefilter, klasifikasi, dan kandidat fuzzy digabung sekali jalan; regex dikompilasi sekali per bahasa.
6. **Bahasa = data, bukan kode.** Varian keyword dihasilkan programatik dari kata inti; kode tidak tahu bahasa selain dari tabel deklaratif.
7. **Perubahan perilaku harus eksplisit.** Setiap beda vs baseline spec-current diberi label TERIMA / PERBAIKAN / WAJIB-SAMA.
8. **Fase dapat diverifikasi.** Tiap fase punya *definition of done* yang bisa dijalankan di Termux nyata.

---

## 2. Peta Modul Target

Paket baru `cs_core/` (pure library, tanpa `rich`, tanpa I/O terminal) + engine lama jadi konsumen tipis.

```
cs_core/
  __init__.py
  text.py            # normalisasi, tokenisasi ringan, unicode fold, segmen dedup
  tokens.py          # ekstraksi token + index posisi, sekali per segmen
  languages/
    __init__.py      # registry bahasa, load deklaratif
    base.py          # dataclass LanguageSpec, KeywordCore, TierWeights
    id.yaml          # (atau .py dict) deklarasi kata inti Indonesia
    en.yaml
    jp.yaml
    kr.yaml
    in.yaml
    th.yaml
    variants.py      # generator varian (regex/romanisasi/fonetik)
  matching.py        # matcher berlapis: exact -> fuzzy -> phonetic, kandidat & skor
  scoring.py         # SATU implementasi scoring + clustering + kasta
  transcript.py      # fetch (platfrom-agnostic), parse VTT streaming, cache gzip
  cache.py           # gzip JSONL store, key, TTL, invalidation
  report.py          # HTML + Discord tunggal (konsumen struktur hasil)
  compat.py          # shim: hasil baru -> skema dict lama (hits/tiers/tier_counts/...)
  cli.py             # entry baru opsional: cs20 search/analyze/index/age
  diagnostics.py     # log ringan, timing, fallback-probe, no rich
```

### Tanggung jawab per modul

| Modul | Peran | Batas (tidak boleh) |
|---|---|---|
| `cs_core.text` | Normalisasi tunggal: strip, NFC, fold case untuk script Latin, buang punctuation berbahaya, jaga CJK/Devanagari/Telugu utuh | Tidak tahu keyword/scoring |
| `cs_core.tokens` | Satu pass: token list + offset, lowercase-folded, raw | Tidak compile regex bahasa |
| `cs_core.matching` | Lapisan exact/fuzzy/phonetic, threshold, whitelist/negatif konteks | Tidak menghitung skor agregat, tidak tahu cluster |
| `cs_core.scoring` | `score_segments()` → `AnalysisResult` (hits, tier_counts, score, persentase, clusters, kasta, `is_valid`) | Tidak menyentuh fetch/HTML |
| `cs_core.transcript` | `get_segments(source)` dari API/VTT/JSON index, lewat cache | Tidak scoring |
| `cs_core.cache` | `read(video_id, lang)`, `write(...)`, TTL, atomic | Tidak tahu semantik kata |
| `cs_core.report` | `build_html(result, meta)`, `send_discord(...)` | Tidak menghitung skor |
| `cs_core.compat` | Konversi `AnalysisResult` → dict skema lama + label kasta lama bila diminta | Tidak logika baru |
| `cs_core.languages` | Deklarasi bahasa + generator varian | Tidak tahu channel/IO |
| `cs_core.cli` | Orkestrasi: parse argumen, pilih sumber, panggil core, cetak | Tidak implementasi matching |

### Engine lama → peran baru

| File lama | Perubahan | Peran baru |
|---|---|---|
| `cs20_engine.py` | Kuruskan: fetch+orkestrasi rich+HTML/Discord **delegasi** ke `cs_core`. `analyze_video` jadi wrapper `transcript.get_segments` → `scoring.score_segments` → `compat.to_legacy`. | CLI live/semi-pasif (tetap) |
| `cs20_index_engine.py` | Hapus salinan scoring/classify; panggil `cs_core`. Hapus dead import `_av` (spec §6.2 #8). | CLI index batch (tetap) |
| `cs20_index_parser.py` | VTT parse & search delegasi ke `cs_core.transcript` + `cs_core.matching` (mode manual search). | CLI index downloader/search |
| `cs20_age_engine.py` | `_load_fuzzy_engine` → `cs_core.languages.load(lang)`; `_analyze_segments` → `cs_core.scoring`. | CLI bypass age-restricted (tetap) |
| `cs20_autodrive_engine.py` | Pakai `cs_core.transcript.fetch` + `ping_check` lewat cache (ping dari cache saat offline). | Discovery otomatis |
| `chatseeker.py` | Adopsi `cs_core.matching` untuk `_KW_*`; cache live-chat gzip opsional. | Engine live-chat |

**Catatan**: modul lama TIDAK dihapus di fase awal. `cs_core` berdampingan; engine lama di-refactor bertahap (lihat §8).

---

## 3. Rancangan Anti-Typo Berlapis

Tujuan: tahan misshear ASR (cegukan→jegukan/segukan/cekukan, kata terbelah, homofon) tanpa banjir FP. Tiga lapis; lapis mahal hanya jalan untuk **kandidat** dari lapis murah.

### 3.1 Urutan evaluasi per segmen (single pass)

```
for seg in segments:
    text = text.normalize(seg)              # cs_core.text
    toks = tokens.extract(text)             # sekali; lowercase-folded + offset
    tier_hits = {}

    for tier, kwset in language.active_tiers:   # loop dengan short-circuit
        tier_hits[tier] = 0

    # L1 EXACT/REGEX  (cepat, wajib)
    for tier, rules in lang.exact_rules:
        n = count_rule_hits(toks, rules, text)
        if n: tier_hits[tier] += n

    # L2 FUZZY TOKEN (hanya bila L1 tidak menutup tier ini)
    for tier in lang.fuzzy_tiers:
        if tier_hits[tier] > 0: continue
        for tok in toks.values:
            key = tok.norm_key                   # folded + collapse dobel
            if key in lang.fuzzy_skip:           # blacklist/whitelist cepat
                continue
            cand = lang.fuzzy_index.get_prefix(key[:lang.fuzzy_prefix])
            if cand and rapidfuzz_ratio(key, cand) >= lang.fuzzy_threshold[tier]:
                tier_hits[tier] += 1

    # L3 PHONETIC RULES (hanya untuk script Latin, hanya bila L1+L2 kosong utk tier)
    for tier in lang.phonetic_tiers:
        if tier_hits[tier] > 0: continue
        if not lang.script_is_latin: continue     # non-Latin lewat romanisasi, bukan fonetik
        key = phonetic_id(tok.norm_key)
        if key in lang.phonetic_map:
            tier_hits[tier] += 1
```

### 3.2 Lapis & ambang (konkret)

| Lapis | Fungsi | Algoritma | Biaya | Kapan aktif |
|---|---|---|---|---|
| **L0 Prefilter** | `combined_prefilter.search(full_text)` | 1 regex gabungan `exact_rules` + `fuzzy_anchors` | O(n) sekali per video | Selalu, sebelum loop |
| **L1 Exact/regex** | `count_rule_hits()` | regex terkompilasi sekali | murah | Setiap segmen |
| **L2 Fuzzy token** | `fuzzy_match_token(key, cand)` | `rapidfuzz.process.extractOne` / `difflib.SequenceMatcher.ratio` fallback | sedang | Hanya token yang tak match exact; dibatasi panjang & kandidat |
| **L3 Phonetic-rule** | `phonetic_key(word)` | rule table per-script → kunci kanonik, bandingkan set | murah | Hanya script Latin, hanya bila L1+L2 gagal untuk tier |
| **L4 Word-segmentation** | `WordSegmentation.segment(text)` | symspellpy (opsional) / wordninja fallback | mahal | Hanya untuk teks tanpa spasi masuk akal (kata menyatu) / kandidat `fuzzy_anchors` |

### 3.3 Strategi anti-false-positive

1. **FP tier eksplisit** (baseline sudah punya; dipertahankan). Match FP tetap dihitung bobot 1 tapi **tidak menaikkan CORE_HITS** → kasta tetap rendah.
2. **Negative context window.** Untuk tiap match fuzzy, cek ±2 token sekitar untuk daftar `neg_context` bahasa (mis. en: `economic|minor|technical` sebelum kata; id: `jangan|bukan` sebagai penanda hipotetis). Bila kena → turunkan tier satu tingkat (CORE→TYPO) atau tandai `suppressed: true`.
3. **Whitelist vs blacklist.** `fuzzy_skip` = kata umum yang mirip secara edit-distance tapi bukan target (mis. id: `cekukan` valid vs `cekukan-dalam-konteks-lain`; en: `hick` vs `hic`). Dideklarasikan per bahasa.
4. **Ambang per-tier**: CORE lebih ketat (mis. ratio ≥ 0.88), TYPO lebih longgar (≥ 0.78) tapi bobot lebih rendah → tidak cukup menembus kasta tinggi tanpa CORE.
5. **Gerbang CORE** tetap: `CORE_HITS == 0 → AMBIGU` (baseline §5 #1). Ini penahan FP terkuat — FP murni tidak akan pernah jadi VALID.
6. **Cap kontribusi fuzzy per video.** `fuzzy_hits_cap` (mis. 8) per tier per video; lebih dari itu dianggap sinyal artefak ASR global, hit tambahan didemosi ke FP count.

### 3.4 Tidak dipakai (keputusan sadar)

- **Phonetic Inggris (Soundex/Metaphone/NYSIIS, jellyfish)** untuk non-Latin: ditolak. Riset sudah menyatakan tidak berlaku untuk ID/JP/KR/HI/TH. Untuk JP/KR/HI/TH/Te pakai exact regex (baseline) + romanisasi untuk TYPO Latin (mis. `hiccup`/`hichki`).
- **symspellpy penuh** sebagai wajib: jadikan opsional (L4). Dua dictionary besar = memori; Termux resource terbatas. Fallback `wordninja` atau `difflib`+split heuristik.

### 3.5 Tabel fonetik Indonesia (kecil, deklaratif — contoh tidak mengikat)

```
c/j/s -> s          # cegukan, jegukan, segukan
k/g   -> g
b/p   -> p
d/t   -> t
ng/n/nk -> n
ai/ei -> e
u/o   -> o
hilang huruf dobel   # shakkuri -> shakuri (untuk Latin di script non-Latin)
```

`phonetic_key("jegukan") == phonetic_key("cegukan") == "sogokan"` (setelah mapping). Ini menggantikan pola regex `ce+g+[uo]+k+...` yang over-fit.

---

## 4. Rancangan Generator Varian Keyword

### 4.1 Deklarasi kata inti (ringkas, per bahasa)

Bukan daftar regex. Bentuk deklaratif:

```yaml
# cs_core/languages/id.yaml
script: latin
romanizable: false
tiers:
  CORE:
    weight: 5
    core_forms: [cegukan, cekukan, jegukan, kecegukan, segukan]
    variants: [auto_typo, phonetic_id]
    compounds: ["*hik*", "*hic*", "*ngik*"]
  TYPO:
    weight: 4
    core_forms: [jegukan, cekukan, cukukan, jegugan]
    variants: [auto_typo]
    context_forms: ["aduh *","duh *","kok *","lagi *","masih *"]
  SILENT:
    weight: 4
    patterns:                      # hanya yang benar-benar perlu struktur frasa
      - "{CORE} (dari tadi|terus|mulu|melulu|lagi)"
      - "(ga|gak|tidak|nggak) (ilang|hilang).*{CORE}"
  CONTEXT:
    weight: 2
    core_forms: [tersedak, kesedak]
  FP:
    weight: 1
    core_forms: [nyendawa, sendawa, sesegukan]
    neg_context: [ekonomi, minor, kecil, sementara]
neg_context_global: [jangan, bukan, kayak, misal, contoh]
```

### 4.2 Cara generate varian → regex

`cs_core.languages.variants` menyediakan:

| Generator | Input | Output |
|---|---|---|
| `auto_typo(form)` | kata inti | substitusi karakter umum (c↔k↔j, u↔o, e↔a, dobel huruf, transposisi) → set varian |
| `phonetic_id(form)` | kata Latin | bentuk ekuivalen berdasarkan rule table §3.5 |
| `romanize(form, script)` | JP/KR/HI/Th | romanisasi sederhana (kana→romaji map, hangul→RR map, devanagari→IAST) untuk menangkap TYPO Latin |
| `build_regex(forms, tier)` | set varian | satu alternasi `(?:form1|form2|...)` dengan boundary sesuai script |
| `build_phonetic_set(forms)` | set varian | set `phonetic_key` untuk lookup L3 |

**Kunci efisiensi**: semua regex per bahasa dikompilasi **sekali** di `language.compile()`; hasil di-cache di objek `LanguageSpec` (bukan global mutable seperti `_init_lang`). `combined_prefilter` = gabungan L1+CORE anchors, juga sekali.

### 4.3 Penanganan non-Latin (JP/KR/HI/Th/Te)

- **Tidak** pakai generator fonetik Inggris. Gunakan:
  - **Exact forms** apa adanya (`しゃっくり`, `딸꾹질`, `हिचकी`, `สะอึก`).
  - **Romanisasi** untuk bentuk Latin TYPO (`shakkuri`, `ttalkkukjil`, `hichki`, `sauek`) via map statis per-script.
  - **Auto-typo pada bentuk Latin** yang diromanisasi (dobel konsonan, vokal).
- Kode bahasa tidak peduli aksara; `LanguageSpec.script` menentukan jalur (latin → L3 phonetic; non-latin → L2 fuzzy hanya untuk token Latin hasil romanisasi).
- Varian aksara ambigu (mis. `シャックリ` vs `シャッくり`): deklarasi beberapa `core_forms`, atau generator `kana_variants()` yang mengganti katakana/hiragana setara.

### 4.4 Merge `in` + `te`

Baseline menggabungkan tier `in`+`te` runtime (spec §2.5). Di arsitektur baru: `language: "in"` punya field `include_scripts: [devanagari, telugu]`; `te` TIDAK lagi bahasa terpisah di menu (koreksi bug spec §2.7/Open Q#7) — atau tetap ada tapi dengan `TRANSCRIPT_LANGS` benar (`te→[te,te-IN,hi]`). Keputusan: **pertahankan `te` internal + perbaiki map transcript** (label perbaikan diterima).

---

## 5. Rancangan Efisiensi

### 5.1 Target metrik

| Metrik | Baseline | Target |
|---|---|---|
| Scan per segmen | 2 pass (`ALL_PATTERNS` + `classify_text`), M×N regex | 1 pass; prefilter hanya 1 regex, klasifikasi 1 loop, fuzzy hanya kandidat |
| Kompilasi regex | per `_init_lang` (per proses engine) | sekali per `LanguageSpec`; di-cache di disk (pickle/`re` tak bisa pickle, cache sumber saja) |
| Alokasi VTT | baca file penuh → list → buang | streaming baris, segment dict, commit ke cache lalu buang |
| Fetch ulang | selalu fetch tiap analisis | cache hit tanpa network |
| RAM puncak / video | O(seluruh VTT + segments) | O(segments) + buffer baris; VTT mentah tidak disimpan |
| CPU skor | 3 salinan | 1 fungsi |

### 5.2 Teknik

1. **Single-pass scanning**: `tokens.extract()` menghasilkan token + offset sekali. Prefilter `combined_prefilter.search(text)` pakai teks yang sudah di-normalisasi (hindari normalisasi ulang). Loop tier pakai short-circuit: tier yang sudah hit TIDAK di-scan fuzzy.
2. **Kompilasi sekali**: `LanguageSpec.compile()` di awal orkestrasi, disimpan di objek, di-inject ke `scoring.score_segments(lang=spec)`. Hapus global mutable `KEYWORD_TIERS/COMPILED_TIERS/ALL_PATTERNS_COMBINED` yang bikin race di ThreadPool.
3. **Lazy VTT streaming**: `transcript.parse_vtt_file(path)` baca baris via iterator, collapse by timestamp pakai dict `{sec: text}`, tidak menyimpan seluruh file.
4. **RapidFuzz vs difflib**:
   - `matching.py` probe sekali: `try: import rapidfuzz` → `HAVE_RAPIDFUZZ`.
   - Bila ada: `rapidfuzz.process.extractOne(key, lang.fuzzy_candidates, scorer=fuzz.ratio, score_cutoff=thr)`. `extractOne` mengembalikan `None` cepat bila di bawah cutoff.
   - Fallback: `difflib.SequenceMatcher(None, a, b).ratio()` dengan **prefilter panjang** (`abs(len(a)-len(b)) <= max_edit`) supaya tidak O(n²) liar.
   - Koreksi: riset menyebut `process.cdist`; di Termux pakai `extractOne` per token (bukan cdist matriks) karena jumlah kandidat kecil.
5. **Cache regex & phonetic key**: `functools.lru_cache(maxsize=4096)` untuk `phonetic_key(word)` dan `auto_typo(form)`.
6. **Batch skor**: hitung `tier_hits` sebagai dict int kecil; hindari dict-of-dict per segmen (flat keys `"CORE"`, dst.) seperti baseline.

### 5.3 Di mana RapidFuzz/difflib dipakai (batas tegas)

| Lokasi | Pemakaian | Fallback |
|---|---|---|
| `matching.fuzzy_match_token` | kandidat token vs forms | difflib ratio + length gate |
| `matching.rank_clusters` (opsional) | ringkasan teks | tidak ada — pure aritmetika |
| **Bukan** di prefilter | prefilter tetap regex exact | — |
| **Bukan** di scoring agregat | scoring murni aritmetika (baseline) | — |

---

## 6. Rancangan Cache Transcript

### 6.1 Lokasi & format

- **Root cache** mengikuti `detect_cache_root()` existing (`~/storage/shared/CS20_Index` bila ada, fallback `~/.cs20/index_cache`). Tambah subdir `transcripts/`.
- **File**: `transcripts/{video_id}.{lang}.jsonl.gz`
- **Format**: **gzip JSONL**, satu baris per segmen:
  ```
  {"v":1,"id":"abc123","lang":"id","source":"yt-api","fetched_at":1690000000,"seg":{"sec":12,"text":"..."}}
  ```
  Baris pertama = **header meta** (`{"_meta":...}`). Baris berikut = segmen. JSONL memungkinkan streaming read tanpa load penuh.
- **Alternatif dipertimbangkan**: single JSON gzip. Ditolak — JSONL bisa append/streaming & tahan file rusak parsial.

### 6.2 Key & invalidation

- **Key**: `(video_id, lang)` di nama file. Lang = kode bahasa normalisasi (`id`, `en`, `ja`, `ko`, `hi`, `te`, `th`), bukan kode transcript mentah (`id-ID` → `id`) — supaya `id`/`id-ID` berbagi cache.
- **Header menyimpan** `source` (yt-api/vtt/index), `lang_requested` (list asli), versi format `v`.
- **TTL**: default 30 hari (`CACHE_TTL_DAYS`, dapat dikonfigurasi via CLI/env). Transkrip YouTube stabil; TTL panjang aman.
- **Invalidasi manual**: `cs20 cache purge --video`, `--channel`, `--all`; `--max-age`.
- **Invalidasi versi format**: `v` di header ≠ `CACHE_FORMAT_VERSION` → anggap miss, tulis ulang.
- **Atomic write**: tulis `.tmp` → `os.replace` (sudah pola `save_json_safe` di parser; pakai itu).
- **GC**: sapu file > TTL saat startup (opsional, lazily) atau via `cs20 cache gc`.

### 6.3 Integrasi engine

- `transcript.get_segments(video_id, lang, source_hint)`:
  1. `cache.read(video_id, lang)` → hit: return segmen + `cache_status="hit"`.
  2. miss: fetch sesuai `source_hint` (`api` / `ytdlp-vtt` / `index-json`) → `cache.write` → return.
- Engine lama memanggil satu fungsi ini; urutan fetch yang kompleks (cookies → UA rotation → fallback) tetap di dalam `transcript.fetch_api()` tapi hasilnya selalu lewat cache.
- `_current_blocked_log` / rate-limit tetap di engine (bukan cache) karena terkait kebijakan runtime.
- `ping_check` autodrive boleh baca cache sebagai bukti "akses masih normal" bila offline (opsional, fase lanjut).

---

## 7. Strategi Migrasi & Kompatibilitas

### 7.1 Prinsip migrasi

- **Strangler fig**: `cs_core` dibangun dan diuji dengan golden test; engine lama dipindahkan fungsi-per-fungsi, bukan big-bang.
- **Shim `compat.to_legacy(result)`**: engine lama tetap menerima dict dengan field yang sama (`hits`, `tiers`, `tier_counts`, `score`, `persentase`, `cluster_count`, `maraton_mins`, `is_valid`, `kasta`, `kasta_label`, `html_rows`). Jadi kode hilir (HTML/Discord/status.json) tidak berubah sampai siap.
- **Flag perilaku**: `cs_core.config.CompatMode` (`BASELINE` | `IMPROVED`). Default awal = `BASELINE` agar hasil identik baseline spec-current saat uji regresi; setelah validasi user, default `IMPROVED`.

### 7.2 Perilaku WAJIB-SAMA (tidak boleh berubah)

Dari spec-current §3–§5:

- Bobot tier: CORE=5, TYPO=4, SILENT=4, CONTEXT=2, FP=1.
- `c_density_bonus = min(10, (c_hits // c_dur_min) * 2)` — **int div dulu**.
- `c_silent_bonus = 15` bila ada SILENT.
- `MARATON_MINS = max(c_dur_min)`.
- `VALID_CLUSTERS` = cluster dengan `c_core >= 2`.
- Multi-cluster bonus pakai `clusters_with_core` (CORE ≥1), `20 × (n-1)`.
- `PERSENTASE = min(100, GLOBAL_SCORE*100 // 60)`.
- Cluster gap: `>180→3600`, `>60→1800`, else `1200`; `total_duration_min` dari span hit (BUKAN durasi video).
- Urutan kasta & threshold: AMBIGU(0 CORE) → GOD_MODE(maraton ∧ pct≥60) → VALID_HIGH multisisi(pct≥60) → SILENT(HAS_SILENT ∧ CORE≥1, pct=max(pct,75)) → VALID_HIGH(core≥3 ∧ pct≥60) → VALID(core≥1 ∧ pct≥40) → LOW(core≥1) → else.
- `IS_MARATON = len(clusters)==1 ∧ MARATON_MINS≥30 ∧ GLOBAL_SCORE≥8`.
- Suffix label `| {n} cluster, {n} hit`.
- Rumus chatseeker `_score_file` & threshold level (bila chatseeker di-refactor, pertahankan rumus).

### 7.3 Perbedaan DITERIMA sebagai perbaikan

| # | Beda | Alasan |
|---|---|---|
| P1 | Hapus double-scan (`ALL_PATTERNS` + `classify_text`) jadi 1 pass | M2; tidak mengubah hasil |
| P2 | Satu scoring menggantikan 3 salinan; label kasta diseragamkan (ae & index kini menyertakan "(0 Hit Core)"/"NON-STOP"/"SESI KAMBUHAN" seperti E) | M1, §6.1; perbedaan label tidak memengaruhi skor; konsumen label jadi konsisten |
| P3 | Hapus dead code kasta #8 `else` | §5, Open Q#5; tidak terjangkau |
| P4 | Tidak ada `(?!)` di tier baru; tier kosong benar-benar kosong | §2; `tier_counts` tetap punya key (nilai 0) untuk kompat output |
| P5 | Highlight HTML: ganti `pat.sub` bertingkat → token-span build sekali, hilangkan nested span | M8, Open Q#6; perbaikan kualitas HTML |
| P6 | Field waktu distandarkan (`sec`), E tak lagi `int(seg["start"])`; adapter fetch menormalkan `start`→`sec` | §6.2 #2 |
| P7 | `_analyze_fallback` dihapus; pengganti = `LanguageSpec` minimal + flag `degraded=true` di hasil | M11, Open Q#10; caller tahu mode fallback |
| P8 | Dedup `abs(sec-last)<1` didokumentasikan sebagai `==0` (int) atau diubah ke float berbasis durasi asli bila sumber punya | §1.3, Open Q#3; keputusan: **pertahankan int ==0** + komentar |
| P9 | `te` map transcript diperbaiki (`te→[te,te-IN,hi]`) | §2.7/Open Q#7 |
| P10 | Varian keyword digenerate; kamus regex manual dipensiunkan | M5, M6 |
| P11 | Cache transcript gzip | M4 |

### 7.4 Perbedaan yang HARUS dikonfirmasi user sebelum aktif

- P2 (label seragam) — ubah tampilan; default `BASELINE` agar tidak mengejutkan.
- P5 (highlight) — ubah HTML; default `BASELINE` (highlight lama) atau `IMPROVED` (span bersih), flag.
- P8 (dedup float) — mengubah HIT_LIST untuk sumber ber-float.
- Clustering span-hit (M9/Open Q#4): **tetap baseline**; perbaikan ke durasi video ditawarkan sebagai flag `CLUSTER_MODE=hit_span|video_duration`, default `hit_span`.
- Chatseeker keyword authority (Open Q#8): **tetap** dua definisi; refactor hanya menyatukan implementasi, bukan mengubah rumus.

---

## 8. Risiko & Trade-off

| Risiko | Dampak | Mitigasi |
|---|---|---|
| RapidFuzz gagal install di Termux (tak ada wheel) | L2 fuzzy mati | fallback `difflib` + length gate; `diagnostics.fallback_status()` dilaporkan di HTML/CLI |
| symspellpy/wordninja memori besar | OOM HP | jadikan opsional L4, hanya aktif bila `--word-segment` & teks kandidat; tidak di default |
| Penambahan dependency bertabrakan `--break-system-packages` | environment rusak | dokumentasikan `pip install --break-system-packages`; sediakan `requirements-termux.txt` + `requirements-min.txt` (stdlib-only) |
| Refactor mengubah hasil tak sengaja | kehilangan momen valid | `CompatMode=BASELINE` + golden test dari spec §3–§5 |
| Cache basi tx transcript diperbarui YouTube | miss momen baru | TTL 30d + `cache purge`; `force_refresh` flag |
| gzip CPU overhead di ARM lemah | lambat untuk file kecil | gzip level 1 (`compresslevel=1`) kompromi kecepatan/ukuran |
| Global mutable hilang → threading bug | race di ThreadPool | `LanguageSpec` immutable, di-pass eksplisit; hilangkan `_init_lang` global |
| VTT collapse "teks terpanjang" beda antar sumber | hasil E≠IE≠AE | normalkan semua sumber ke `{sec,text}` via adapter; dokumentasikan |
| Romanisasi JP/KR/HI tak sempurna | TYPO non-Latin tetap meleset | exact forms tetap jalur utama; romanisasi hanya bonus, tidak menurunkan presisi CORE |
| Dependency `re` kompleks (lookbehind) di pattern | error compile | `LanguageSpec.compile()` tangkap `re.error`, log, lanjut (perilaku baseline) |

**Trade-off utama**: memisahkan `cs_core/` + file engine tipis = lebih banyak file, tapi menghapus 3 salinan scoring/HTML dan membuat anti-typo teruji. Diterima karena skala perubahan sudah BESAR dan tidak ada test saat ini — modularitas justru syarat untuk menambah test.

---

## 9. Testing Implications

Repo belum punya test (spec §10). Strategi:

1. **Golden test baseline** (fase 0): rekam input segmen → output dict dari `analyze_video`/`_analyze_from_segments`/`_analyze_segments` versi lama untuk beberapa video nyata + kasus sintetis. Simpan sebagai fixture JSON. Tes baru: `cs_core` dalam `BASELINE` mode harus menghasilkan output identik (kecuali field yang sengaja beda bila flag).
2. **Property test scoring**: `scoring.score_segments` deterministik; jalankan 1000 segmen acak, cek invariants (PERSENTASE ≤ 100, `is_valid ⇒ CORE_HITS>0`, dll).
3. **Anti-typo test**: tabel pasangan `(teks, expected_tier)` untuk cegukan/jegukan/segukan/cekukan, hiccup/hicup/hickup, しゃっくり/シャクリ, 딸꾹질/딸각, plus kasus FP (`nyendawa`, `economic hiccup`).
4. **Cache test**: write → read round-trip; TTL; format version mismatch; atomic replace; corrupt JSONL di-skip.
5. **Fallback test**: simulasi RapidFuzz/symspellpy tidak ada → hasil tetap berjalan, `degraded=true` ter-set.
6. **Efisiensi test**: hitung regex `search` call via monkeypatch counter; assert ≤ jumlah pattern unik per segmen (regresi M2/M3).
7. **CLI smoke test**: `cs20 analyze --video <id> --cache-dir tmp` tanpa network (pakai fixture).
8. Test runner: `pytest` (tersedia Termux, pure Python). Tidak ada framework lain.

---

## 10. Urutan Implementasi Bertahap

### Fase 0 — Baseline beku & golden fixtures
- **Kerja**: baca 5 engine; rekam output nyata untuk N video tiap engine; tulis fixture + skrip pembanding. Tidak mengubah kode.
- **DoD**: `tests/fixtures/*.json` ada; skrip `tools/baseline_compare.py` (pseudocode) mendeteksi diff.

### Fase 1 — `cs_core` tulang: text, tokens, scoring
- **Kerja**: implement `text.normalize`, `tokens.extract`, `matching` L1-exact, `scoring.score_segments` + cluster + kasta identik baseline. Belum ada fuzzy.
- **DoD**: golden test scoring lolos (BASELINE mode); property test lolos.

### Fase 2 — Bahasa deklaratif & generator varian
- **Kerja**: `languages/*` YAML + `variants.py`; hasilkan forms yang setara/menutup pattern manual baseline untuk `id`,`en`,`jp`,`kr`,`in`,`th`,`te`. Hapus ketergantungan `(?!)`.
- **DoD**: test anti-typo tabel `(teks→expected_tier)` lolos; diff forms vs regex lama dilaporkan (tidak boleh kehilangan form CORE).

### Fase 3 — Fuzzy & phonetic berlapis
- **Kerja**: `matching` L2/L3; probe RapidFuzz; fallback difflib; neg_context; cap fuzzy.
- **DoD**: test FP (nyendawa, economic hiccup) tetap non-VALID; test typo ASR lolos; `diagnostics.fallback_status()` benar.

### Fase 4 — Transcript + cache gzip
- **Kerja**: `transcript.py` (fetch api/vtt/index), `cache.py` gzip JSONL; engine pakai fungsi ini.
- **DoD**: cache hit tanpa network (tes mock); round-trip; TTL; VTT streaming tidak load penuh.

### Fase 5 — Migrasi engine (strangler)
- Urut: `cs20_age_engine` → `cs20_index_engine` → `cs20_index_parser` → `cs20_engine` → `chatseeker`.
- Tiap engine: hapus salinan scoring/classify, pakai `cs_core` + `compat.to_legacy`.
- **DoD**: golden test per engine dalam BASELINE mode identik; tidak ada import `cs20_engine.analyze_video` dead.
- **Stop point**: di sini user bisa uji channel nyata dengan `CompatMode=BASELINE`.

### Fase 6 — `report.py` tunggal + `CompatMode=IMPROVED`
- **Kerja**: satukan build_html/send_discord; highlight span bersih; flag mode.
- **DoD**: HTML E/IE/AE identik untuk input sama; highlight tidak nested.

### Fase 7 — CLI baru, cleanup dependency, dokumentasi Termux
- **Kerja**: `cs_core/cli.py` (`search/analyze/index/age/cache`); `requirements-*.txt`; README Termux; hapus dead code; `cs20.sh` update bila perlu.
- **DoD**: instalasi bersih di Termux ARM64 (atau venv simulasi) jalan; semua test lolos; docs diperbarui.

### Fase 8 — Optimasi lanjut (opsional)
- symspellpy L4, romanisasi penuh, GC cache terjadwal, cluster mode video_duration.
- **DoD**: metrik efisiensi §5.1 terpenuhi; tidak ada regresi golden.

---

## 11. Keputusan Arsitektur Kunci (ringkas)

1. Paket `cs_core/` pure-Python tanpa terminal; engine lama jadi konsumen tipis — satu sumber scoring/HTML.
2. `scoring.py` mempertahankan **rumus baseline byte-for-byte** (int-div, cap 60, kasta berurutan) — `CompatMode=BASELINE` default agar bisa dibandingkan.
3. Anti-typo berlapis L0 prefilter → L1 exact → L2 fuzzy token → L3 phonetic-rule → L4 word-segmentation; tiap lapis hanya untuk kandidat.
4. Phonetic Inggris (jellyfish) ditolak untuk non-Latin; ID pakai rule-table kecil, non-Latin pakai exact + romanisasi.
5. Keyword = data deklaratif per bahasa + generator varian (`auto_typo`, `phonetic_id`, `romanize`); regex dikompilasi sekali.
6. Single-pass scanning + hapus global mutable `_init_lang`; `LanguageSpec` immutable di-inject eksplisit (aman ThreadPool).
7. Cache transcript gzip JSONL `transcripts/{video_id}.{lang}.jsonl.gz`, TTL 30d, atomic write, key dinormalisasi.
8. RapidFuzz opsional dengan fallback difflib+length-gate; symspellpy/wordninja L4 opsional; jalur stdlib selalu hidup.
9. Migrasi strangler per engine dengan `compat.to_legacy`; perbedaan P1–P11 dilabeli, yang mengubah tampilan menunggu konfirmasi user.
10. Test pertama = golden baseline dari spec-current; tanpa itu refactor tidak boleh lanjut ke `IMPROVED`.
