# Cegukan Seeker — Spesifikasi Perilaku AKTUAL (baseline refactor)

> Rekonstruksi dari kode pada commit saat ini. **Hanya mendeskripsikan kondisi sekarang** — bukan rekomendasi.
> Referensi baris: `cs20_engine.py` (E), `cs20_index_engine.py` (IE), `cs20_age_engine.py` (AE), `cs20_index_parser.py` (P), `chatseeker.py` (CS).

---

## 1. Preprocessing Transcript

### 1.1 Sumber segmen

| Jalur | Sumber | Format segmen | Referensi |
|---|---|---|---|
| Live/semi pasif | `youtube-transcript-api` `api.fetch(video_id, languages=TRANSCRIPT_LANGS)` → `.to_raw_data()` | `[{text, start, duration}, ...]`, `start` float sec | E626–661, E704 |
| Index mode | yt-dlp `--write-auto-subs --sub-format vtt` → file VTT → `parse_vtt_content` | `[{sec, text}, ...]`, `sec` int | P89–131, P260–330 |
| Age-restricted | yt-dlp + `--cookies` → VTT → `_parse_vtt` | `[{sec, text}, ...]`, `sec` int | AE133–156, AE920–934 |

`TRANSCRIPT_LANGS` di-set oleh `_init_lang()` (E424–436), map `lang → daftar kode bahasa` (E428–435):
`id→[id,en,id-ID]`, `en→[en,en-US,en-GB]`, `jp→[ja,ja-JP]`, `kr→[ko,ko-KR]`, `in→[hi,hi-IN,te,te-IN]`, `th→[th,th-TH]`. Default `[id,en,id-ID]` bila lang tak dikenal (E436).

### 1.2 Normalisasi

- **E**: tidak ada normalisasi case pada teks. `text = seg.get("text","").strip()` (E804). `sec = int(seg.get("start",0))` (E805).
- **IE**: `text = seg.get("text","").strip()` (IE542); `start_sec = int(seg.get("sec",0))` (IE543).
- **AE**: `text = ...strip()` (AE561); `sec = int(seg.get("sec",0))` (AE562).
- Regex kompilasi memakai `re.IGNORECASE` (E459), jadi matching case-insensitive **hanya untuk pola Latin** — aksara CJK/Devanagari/Telugu tak terpengaruh.
- **VTT parse** strip semua HTML tag `<...>` via `_VTT_TAG_RE = <[^>]+>` — ini juga menghapus tag timestamp inline YouTube `[00:01:23.000]` (P79, P112; AE125, AE146).
- Tidak ada lowercasing, tidak ada Unicode normalization (NFC/NFD), tidak ada punctuation removal.

### 1.3 Dedup

Dua lapis, dijalankan **berurutan** dalam loop segmen:

```
# (IE541-550, AE560-568, E803-816)
if not text or text == LAST_TEXT:          continue   # dedup teks identik berturut (persis sama)
if not ALL_PATTERNS.search(text):          continue   # prefilter keyword
if abs(start_sec - LAST_SEC) < 1:          continue   # dedup jarak < 1 detik
```

- `text == LAST_TEXT` → perbandingan **persis** (case-sensitive, sudah di-strip). Bukan substring.
- `abs(start_sec - LAST_SEC) < 1` → hanya menolak bila selisih **0** detik (start sama). Karena `start_sec`/`sec` adalah integer. Komentar "dalam 1 detik yang sama" (E814) menyesatkan: `< 1` pada int praktis `== 0`.
- `LAST_TEXT`/`LAST_SEC` **hanya** di-update saat hit lolos tersimpan (E837–838), bukan tiap segmen. Artinya segmen non-hit tidak me-reset penanda dedup.

### 1.4 VTT collapse duplikat timestamp

`parse_vtt_content` (P97–131) dan `_parse_vtt` (AE133–156): key = `start_sec`; untuk timestamp sama ambil **teks terpanjang** (`if len(combined) > len(existing)`). Hasil di-sort by `sec`.

### 1.5 Pre-check cepat

Sebelum loop per segmen: `full_text = " ".join(seg text)`; jika `ALL_PATTERNS_COMBINED.search(full_text)` gagal → langsung `no_match` (E790–795, IE518–520, AE542–544). `ALL_PATTERNS_COMBINED` dibangun dari keyword **non-`(?!)`** di semua tier (E468–476).

---

## 2. Tier Keyword

Tier per bahasa di `_ALL_KEYWORD_TIERS` (E86–417). Bobot seragam struktural: CORE=5, TYPO=4, SILENT=4, CONTEXT=2, FP=1.

> **Pattern `(?!)` = no-op.** Regex negative-lookahead yang selalu gagal → tier tsb. tak pernah match. Tier dengan hanya `(?!)` efektif kosong tapi tetap hadir di `tier_counts` (nilai selalu 0).

### 2.1 `id`

| Tier | Bobot | Patterns (verbatim) |
|---|---|---|
| CORE | 5 | `ce+g+[uo]+k+[ae]+n+`, `ce+g+[uo]+k+[ae]+n+nya`, `ce+g+[uo]+k+[ae]+n+ku`, `ce+c+e+g+[uo]+k+[ae]+n+`, `ce+k+[uo]+k+[ae]+n+`, `ce+k+[uo]+k+[ae]+n+nya`, `ce+k+[uo]+k+[ae]+n+ku`, `je+g+[uo]+k+[ae]+n+`, `ke+je+g+[uo]+k+[ae]+n+`, `ke+ce+g+[uo]+k+[ae]+n*`, `ce+g+[uo]+k+e+n+`, `ce+k+[uo]+k+e+n+`, `\*hi+k+\*`, `\*hi+c+\*`, `\*ngi+k+\*` |
| TYPO | 4 | `aduh\s*c[uo]+k+[ae]*n+`, `duh\s*c[uo]+k+[ae]*n+`, `kok\s*c[uo]+k+[ae]*n+`, `lagi\s*c[uo]+k+[ae]*n+`, `masih\s*c[uo]+k+[ae]*n+`, `\bcu+k+[uo]+k+[ae]+n+\b`, `(?<!se)se+g+[uo]+k+[ae]*n+\b`, `\bce+g+[uo]+[ae]*n+\b`, `\bce+k+[uo]+[ae]*n+\b`, `\bce+g+[uo]+k+\s+[ae]*n+\b`, `\bju+g+[uo]+k+[ae]*n+\b`, `\bce+k+[uo]+g+[ae]*n+\b`, `\bce+g+[uo]+g+[ae]*n+\b`, `\bje+g+[uo]+g+[ae]*n+\b`, `\bje+k+[uo]+g+[ae]*n+\b`, `\bc+e*b+u+k+a+n+\b`, `\bja+g+u+k+[ae]*n+\b`, `\bc+u+k+[ae]*n+\b` |
| SILENT | 4 | `ce+g+[uo]+k+[ae]*n+\s*(dari\s*tadi|terus|mulu|melulu|lagi)`, `(ga|gak|tidak|nggak)\s*(ilang|hilang)\s*[\w\s]*ce+g+[uo]+k+[ae]*n*`, `ce+g+[uo]+k+[ae]*n+\s*(ga|gak|nggak)\s*(ilang|hilang)`, `capek\s*ce+g+[uo]+k+[ae]*n*`, `ce+g+[uo]+k+[ae]*n+\s*ga\s*ilang` |
| CONTEXT | 2 | `te+rs+e+d+[ae]+k+`, `ke+s+e+d+[ae]+k+`, `(?<![a-zA-Z])ce+g+[uo]+k+(?![a-zA-Z])` |
| FP | 1 | `ny+e+nd+[ao]+w+[ao]*`, `se+nd+[ao]+w+[ao]*`, `\bhi+k+\b`, `\bse+se+g+[uo]+k+[ae]*n+\b` |

### 2.2 `en`

| Tier | Bobot | Patterns |
|---|---|---|
| CORE | 5 | `\bhiccup+s?\b`, `\bhiccu+p+s?\b`, `\*hic\*`, `\bhic+\b` |
| TYPO | 4 | `\bhicup+s?\b`, `\bhickup+s?\b`, `\bh[ie]ccup+s?\b`, `\bhic\s+cup+s?\b` |
| SILENT | 4 | `hiccup+s?\s*(won'?t|can'?t|don'?t|not)\s*(stop|go away)`, `(can'?t|won'?t)\s*(stop|get rid of)\s*(the\s*)?hiccup`, `hiccup+s?\s*(for|like)\s*(an?\s*)?(hour|minute|while)`, `still\s*(have|got)\s*(the\s*)?hiccup` |
| CONTEXT | 2 | `\bhiccough+s?\b` |
| FP | 1 | `(economic|minor|small|little|technical|temporary)\s*hiccup+s?`, `hiccup+s?\s*(in|with|for)\s*(the|our|my|their)\s*\w+` |

### 2.3 `jp`

| Tier | Bobot | Patterns |
|---|---|---|
| CORE | 5 | `しゃっくり`, `シャックリ`, `シャッくり`, `しゃッくり`, `吃逆`, `しゃっ\s*くり`, `シャッ\s*クリ` |
| TYPO | 4 | `しゃくり`, `シャクリ`, `ひゃっくり`, `ヒャックリ`, `ヒック`, `ひっく`, `吃\s*逆` |
| SILENT | 4 | `しゃっくりが止まら`, `シャックリが止まら`, `しゃっくり.*止まらない`, `しゃっくり.*続く`, `しゃっくり.*止め` |
| CONTEXT | 2 | `(?!)` ← **no-op** |
| FP | 1 | `びっくり`, `ビックリ` |

### 2.4 `kr`

| Tier | Bobot | Patterns |
|---|---|---|
| CORE | 5 | `딸꾹질`, `딸꾹`, `딸각`, `딸깍`, `딸구질`, `딸국` |
| TYPO | 4 | `\[딸꾹\]`, `\[딸깍\]`, `사레`, `사레들`, `캑캑`, `컥컥` |
| SILENT | 4 | `딸꾹질이 안`, `딸꾹질 계속`, `딸꾹질 멈추`, `멈추질 않`, `딸꾹질 때문에` |
| CONTEXT | 2 | `트림`, `거억`, `꺼억`, `끄억`, `\[트림\]` |
| FP | 1 | `(?!)` ← **no-op** |

### 2.5 `in` (Hindi + Telugu di-merge)

`_init_lang("in")` menggabungkan pattern `in` + `te` per tier, dedupe via `dict.fromkeys` urutan terjaga (E443–452). Bobot diambil dari `in`.

| Tier | Bobot | Patterns (in, E300–338) | Patterns ditambah dari `te` (E375–416) |
|---|---|---|---|
| CORE | 5 | `हिचकी`, `\bhiccup\b`, `\bhichki\b` | `ఎక్కిళ్లు`, `ఎక్కిళ్ళు`, `ఎక్కిలి`, `\bekkillu\b`, `\bekkili\b` |
| TYPO | 4 | `इचकी`, `हिचकि`, `\bhicup\b`, `\bh[ae]cup\b`, `\bhichky\b` | `ఎకిళ్లు`, `ఎకిళ్ళు`, `\bekilu\b`, `\bekkilu\b`, `హిచ్కి`, `హిచ్కి` |
| SILENT | 4 | `(?!)` ← no-op | `(?!)` ← no-op |
| CONTEXT | 2 | `हिचकियाँ`, `हिचकिया`, `हिचकीं` | `ఎక్కిళ్లతో`, `త్రేనుపు` |
| FP | 1 | `(?!)` ← no-op | `(?!)` ← no-op |

### 2.6 `th`

| Tier | Bobot | Patterns |
|---|---|---|
| CORE | 5 | `สะอึก`, `อาการสะอึก` |
| TYPO | 4 | `สอึก`, `สะอิก` |
| SILENT | 4 | `(?!)` ← no-op |
| CONTEXT | 2 | `สำลัก`, `เรอ` |
| FP | 1 | `(?!)` ← no-op |

### 2.7 `te` (mandiri — tidak dipakai menu, hanya sumber merge)

| Tier | Bobot | Patterns |
|---|---|---|
| CORE | 5 | `ఎక్కిళ్లు`, `ఎక్కిళ్ళు`, `ఎక్కిలి`, `\bekkillu\b`, `\bekkili\b` |
| TYPO | 4 | `ఎకిళ్లు`, `ఎకిళ్ళు`, `\bekilu\b`, `\bekkilu\b`, `హిచ్కి`, `హిచ్కి` |
| SILENT | 4 | `(?!)` |
| CONTEXT | 2 | `ఎక్కిళ్లతో`, `త్రేనుపు` |
| FP | 1 | `(?!)` |

> Catatan: menu `lang="te"` via `_ALL_KEYWORD_TIERS.get("te")` akan mengembalikan tier Telugu **asal** (tanpa merge). Namun `TRANSCRIPT_LANGS` untuk `"te"` tidak ada di map → fallback `[id,en,id-ID]` (E436). Jadi pilih `te` = keyword Telugu + transcript bahasa Indonesia (kemungkinan besar tidak match).

### 2.8 Klasifikasi tier

`classify_text` (E666–675; IE533–539; AE551–558): untuk setiap tier, hitung **jumlah pattern yang match** (`pat.search`), lalu increment. Satu teks bisa berkontribusi ke banyak tier. `tier_counts` menambah **1 per segmen** per tier yang `count>0` (E825–827) — bukan jumlah pattern.

---

## 3. Scoring

Blok scoring identik secara matematis di ketiga salinan (E869–910, IE594–624, AE599–617).

```
SCORE_CAP   = 60
GLOBAL_SCORE = 0
MARATON_MINS = 0
VALID_CLUSTERS = 0

per cluster:
    c_hits   = len(cluster)
    c_dur_sec = cluster[-1]["sec"] - cluster[0]["sec"]
    c_dur_min = max(1, c_dur_sec // 60)          # integer division, floor, min 1
    c_core   = #h dengan tiers.CORE>0
    c_typo   = #h dengan tiers.TYPO>0
    c_silent = #h dengan tiers.SILENT>0
    c_ctx    = #h dengan tiers.CONTEXT>0
    c_fp     = #h dengan tiers.FP>0

    c_base = (c_core*5) + (c_typo*4) + (c_silent*4) + (c_ctx*2) + (c_fp*1)
    c_density_bonus = min(10, (c_hits // c_dur_min) * 2)   # int div dulu, baru *2, lalu cap 10
    c_silent_bonus  = 15 if c_silent > 0 else 0
    c_total = c_base + c_density_bonus + c_silent_bonus
    GLOBAL_SCORE += c_total
    MARATON_MINS = max(MARATON_MINS, c_dur_min)
    if c_core >= 2: VALID_CLUSTERS += 1

# multi-cluster bonus (per-cluster CORE presence, BUKAN VALID_CLUSTERS)
clusters_with_core = #cluster yang punya >=1 hit CORE
if clusters_with_core > 1:
    GLOBAL_SCORE += 20 * (clusters_with_core - 1)

PERSENTASE = min(100, (GLOBAL_SCORE * 100) // SCORE_CAP)
```

Poin perilaku:
- `c_density_bonus`: `//` int div, jadi `(c_hits // c_dur_min)` bisa 0 walau density riil 1.9. Cap `min(10, ...)`.
- `c_fp` dikali `*1` eksplisit (E888) / implisit `+ c_fp` (AE611) — nilainya sama; perbedaan hanya gaya.
- Multi-cluster bonus pakai `clusters_with_core` (CORE >=1), sedangkan `VALID_CLUSTERS` (CORE >=2) hanya untuk kasta MULTISESI. Kedua metrik berbeda.
- `PERSENTASE` berbasis `GLOBAL_SCORE*100 // 60`, cap 100.

---

## 4. Clustering

Threshold gap dari rentang total HIT_LIST (bukan durasi video asli):

```
total_duration_min = (HIT_LIST[-1]["sec"] - HIT_LIST[0]["sec"]) // 60
if   total_duration_min > 180: CLUSTER_GAP = 60*60   # > 3 jam
elif total_duration_min > 60:  CLUSTER_GAP = 30*60   # 1–3 jam
else:                          CLUSTER_GAP = 20*60   # <= 60 menit
```

(E847–853, IE574–580, AE586–587)

Pembentukan cluster (E855–867, IE582–592, AE588–597): iterasi HIT_LIST berurutan; mulai cluster baru saat `hit["sec"] - cluster[-1]["sec"] >= CLUSTER_GAP`; else append. Cluster terakhir selalu di-flush.

Konsekuensi: `total_duration_min` dihitung dari span hit pertama↔terakhir, **bukan durasi video**. Video panjang tanpa hit awal = span kecil = gap 20 menit. Batas 60 termasuk `<=60` → gap 20 menit.

---

## 5. Kasta (if/elif berurutan)

Urutan prioritas (E917–962, IE630–664, AE623–643). Hit pertama menang.

| # | Kasta | Syarat | Efek `PERSENTASE` | is_valid |
|---|---|---|---|---|
| 1 | AMBIGU | `CORE_HITS == 0` | `min(PERSENTASE, 15)` | False |
| 2 | GOD_MODE | `IS_MARATON and PERSENTASE >= 60` | **= 100** | True |
| 3 | VALID_HIGH (multisesi) | `IS_MULTISESI and PERSENTASE >= 60` | — | True |
| 4 | SILENT | `HAS_SILENT and CORE_HITS >= 1` | `max(PERSENTASE, 75)` | True |
| 5 | VALID_HIGH (core) | `CORE_HITS >= 3 and PERSENTASE >= 60` | — | True |
| 6 | VALID | `CORE_HITS >= 1 and PERSENTASE >= 40` | — | True |
| 7 | LOW | `CORE_HITS >= 1` | — | False |
| 8 | AMBIGU (else) | fallback (praktis tak tercapai karena #1 menangkap CORE_HITS==0, #7 menangkap >=1) | `min(PERSENTASE, 15)` | False |

Flag:
```
IS_MARATON   = (len(clusters) == 1 and MARATON_MINS >= 30 and GLOBAL_SCORE >= 8)
IS_MULTISESI = (VALID_CLUSTERS >= 2)          # cluster dgn >= 2 hit CORE
HAS_SILENT   = tier_counts.get("SILENT", 0) > 0
```
Label kasta selalu ditambah suffix `f" | {len(clusters)} cluster, {len(HIT_LIST)} hit"` (E965).

Catatan: kasta #1 (CORE_HITS==0) menangkap SEMUA kasus tanpa CORE, jadi branch #8 `else` (E959–962) **dead code**. Ini konsisten di ketiga salinan.

---

## 6. Divergensi antar 3 salinan

### 6.1 Ringkasan

| Aspek | E `analyze_video` | IE `_analyze_from_segments` | AE `_analyze_segments` |
|---|---|---|---|
| Sumber segmen | fetch transcript (youtube-transcript-api) | JSON index `segments` (VTT) | VTT parse |
| Field waktu | `seg["start"]` | `seg["sec"]` | `seg["sec"]` |
| `SCORE_CAP` | didefinisikan (60, tak dipakai utk cap global selain rumus) | 60 | hardcode `//60` (AE617) — tetap 60 |
| Kasta & threshold | identik | identik | identik |
| Label kasta | `⚠️ AMBIGU — Indikasi Lemah (0 Hit Core)` | sama persis dgn E | `⚠️ AMBIGU — Indikasi Lemah` (tanpa "(0 Hit Core)") |
| Label GOD_MODE | `... MARATON X MENIT NON-STOP` | sama dgn E | `... MARATON X MENIT` (tanpa NON-STOP) |
| Label VALID_HIGH multisisi | `... X SESI KAMBUHAN` | sama dgn E | `... X SESI` |
| Label SILENT | `VALID — SILENT TREATMENT DETECTED` | sama dgn E | `VALID — SILENT TREATMENT` |
| Highlight HTML | regex `pat.sub` pada teks (E999–1003) | **tidak** highlight, hanya tier_strip | **tidak** highlight, hanya tier_strip |
| Strip `FP` di badge HTML | tidak ada badge FP | tidak ada | tidak ada |

### 6.2 Divergensi perilaku nyata (krusial)

1. **E menghighlight teks hit via `pat.sub` bertingkat** (E988–1003) — dapat memodifikasi HTML jika pattern overlap. IE & AE **tidak** menghighlight (hanya `safe_text` + badge). Hasil HTML E ≠ IE ≠ AE pada teks yang sama.

2. **Field waktu berbeda**: E `int(seg.get("start",0))`; IE/AE `int(seg.get("sec",0))`. Bila dict segmen keliru field → E dapat 0.

3. **Dedup `LAST_TEXT` update**: ketiga salinan sama (update hanya saat hit). Tapi karena E sumbernya youtube-transcript-api (start float, text per detik), sedangkan IE/AE dari VTT hasil collapse-by-timestamp, jumlah HIT_LIST **dapat berbeda** untuk video sama (VTT sudah collapse per detik; youtube-transcript-api tidak).

4. **Pre-check & loop E membandingkan `E804 text.strip()` vs seg dict**, sama dgn IE/AE. Konsisten.

5. **AE `.get("start")`?** Tidak — AE pakai `sec` (AE562). OK.

6. **AE `c_base`**: `c_core*5 + c_typo*4 + c_silent*4 + c_ctx*2 + c_fp` (AE611) — ekuivalen dgn E/IE (`c_fp*1`). Bukan divergensi nilai.

7. **AE tidak punya `SCORE_CAP` variable**, langsung `//60` (AE617). Nilai sama tapi kode berbeda → risiko refactor.

8. **IE mengimpor `analyze_video` dari cs20_engine tapi tidak dipakai** (IE490–495, komentar "reimplementasi inline"). Dead import.

9. **Kasta label panjang beda** (6.1) → setiap konsumen label antar-mode tidak konsisten.

10. **Fallback `_analyze_fallback` (IE718)** beda total: regex `cegukan|hiccup|cekukan|jegukan` saja, tanpa tier/scoring/kasta (isi `is_valid = len(hits)>=1`). Dipakai bila COMPILED_TIERS gagal dimuat.

### 6.3 Struktur `_load_fuzzy_engine` (AE499–520)

AE mencoba `_init_lang(lang)` lalu import `COMPILED_TIERS, ALL_PATTERNS_COMBINED`. Fallback: tier CORE tunggal `cegukan|hiccup|cekukan|jegukan|しゃっくり|딸꾹질`, bobot 5. Jadi bila cs20_engine tak tersedia, AE hanya deteksi 1 pattern gabungan CORE → semua hit CORE, scoring tetap jalan tapi tier TYPO/SILENT/CONTEXT/FP = 0.

---

## 7. Chatseeker Scoring

Regex (`CS561–584`):
```
_KW_UTAMA  = "text"\s*:\s*"[^"]*(cegukan|cekukan|kecegukan)[^"]*"
_KW_ONOMA  = "text"\s*:\s*"[^"]*(hicc|hikk|ngikk)[^"]*"
_KW_DASAR  = "text"\s*:\s*"[^"]*(minum|nafas|napas|kagetin)[^"]*"
_KW_KOMBI  = "text"\s*:\s*"[^"]*((coba|tahan|tarik|buang|kasih)\s*(nafas|napas)
             |(minum)\s*(dulu|kak|bang|dir|obat|dlu)
             |[0-9]+\s*tegukan
             |(gas|coba|di)\s*kagetin)[^"]*"
_KW_ANY    = cegukan|cekukan|hicc|hikk|ngikk|minum|nafas|napas|kagetin
```
Semua `re.IGNORECASE`, dijalankan terhadap **seluruh isi file** (semua baris digabung sebagai string, bukan per-baris).

Rumus `_score_file` (CS587–604):
```
c_utama = len(_KW_UTAMA.findall(content))
c_onoma = len(_KW_ONOMA.findall(content))
c_dasar = len(_KW_DASAR.findall(content))
c_kombi = len(_KW_KOMBI.findall(content))

r_dasar = max(0, c_dasar - c_kombi)
score   = int(c_utama*35 + c_onoma*10 + r_dasar*0.5 + c_kombi*4.5)
```
`int()` truncate toward zero (bukan round).

Threshold level (`CS663–666`) — **hanya dievaluasi bila `score > 0`** (guard `if score==0: return level 0`, CS660–661):
```
score >= 100 → level 4  (LVL4-ABSOLUTE-HYPE)
score >=  75 → level 3  (LVL3-POTENSI-TINGGI)
score >=  50 → level 2  (LVL2-POTENSI-SEDANG)
else         → level 1  (LVL1-POTENSI-RENDAH)
```

`_extract_hits` (CS607–648): baca file baris demi baris; prafilter `_KW_ANY.search(line)`; parse JSON; ambil `replayChatItemAction.actions[].addChatItemAction.item.liveChatTextMessageRenderer`; `text = join(runs.text)`; filter `_KW_ANY.search(text)`; `sec = videoOffsetTimeMsec // 1000`; URL `youtube.com/watch?v=...&t={sec}s`. Baris JSON rusak di-skip diam-diam. **Tidak ada dedup** pada hits.

Catatan: `_extract_hits` **memakai regex `_KW_ANY`** (kata polos `cegukan|hicc|...`), berbeda dari `_score_file` yang memakai pola JSON-quoted `"text"..."`. Efek: skor dihitung dari occurrence dalam literal `"text"`, hit list dari teks yang di-parse.

---

## 8. Search Manual (`cs20_index_parser`)

`_tokenize_query` (P528–557): split query atas `\bOR\b` (case-insensitive) → daftar grup. Tiap grup di-parse `_parse_clause` (P503–525).

`_parse_clause`:
- Semua frasa dalam tanda kutip `"..."` → term type `phrase` (regex `re.escape`, `IGNORECASE`).
- Sisa setelah buang frasa & operator AND/OR → split whitespace → term type `word`, **hanya jika `len(word) >= 2`** (kata 1 huruf dibuang).
- Tidak peduli posisi `AND`/`OR` di dalam klausa — semua term dalam satu klausa = AND.

Hasil: `{"groups": [[term,...], ...], "terms": flatten, "operator": "AND"|"OR"}`. `operator` hanya label, "tidak dipakai matcher" (P540).

**Semantik akhir (after fix; groups OR-of-AND)** di `_search_segments` (P618–664):
```
1. full_text = gabungan semua segmen
2. matched_groups = [g untuk g in groups jika SEMUA term g match full_text]  # AND penuh di level video
3. jika matched_groups kosong → return []
4. active_terms = semua term dari matched_groups
5. hits = segmen yang match >= 1 active_term, dedup by start_sec
```

Konsekuensi: grup AND dievaluasi di **level video** (semua term bisa tersebar di segmen berbeda), bukan per segmen. Baris hit ditampilkan bila match term mana pun dari grup yang lolos.

`search_index_batch` (P560–615) hasil per video:
```
score        = len(hits) * 5
persentase   = min(100, len(hits) * 10)
tier_counts  = {CORE: len(hits), TYPO:0, SILENT:0, CONTEXT:0, FP:0}
cluster_count= 1
is_valid     = True
kasta        = "VALID"
```
Semua video yang punya >=1 hit dianggap VALID. Hasil di-sort `len(hits)` desc (P614).

---

## 9. Open Questions / Ambigu

1. **`c_hits` tak didefinisikan?** — VERIFIKASI: `c_hits` **ADA** di E878 (`c_hits = len(cluster)`) dan dipakai E890. Di IE **tidak ada `c_hits`**; IE pakai `len(cluster)` langsung (IE610). Di AE pakai `len(cl)` (AE612). Jadi bukan bug undefined — hanya penamaan beda. (Klaim awal di brief tidak terbukti.)

2. **`(?!)` sebagai "tier kosong"** — mengapa tier tetap dipertahankan alih-alih dihapus? Mempengaruhi tampilan `tier_counts` (selalu 0) dan tidak mempengaruhi scoring. Perlu konfirmasi apakah ini sengaja.

3. **Dedup `abs(sec-LAST_SEC) < 1`** — pada int hanya menyaring selisih 0. Apakah maksud awal memang "dalam 1 detik" (butuh float)? Perlu konfirmasi.

4. **`total_duration_min` dari span hit**, bukan durasi video — apakah intensional? Ini membuat gap clustering bergantung pada distribusi hit, bukan panjang video.

5. **Kasta #8 `else` dead code** — apakah ada jalur yang diharapkan mencapainya? Secara logika tidak.

6. **E highlight via `pat.sub` berganda** — pattern bisa saling menimpa/menyisipkan tag ke dalam tag (`<span>` di dalam `<span>`). Apakah diinginkan?

7. **`in` merge Telugu** — pilih `te` via menu menghasilkan transcript fallback ID (E436), bukan Telugu. Apakah `te` memang hanya internal?

8. **Chatseeker**: `_score_file` cari di literal `"text"`, `_extract_hits` parse per-baris — dua definisi "keyword" berbeda. Mana yang otoritatif untuk "hit"?

9. **`_extract_hits` hint URL** `...&t={sec}s` (CS642) vs engine `youtu.be/{id}?t={sec}` (E834) — format URL berbeda antar modul. Ada yang mengandalkan parsing URL ini?

10. **AE `_load_fuzzy_engine` fallback** hanya 1 pattern CORE → hasil analisis berbeda total bila import gagal, tanpa penanda status. Apakah caller tahu ia mode fallback? (Tidak — `return ..., False` diabaikan di AE933.)

---

## 10. Tes yang mereveal perilaku

Tidak ditemukan file test di repo (`*.py` di lima file target; tidak ada `test_*.py`, `*_test.py`, `tests/`). Spesifikasi di atas murni dari implementasi. Bila ada tes di luar lima file yang dibaca, perlu ditambahkan ke dokumen ini.
