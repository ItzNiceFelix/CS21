# Implementation Plan — Refactor Cegukan Seeker (`cs_core`)

> Turunan dari `docs/architecture.md` §10 + keputusan final user. Baseline perilaku: `docs/spec-current.md` §2–§6.
> Tak ada kode implementasi di dokumen ini (signature + command saja).

---

## 0. Keputusan final user (mengikat)

| ID | Keputusan final | Catatan plan |
|---|---|---|
| P2 | Label kasta **seragam versi E** (lengkap: `(0 Hit Core)`, `NON-STOP`, `SESI KAMBUHAN`, `DETECTED`) | Default baru `IMPROVED`; `BASELINE` tetap ada utk regresi. |
| P5 | Highlight HTML -> **span bersih**, tanpa nested span | `report.build_html` token-span sekali jalan. |
| P8 | Dedup segmen -> **float berbasis durasi asli** bila sumber punya durasi; else fallback int `==0` | Fungsi `dedup_key`. |
| M9 | Clustering default -> **durasi video**. Flag `CLUSTER_MODE=video_duration|hit_span`, default `video_duration` | Rumus cluster internal wajib-sama §7.2 utk mode `hit_span`. |
| Fase 0 | User jalankan skrip baseline sendiri di Termux; plan hanya hasilkan **skrip** | Output JSON dikirim balik. |
| Dependency | Boleh tambah; utamakan wheel musllinux aarch64; **selalu ada fallback stdlib** | `requirements-*.txt`. |
| Validasi | User uji channel YouTube nyata di Termux | Gate Fase 5 stop-point. |

Global config default: `CompatMode=BASELINE` sampai Fase 5 lolos; setelah validasi user -> `IMPROVED`.

---

## 1. Kontrak Data (KRUSIAL — engine lama tak boleh rusak)

### 1.1 `AnalysisResult` (dataclass, `cs_core/scoring.py`)

```
@dataclass(frozen=True)
class AnalysisResult:
    video_id: str
    lang: str
    hits: tuple[Hit, ...]              # Hit = {sec:int|float, time:str, text:str, tiers:dict, url:str}
    tier_counts: dict[str, int]        # key selalu ada: CORE,TYPO,SILENT,CONTEXT,FP (0 bila kosong)
    score: int                         # GLOBAL_SCORE
    persentase: int
    clusters: tuple[tuple[Hit, ...], ...]
    cluster_count: int
    maraton_mins: int
    valid_clusters: int
    is_maraton: bool
    is_multisesi: bool
    has_silent: bool
    core_hits: int
    kasta: str                         # AMBIGU|GOD_MODE|VALID_HIGH|SILENT|VALID|LOW|ZONK
    kasta_label: str
    is_valid: bool
    status: str                        # analyzed|no_match
    status_label: str
    degraded: bool = False             # P7: penanda fallback mode
    cluster_mode: str = "video_duration"  # M9
    score_cap: int = 60
```

### 1.2 `compat.to_legacy(result, *, mode=CompatMode) -> dict`

Field dict lama yang **WAJIB ADA** (dibaca hilir HTML/Discord/status.json):

`status`, `status_label`, `hits`, `tier_counts`, `score`, `persentase`, `cluster_count`, `maraton_mins`, `is_valid`, `kasta`, `kasta_label`, `html_rows`.

Aturan:
- `mode=BASELINE` -> `kasta_label` memakai varian label engine asal (AE tanpa `(0 Hit Core)`/`NON-STOP`/`SESI KAMBUHAN`/`DETECTED`) via `_legacy_label(kasta, engine=)`.
- `mode=IMPROVED` -> label E lengkap (P2).
- Suffix `f" | {cluster_count} cluster, {len(hits)} hit"` selalu.
- `html_rows` dari `report.build_html_rows(hits, mode)` (P5: span bersih).
- `hits` dikembalikan sebagai `list[dict]` supaya `json.dump` sama.

**DoD kontrak:** test Fase 1 membandingkan `compat.to_legacy(result_baseline)` byte-for-byte dengan fixture Fase 0.

---

## 2. Fase & Task

Legenda: **S** <=1 hari, **M** ~1-2 hari, **L** >=3 hari.

### FASE 0 — Skrip baseline & golden fixtures (S)
Tujuan: skrip yang user jalankan di Termux untuk merekam output 4 engine + scoring murni.

- **T0.1** `tools/baseline_capture.py` — CLI: `--channel CH --lang id --limit N --engines e,ie,ae,cs --out tests/fixtures/baseline_<channel>_<lang>.json`.
  Rekam raw segmen (input) + `analyze_video` (E) + `_analyze_from_segments` (IE) + `_analyze_segments` (AE) untuk N video. Tambah `tools/pure_scoring_probe.py` memanggil blok scoring murni langsung (tanpa fetch).
  DoD: file ada, `--help` jalan, output JSON valid; tak menyentuh kode engine.
- **T0.2** `tools/baseline_compare.py` — banding dua file baseline (atau baseline vs `cs_core` `BASELINE`); cetak diff per-field per-video; exit != 0 bila ada beda. DoD: baseline vs dirinya sendiri = 0 diff.
- **T0.3** `tools/fixtures_synthetic.py` (opsional) — segmen sintetis: 0 CORE, maraton, multisisi, silent, dedup float.
- **T0.4** `tools/TERMUX_BASELINE.md` — command persis + format balik.

Dependensi: tidak ada.
Risiko: sumber segmen E (float) vs IE/AE (int) beda -> HIT_LIST bisa beda untuk video sama (spec §6.2 #3). Wajib catat `source` per-video di fixture.

Command user (Termux):
```
pip install youtube-transcript-api requests yt-dlp --break-system-packages
python3 tools/baseline_capture.py --channel "<CHANNEL>" --lang id --limit 20 \
  --out tests/fixtures/baseline_<channel>_id.json
python3 tools/baseline_capture.py --channel "<CHANNEL2>" --lang en --limit 20 \
  --out tests/fixtures/baseline_<channel2>_en.json
```
Output dikirim balik: **file JSON** `tests/fixtures/*.json`.

Gate F0 -> F1: >=2 fixture (id + en) ada; self-compare 0 diff.

---

### FASE 1 — Tulang `cs_core`: text, tokens, scoring (M)
Tujuan: satu implementasi scoring identik baseline (tanpa fuzzy).

- **T1.1** `cs_core/__init__.py` (`__version__`).
- **T1.2** `cs_core/text.py` — `normalize(seg) -> str` (strip; NFC; TANPA lowercasing agar sama baseline; VTT tag strip `_VTT_TAG_RE`). DoD: test tag strip + CJK utuh.
- **T1.3** `cs_core/tokens.py` — `extract(text) -> TokenList` (satu pass, simpan raw+offset). DoD: 1 pass terverifikasi via counter.
- **T1.4** `cs_core/languages/base.py` — `LanguageSpec` (frozen), `KeywordCore`, `TierWeights`; `compile()` -> regex sekali, cache di objek (no global mutable).
- **T1.5** `cs_core/languages/__init__.py` — `load(lang) -> LanguageSpec`; Fase 1 isi SEMENTARA = salinan regex `_ALL_KEYWORD_TIERS` (migrasi data menyusul Fase 2). Hapus `(?!)` -> tier kosong (P4) tapi tetap key di `tier_counts`.
- **T1.6** `cs_core/matching.py` — `count_rule_hits(toks, rules, text)` L1 exact/regex saja.
- **T1.7** `cs_core/scoring.py` — `score_segments(segments, lang_spec, *, cluster_mode, dedup_mode, video_duration_sec=None) -> AnalysisResult`. Rumus internal byte-for-byte §7.2 (int div `c_hits // c_dur_min`, cap 60, `//` untuk PERSENTASE). `dedup_key(seg, prev, dedup_mode)` — P8: float bila `duration` ada (`abs(delta) < 1`), else int `==0`. Clustering: `hit_span` reproduksi baseline; `video_duration` pakai durasi video (M9).
- **T1.8** `cs_core/config.py` — `CompatMode` (BASELINE default), baca env `CLUSTER_MODE`, `CACHE_TTL_DAYS`.
- **T1.9** `cs_core/compat.py` — `to_legacy()` + `_legacy_label`.
- **T1.10** `tests/test_scoring.py` — golden vs fixture (BASELINE), property test (1000 segmen acak: PERSENTASE <=100, `is_valid => core_hits>0`).
- **T1.11** `tests/test_dedup.py` — P8 float vs int.

Dependensi: T0 fixtures; T1.2->T1.3->T1.5->T1.6->T1.7; T1.7->T1.9->T1.10.
DoD: golden scoring lolos utk E/IE/AE, mode BASELINE.
Gate F1 -> F2: `pytest tests/test_scoring.py` hijau 100%.

---

### FASE 2 — Bahasa deklaratif & generator varian (L)
Tujuan: keyword = data; regex manual dipensiunkan.

- **T2.1** `cs_core/languages/variants.py` — `auto_typo`, `phonetic_id`, `romanize`, `build_regex`, `build_phonetic_set`.
- **T2.2** `cs_core/languages/{id,en,jp,kr,in,te,th}.yaml` — deklarasi §4.1; `core_forms` disalin dari regex lama spec §2.
- **T2.3** `cs_core/languages/load.py` — baca YAML + `include_scripts` (in+te merge §4.4); `te` internal, `TRANSCRIPT_LANGS["te"] = [te,te-IN,hi]` (P9).
- **T2.4** `cs_core/transcript.py` — `TRANSCRIPT_LANGS` map dipindah ke sini; `get_segments(video_id, lang, source_hint, force_refresh)` (skeleton; fetch penuh Fase 4).
- **T2.5** `tests/test_anti_typo.py` — tabel `(text, expected_tier)`: cegukan/jegukan/segukan/cekukan; hiccup/hicup/hickup; shakkuri variants; FP `nyendawa`, `economic hiccup`.
- **T2.6** `tools/diff_forms.py` — banding forms baru vs regex lama; GAGAL bila ada CORE form hilang.

Dependensi: Fase 1 (base.py). T2.1->T2.2->T2.3; T2.5<-T2.3.
DoD: test anti-typo lolos; `diff_forms.py` 0 CORE hilang.
Gate F2 -> F3: diff_forms 0 kehilangan CORE + golden F1 masih hijau.

---

### FASE 3 — Fuzzy & phonetic berlapis (L)
Tujuan: tahan misshear ASR tanpa banjir FP.

- **T3.1** `cs_core/matching.py` — L0 prefilter (1 regex gabungan), L2 fuzzy token (`rapidfuzz.extractOne`|`difflib` length-gate), L3 phonetic.
- **T3.2** `cs_core/diagnostics.py` — `HAVE_RAPIDFUZZ` probe, `fallback_status()`, timing ringan, TANPA rich.
- **T3.3** `cs_core/languages/base.py` — `neg_context`, `fuzzy_skip`, `fuzzy_threshold`, `fuzzy_hits_cap`.
- **T3.4** `tests/test_fp.py` — FP tetap non-VALID; `nyendawa`, `economic hiccup`.
- **T3.5** `tests/test_fallback.py` — monkeypatch RapidFuzz absent -> tetap jalan, `degraded=True`.
- **T3.6** `requirements-termux.txt` (rapidfuzz musllinux aarch64), `requirements-min.txt` (stdlib only).

Dependensi: Fase 2. DoD: FP non-VALID; typo ASR lolos; fallback status benar.
Gate F3 -> F4: `pytest tests/test_fp.py tests/test_fallback.py` hijau; golden F1 hijau.

---

### FASE 4 — Transcript + cache gzip (M) [paralel]
Tujuan: fetch sekali, cache gzip JSONL streaming.

- **T4.1** `cs_core/cache.py` — `read/write/purge`, `transcripts/{video_id}.{lang}.jsonl.gz`, header meta, TTL 30d env, atomic -> `os.replace`, `compresslevel=1`, format-version miss.
- **T4.2** `cs_core/transcript.py` — adapter `start`->`sec` (P6), VTT streaming `parse_vtt_file`, `fetch_api/fetch_vtt/fetch_index`, cache-first.
- **T4.3** `tests/test_cache.py` — round-trip, TTL, versi mismatch, atomic, corrupt JSONL skip.
- **T4.4** `tests/test_transcript.py` — cache hit tanpa network (mock), VTT tak load penuh.

Dependensi: Fase 1 (result shape). Bisa PARALEL dengan Fase 2/3.
DoD: cache hit tanpa network; round-trip; streaming.
Risiko: gzip CPU ARM -> level 1.

---

### FASE 5 — Migrasi engine strangler (L) — STOP POINT uji channel nyata
Tujuan: engine lama delegasi ke `cs_core`, output identik baseline.

- **T5.1** `cs20_age_engine.py`: `_load_fuzzy_engine`->`languages.load`; `_analyze_segments`->`scoring`+`compat.to_legacy`; penanda `degraded` (P7).
- **T5.2** `cs20_index_engine.py`: hapus salinan scoring/classify; hapus `_analyze_fallback`; hapus dead import `_av`.
- **T5.3** `cs20_index_parser.py`: `parse_vtt_content`+`_search_segments` delegasi `transcript`+`matching`.
- **T5.4** `cs20_engine.py`: `analyze_video` = `transcript.get_segments`->`scoring.score_segments`->`compat.to_legacy`; `_init_lang` tetap ada tapi delegasi.
- **T5.5** `chatseeker.py`: `_KW_*` adopsi `matching`; rumus `_score_file` WAJIB-SAMA §7.2; dua definisi keyword TETAP (Open Q#8).
- **T5.6** `tests/test_engine_parity.py` — golden per engine mode BASELINE identik fixture Fase 0.

Dependensi: Fase 1-4 semua.
DoD: golden per engine BASELINE identik; tak ada import dead.
Gate stop: user jalankan `cs20.sh` di channel nyata, `CompatMode=BASELINE`, banding output lama. Lolos -> lanjut.

---

### FASE 6 — `report.py` tunggal + `IMPROVED` default (M)
Tujuan: satu HTML/Discord; highlight span bersih (P5); label seragam (P2).

- **T6.1** `cs_core/report.py` — `build_html`, `build_html_rows`, `send_discord`; token-span sekali (tak nested).
- **T6.2** Pindahkan CSS/`_card_class`/`_pct_class`/`_tier_strip` dari E ke `report.py`.
- **T6.3** Set default `CompatMode=IMPROVED` (setelah validasi user Fase 5).
- **T6.4** `tests/test_report.py` — HTML E/IE/AE identik input sama; assert tak ada `<span` di dalam `<span`.

Dependensi: Fase 5. DoD: HTML tiga engine identik; highlight tak nested.
Gate F6 -> F7: test_report hijau + user setujui visual.

---

### FASE 7 — CLI baru, cleanup dependency, dokumentasi Termux (M)
Tujuan: entry tunggal; instalasi bersih.

- **T7.1** `cs_core/cli.py` — `search/analyze/index/age/cache`.
- **T7.2** `cs20.sh` update: `check_and_install_deps` cek `cs_core` importable; tetap panggil engine lama (kompatibel) atau CLI baru (opsional).
- **T7.3** `requirements-*.txt` final; README Termux (`pip install --break-system-packages`).
- **T7.4** Hapus dead code (`_analyze_fallback` IE, `(?!)`, dead import).

Dependensi: Fase 6. DoD: instalasi bersih ARM64/venv simulasi; semua test lolos.
Gate F7 -> F8: `pytest` full hijau.

---

### FASE 8 — Optimasi lanjut (opsional) (L)
Tujuan: metrik efisiensi §5.1; cluster `video_duration` penuh; GC cache.

- **T8.1** symspellpy L4 opsional.
- **T8.2** romanisasi penuh JP/KR/HI/TH.
- **T8.3** GC cache terjadwal (`cs20 cache gc`).
- **T8.4** `CLUSTER_MODE=video_duration` finalisasi + banding baseline (M9).
- **T8.5** `tests/test_efficiency.py` — assert regex call <= pattern unik (regresi M2/M3).

Dependensi: Fase 7. DoD: metrik §5.1; no regresi golden.

---

## 3. Urutan Dependensi & Jalur Kritis

- F0 -> F1 -> F2 -> F3 -> F5 -> F6 -> F7 -> F8
- F4 (cache/transcript) bergantung F1, PARALEL dengan F2/F3.
- F5 butuh F1+F2+F3+F4.

Jalur kritis: F0 -> F1 -> F2 -> F3 -> F5 (stop-point) -> F6 -> F7.
Jalur paralel: F4 (cache) || F2/F3 (setelah F1). F8 fully opsional.

---

## 4. Strategi Kontrol P8 & M9

- Flag: `DEDUP_MODE=float|int0` (default `float` bila sumber punya `duration`, else `int0`); `CLUSTER_MODE=video_duration|hit_span` (default `video_duration`). Baca dari env + argumen CLI.
- Test: `tests/test_dedup.py` (P8) & `tests/test_cluster.py` (M9) — dua mode dibanding langsung.
- Baseline: semua fixture Fase 0 punya `dedup_mode`/`cluster_mode` tercatat -> `baseline_compare.py` tahu mode mana yang harus identik.
- Rollback: set `DEDUP_MODE=int0 CLUSTER_MODE=hit_span` -> perilaku baseline persis.
- Karena ubah hasil: Fase 5 default `BASELINE`+`hit_span`+`int0`; P8/M9 diaktifkan hanya di Fase 6/8 setelah validasi user.

---

## 5. Definition of Done Global & Gate

DoD global:
- [ ] `pytest tests/` full hijau.
- [ ] `baseline_compare.py` mode BASELINE = 0 diff pada semua fixture.
- [ ] Instalasi bersih Termux ARM64 (`requirements-min.txt` dan `requirements-termux.txt`).
- [ ] `cs20.sh` semua mode (1,4,5,6,7,8) jalan tanpa error.
- [ ] User validasi 1 channel nyata di Termux.

Gate per fase:
- F0: >=2 fixture + self-compare 0 diff.
- F1: `test_scoring.py` hijau.
- F2: `diff_forms` 0 CORE hilang.
- F3: `test_fp.py` + `test_fallback.py` hijau.
- F4: `test_cache.py` + `test_transcript.py` hijau.
- F5: golden per-engine identik + user channel nyata.
- F6: HTML identik + user visual.
- F7: full pytest hijau.
- F8: metrik efisiensi.

---

## 6. Estimasi Kompleksitas

| Fase | Skala | Alasan |
|---|---|---|
| F0 | S | Skrip rekam + compare. |
| F1 | M | Rumus harus presisi. |
| F2 | L | 7 bahasa + generator varian. |
| F3 | L | Fuzzy/phonetic + anti-FP. |
| F4 | M | Cache + streaming. |
| F5 | L | 5 engine migrasi + parity. |
| F6 | M | Report tunggal. |
| F7 | M | CLI + docs. |
| F8 | L | Opsional. |

---

## 7. Out of Scope (TIDAK dikerjakan)

- Hapus engine lama (`cs20_*.py`) — tetap hidup, jadi konsumen tipis.
- symspellpy/wordninja wajib — tetap opsional L4.
- Phonetic Inggris (jellyfish) utk non-Latin — ditolak (architecture §3.4).
- Ubah rumus chatseeker / normalisasi dua definisi keyword (Open Q#8) — tetap.
- Ubah dedup `LAST_TEXT` semantik update-hanya-saat-hit — tetap.
- Multi-channel paralel baru / GUI.
- Live chat CDN cache (chatseeker cache opsional, bukan wajib).
- Migrasi data JSON index lama (di luar cache transcript baru).
