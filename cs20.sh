#!/bin/bash
# ==============================================================================
# 👑 CEGUKAN SEEKER V20.0 - REBORN EDITION
# Engine: youtube-transcript-api (Python) | Hybrid Bash+Python
# Modes: Tidur / Semi Pantau / Pantau
# Features: Checkpoint/Resume, RAM Guard, Fuzzy Regex, Multi-Channel
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_ENGINE="$SCRIPT_DIR/cs20_engine.py"
CONFIG_DIR="$SCRIPT_DIR/.cs20"
CHECKPOINT_DIR="$CONFIG_DIR/checkpoints"
PROFILE_FILE="$CONFIG_DIR/profile"
VERSION="20.0"
# ── Webhook Indonesia & Global — HARUS di-inject via inject_webhook.sh ──
WEBHOOK_FILE="$CONFIG_DIR/.webhook_injected"
WEBHOOK_INDONESIA=""
WEBHOOK_GLOBAL=""

# Warna terminal
R='\033[0;31m'  GR='\033[0;32m'  Y='\033[0;33m'
B='\033[0;34m'  M='\033[0;35m'   C='\033[0;36m'
W='\033[1;37m'  DIM='\033[2m'    BOLD='\033[1m'
NC='\033[0m'

# ==============================================================================
# WEBHOOK INJECTOR CHECK — script tidak boleh lanjut tanpa ini
# ==============================================================================
inject_webhook() {
    if [ ! -f "$WEBHOOK_FILE" ]; then
        echo -e "${R}[❌] Webhook belum di-inject!${NC}"
        echo -e "${Y}     Jalankan dulu: ${C}bash inject_webhook.sh${NC}"
        exit 1
    fi

    # shellcheck disable=SC1090
    source "$WEBHOOK_FILE"

    if [ -z "$WEBHOOK_INDONESIA" ] || [ -z "$WEBHOOK_GLOBAL" ]; then
        echo -e "${R}[❌] File webhook rusak/kosong — WEBHOOK_INDONESIA atau WEBHOOK_GLOBAL tidak ada.${NC}"
        echo -e "${Y}     Hapus $WEBHOOK_FILE lalu jalankan ulang: bash inject_webhook.sh${NC}"
        exit 1
    fi
    echo -e "${GR}[✅] Webhook siap (Indonesia & Global).${NC}"
}

# ==============================================================================
# DEPENDENCY CHECK & AUTO INSTALL
# ==============================================================================
check_and_install_deps() {
    echo -e "${C}[🧹] Membersihkan file HTML lama (Skenario B)...${NC}"
    # Hapus file HTML di folder .cs20 yang usianya lebih dari 24 jam (+1 hari)
    find "$CONFIG_DIR" -maxdepth 1 -name "*.html" -type f -mtime +0 -exec rm -f {} \; 2>/dev/null
    
    echo -e "${C}[🔍] Memeriksa dependensi...${NC}"
    local MISSING=()

    # Cek Python3
    if ! command -v python3 &>/dev/null; then
        MISSING+=("python3")
    fi

    # Cek yt-dlp
    if ! command -v yt-dlp &>/dev/null; then
        MISSING+=("yt-dlp")
    fi

    # Cek curl
    if ! command -v curl &>/dev/null; then
        MISSING+=("curl")
    fi

    # Cek pip packages Python
    local PY_MISSING=()
    python3 -c "import youtube_transcript_api" 2>/dev/null || PY_MISSING+=("youtube-transcript-api")
    python3 -c "import requests" 2>/dev/null || PY_MISSING+=("requests")

    # Install binary yang kurang
    if [ ${#MISSING[@]} -gt 0 ]; then
        echo -e "${Y}[⚠️] Paket kurang: ${MISSING[*]}${NC}"
        echo -e "${C}[📦] Menginstall via pkg...${NC}"
        pkg install -y "${MISSING[@]}" 2>/dev/null || {
            echo -e "${R}[❌] Gagal install: ${MISSING[*]}${NC}"
            echo -e "${Y}     Coba manual: pkg install ${MISSING[*]}${NC}"
            exit 1
        }
    fi

    # Install Python packages yang kurang
    if [ ${#PY_MISSING[@]} -gt 0 ]; then
        echo -e "${Y}[⚠️] Python package kurang: ${PY_MISSING[*]}${NC}"
        echo -e "${C}[📦] Menginstall via pip...${NC}"
        pip install "${PY_MISSING[@]}" --break-system-packages -q 2>/dev/null || \
        pip install "${PY_MISSING[@]}" -q 2>/dev/null || {
            echo -e "${R}[❌] Gagal install Python packages.${NC}"
            echo -e "${Y}     Coba manual: pip install ${PY_MISSING[*]} --break-system-packages${NC}"
            exit 1
        }
    fi

    # Cek engine Python ada
    if [ ! -f "$PYTHON_ENGINE" ]; then
        echo -e "${R}[❌] File engine tidak ditemukan: cs20_engine.py${NC}"
        echo -e "${Y}     Pastikan cs20_engine.py ada di folder yang sama dengan cs20.sh${NC}"
        exit 1
    fi

    echo -e "${GR}[✅] Semua dependensi siap!${NC}"
}

# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================
get_ram_mb() {
    awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo 2>/dev/null || echo "0"
}

draw_line() {
    echo -e "${DIM}════════════════════════════════════════════════════════${NC}"
}

draw_box_title() {
    local title="$1"
    local color="${2:-$C}"
    echo -e "${color}"
    echo -e "╔══════════════════════════════════════════════════════╗"
    printf  "║  %-52s║\n" "$title"
    echo -e "╚══════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

# ==============================================================================
# BANNER
# ==============================================================================
show_banner() {
    clear
    echo -e "${M}"
    cat << 'EOF'
  ██████╗███████╗ ██████╗ ██╗   ██╗██╗  ██╗ █████╗ ███╗  ██╗
 ██╔════╝██╔════╝██╔════╝ ██║   ██║██║ ██╔╝██╔══██╗████╗ ██║
 ██║     █████╗  ██║  ███╗██║   ██║█████╔╝ ███████║██╔██╗██║
 ██║     ██╔══╝  ██║   ██║██║   ██║██╔═██╗ ██╔══██║██║╚████║
 ╚██████╗███████╗╚██████╔╝╚██████╔╝██║  ██╗██║  ██║██║ ╚███║
  ╚═════╝╚══════╝ ╚═════╝  ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚══╝
EOF
    echo -e "${C}          ✦  S E E K E R  V${VERSION}  —  REBORN EDITION  ✦${NC}"
    echo -e "${DIM}        Engine: youtube-transcript-api | Fuzzy Regex Active${NC}"
    draw_line
}

# ==============================================================================
# PROFILE MANAGEMENT
# ==============================================================================
load_profile() {
    mkdir -p "$CONFIG_DIR" "$CHECKPOINT_DIR"

    if [ -f "$PROFILE_FILE" ]; then
        EXECUTOR=$(cat "$PROFILE_FILE")
        echo -e "${GR}[👤] Selamat datang kembali, ${BOLD}$EXECUTOR${NC}${GR}!${NC}"
    else
        echo -e "${Y}[👤] USER BARU TERDETEKSI${NC}"
        echo -e "${W}Masukkan nama alias kamu (ini akan muncul di laporan Discord):${NC}"
        read -rp "  ➤ Nama alias: " EXECUTOR
        while [ -z "$EXECUTOR" ]; do
            echo -e "${R}  Nama tidak boleh kosong!${NC}"
            read -rp "  ➤ Nama alias: " EXECUTOR
        done
        echo "$EXECUTOR" > "$PROFILE_FILE"
        echo -e "${GR}[✅] Profile tersimpan!${NC}"
    fi
}

# ==============================================================================
# INPUT LANGUAGE (BAHASA ENGINE)
# ==============================================================================
input_language() {
    echo ""
    draw_line
    echo -e "${W}[🌐] PILIH BAHASA ENGINE${NC}"
    draw_line
    echo -e "   ${C}1.${NC} 🇮🇩 Indonesia (ID)"
    echo -e "   ${C}2.${NC} 🇯🇵 Jepang (JP)"
    echo -e "   ${C}3.${NC} 🇰🇷 Korea (KR)"
    echo -e "   ${C}4.${NC} 🇮🇳 Hindi (IN) ${DIM}— otomatis kebaca juga kalau transcript keluar aksara Telugu${NC}"
    echo -e "   ${C}5.${NC} 🇬🇧 Inggris (EN)"
    echo -e "   ${C}6.${NC} 🇹🇭 Thailand (TH)"
    echo ""
    read -rp "  ➤ Pilihan (1-6): " LANG_INPUT

    case "$LANG_INPUT" in
        1) LANG_CHOICE="id" ;;
        2) LANG_CHOICE="jp" ;;
        3) LANG_CHOICE="kr" ;;
        4) LANG_CHOICE="in" ;;
        5) LANG_CHOICE="en" ;;
        6) LANG_CHOICE="th" ;;
        *) echo -e "${Y}Pilihan tidak valid, default ke Indonesia (ID).${NC}"; LANG_CHOICE="id" ;;
    esac

    # Semua bahasa pakai engine yang sama, webhook berbeda per bahasa
    PYTHON_ENGINE="$SCRIPT_DIR/cs20_engine.py"
    case "$LANG_CHOICE" in
        id) WEBHOOK_URL="$WEBHOOK_INDONESIA" ;;
        *)  WEBHOOK_URL="$WEBHOOK_GLOBAL" ;;
    esac

    # Validasi ketersediaan engine
    if [ ! -f "$PYTHON_ENGINE" ]; then
        echo -e "${R}[❌] Engine untuk bahasa tersebut tidak ditemukan! Pilih yang lain.${NC}"
        sleep 1.5
        input_language # Panggil dirinya sendiri untuk loop (wajib pilih yang ada)
    fi

    echo -e "${GR}[✅] Engine terpilih: $(basename "$PYTHON_ENGINE")${NC}"
}

# ==============================================================================
# INPUT CHANNEL
# ==============================================================================
input_channels() {
    local max_channels="$1"
    local mode_name="$2"
    TARGET_CHANNELS=()

    echo ""
    draw_line
    echo -e "${W}[📺] INPUT TARGET CHANNEL${NC}"
    echo -e "${DIM}   Mode $mode_name — Unlimited channel${NC}"
    draw_line
    echo -e "${DIM}   Format: nama channel tanpa '@' (contoh: windahbasudara)${NC}"
    echo -e "${DIM}   Ketik 'selesai' jika sudah cukup${NC}"
    echo ""

    local i=1
    while [ $i -le $max_channels ]; do
        read -rp "  ➤ Channel $i (atau 'selesai'): " ch_input
        ch_input="${ch_input#@}"  # Hapus @ jika ada
        ch_input="${ch_input// /}"  # Hapus spasi

        [ "$ch_input" = "selesai" ] && break
        [ -z "$ch_input" ] && continue

        TARGET_CHANNELS+=("$ch_input")
        echo -e "     ${GR}✓ @$ch_input ditambahkan${NC}"
        ((i++))
    done

    if [ ${#TARGET_CHANNELS[@]} -eq 0 ]; then
        echo -e "${R}[❌] Tidak ada channel yang dimasukkan!${NC}"
        exit 1
    fi

    echo ""
    echo -e "${GR}[✅] Total: ${#TARGET_CHANNELS[@]} channel dipilih${NC}"
}

# ==============================================================================
# INPUT TIPE KONTEN
# ==============================================================================
input_content_type() {
    echo ""
    draw_line
    echo -e "${W}[🎬] PILIH TIPE KONTEN YANG DICARI${NC}"
    draw_line
    echo -e "   ${C}1.${NC} 🔴 Arsip Live Stream saja"
    echo -e "   ${C}2.${NC} 🎬 Video biasa saja (bukan live, bukan shorts)"
    echo -e "   ${C}3.${NC} 🌐 Semua (kecuali Shorts)"
    echo ""
    read -rp "  ➤ Pilihan (1/2/3): " CONTENT_TYPE_INPUT

    case "$CONTENT_TYPE_INPUT" in
        1) CONTENT_TYPE="live"   ; CONTENT_LABEL="🔴 Arsip Live Stream" ;;
        2) CONTENT_TYPE="video"  ; CONTENT_LABEL="🎬 Video Biasa" ;;
        3) CONTENT_TYPE="all"    ; CONTENT_LABEL="🌐 Semua (kecuali Shorts)" ;;
        *) CONTENT_TYPE="all"    ; CONTENT_LABEL="🌐 Semua (kecuali Shorts)"
           echo -e "${Y}   Input tidak valid, default: Semua${NC}" ;;
    esac

    echo -e "${GR}[✅] Tipe konten: $CONTENT_LABEL${NC}"
}

# ==============================================================================
# INPUT JOB PRESET
# ==============================================================================
input_job_preset() {
    local RAM
    RAM=$(get_ram_mb)

    echo ""
    draw_line
    echo -e "${W}[⚡] PILIH MODE KECEPATAN${NC}"
    echo -e "${DIM}   RAM tersedia saat ini: ${RAM}MB${NC}"
    draw_line
    echo -e "   ${C}1.${NC} 💤 HEMAT   — 2 jobs  ${DIM}(HP kentang / baterai tipis)${NC}"
    echo -e "   ${C}2.${NC} ⚖️  BALANCE — 4 jobs  ${DIM}(default, mid-range)${NC}"
    echo -e "   ${C}3.${NC} 🚀 TURBO   — 6 jobs  ${DIM}(RAM 6GB+)${NC}"
    echo -e "   ${C}4.${NC} ☢️  CUSTOM  — bebas   ${DIM}(HP dewa, tau risikonya!)${NC}"
    echo ""
    read -rp "  ➤ Pilihan (1/2/3/4): " JOB_INPUT

    case "$JOB_INPUT" in
        1) MAX_JOBS=2 ; JOB_LABEL="💤 HEMAT (2 jobs)" ;;
        2) MAX_JOBS=4 ; JOB_LABEL="⚖️ BALANCE (4 jobs)" ;;
        3) MAX_JOBS=6 ; JOB_LABEL="🚀 TURBO (6 jobs)" ;;
        4)
            read -rp "  ➤ Masukkan jumlah jobs (1-20): " CUSTOM_JOBS
            if [[ "$CUSTOM_JOBS" =~ ^[0-9]+$ ]] && [ "$CUSTOM_JOBS" -ge 1 ] && [ "$CUSTOM_JOBS" -le 20 ]; then
                MAX_JOBS=$CUSTOM_JOBS
                JOB_LABEL="☢️ CUSTOM ($CUSTOM_JOBS jobs)"
                if [ "$CUSTOM_JOBS" -gt 8 ]; then
                    echo -e "${Y}   [⚠️] ${CUSTOM_JOBS} jobs sangat agresif. Pastikan RAM cukup!${NC}"
                fi
            else
                MAX_JOBS=4
                JOB_LABEL="⚖️ BALANCE (4 jobs) — default karena input invalid"
            fi
            ;;
        *) MAX_JOBS=4 ; JOB_LABEL="⚖️ BALANCE (4 jobs)" ;;
    esac

    # RAM safety check
    local safe_jobs=$(( RAM / 150 ))
    [ "$safe_jobs" -lt 1 ] && safe_jobs=1
    if [ "$MAX_JOBS" -gt "$safe_jobs" ]; then
        echo -e "${Y}   [⚠️] RAM saat ini aman untuk ${safe_jobs} jobs. Kamu pilih ${MAX_JOBS}.${NC}"
        echo -e "${Y}         RAM guard tetap aktif — akan throttle otomatis jika perlu.${NC}"
    fi

    echo -e "${GR}[✅] Mode kecepatan: $JOB_LABEL${NC}"
}

# ==============================================================================
# INPUT BATAS VIDEO PER CHANNEL
# ==============================================================================
input_video_limits() {
    echo ""
    draw_line
    echo -e "${W}[📊] BATAS VIDEO PER CHANNEL${NC}"
    draw_line

    declare -gA CHANNEL_LIMITS
    TOTAL_VIDEOS_ALL=0

    for CH in "${TARGET_CHANNELS[@]}"; do
        echo -e "\n   ${C}@$CH${NC}"

        # Ambil jumlah video sesuai tipe konten yang dipilih
        echo -e "   ${DIM}Mengambil info channel...${NC}"
        local V_COUNT
        if [ "$CONTENT_TYPE" = "live" ]; then
            V_COUNT=$(yt-dlp --flat-playlist --print id --quiet \
                "https://www.youtube.com/@$CH/streams" 2>/dev/null | wc -l)
        elif [ "$CONTENT_TYPE" = "video" ]; then
            V_COUNT=$(yt-dlp --flat-playlist --print id --quiet \
                --match-filter "duration>60" \
                "https://www.youtube.com/@$CH/videos" 2>/dev/null | wc -l)
        else
            local V_LIVE V_VID
            V_LIVE=$(yt-dlp --flat-playlist --print id --quiet \
                "https://www.youtube.com/@$CH/streams" 2>/dev/null | wc -l)
            V_VID=$(yt-dlp --flat-playlist --print id --quiet \
                --match-filter "duration>60" \
                "https://www.youtube.com/@$CH/videos" 2>/dev/null | wc -l)
            V_COUNT=$(( V_LIVE + V_VID ))
        fi

        echo -e "   ${DIM}Total video tersedia: ~${V_COUNT}${NC}"
        echo -e "   ${DIM}Ketik angka, atau 'all' untuk semua${NC}"
        read -rp "  ➤ Batas video untuk @$CH: " V_INPUT

        if [ "$V_INPUT" = "all" ]; then
            CHANNEL_LIMITS[$CH]=$V_COUNT
            TOTAL_VIDEOS_ALL=$(( TOTAL_VIDEOS_ALL + V_COUNT ))
            echo -e "   ${GR}✓ Semua $V_COUNT video${NC}"
        elif [[ "$V_INPUT" =~ ^[0-9]+$ ]] && [ "$V_INPUT" -gt 0 ]; then
            local actual=$(( V_INPUT < V_COUNT ? V_INPUT : V_COUNT ))
            CHANNEL_LIMITS[$CH]=$actual
            TOTAL_VIDEOS_ALL=$(( TOTAL_VIDEOS_ALL + actual ))
            echo -e "   ${GR}✓ $actual video${NC}"
        else
            CHANNEL_LIMITS[$CH]=10
            TOTAL_VIDEOS_ALL=$(( TOTAL_VIDEOS_ALL + 10 ))
            echo -e "   ${Y}  Input tidak valid, default: 10 video${NC}"
        fi
    done
}

# ==============================================================================
# CEK CHECKPOINT
# ==============================================================================
check_checkpoint() {
    local channel="$1"
    local cp_file="$CHECKPOINT_DIR/${channel}.checkpoint"

    if [ -f "$cp_file" ]; then
        local cp_done cp_total cp_time
        cp_done=$(grep "DONE=" "$cp_file" | cut -d= -f2)
        cp_total=$(grep "TOTAL=" "$cp_file" | cut -d= -f2)
        cp_time=$(grep "TIME=" "$cp_file" | cut -d= -f2)

        echo ""
        echo -e "${Y}[💾] CHECKPOINT DITEMUKAN untuk @${channel}!${NC}"
        echo -e "   Progres sebelumnya: ${cp_done}/${cp_total} video (${cp_time})"
        echo -e "   ${W}Lanjutkan dari checkpoint, atau mulai ulang?${NC}"
        echo -e "   ${C}1.${NC} Lanjutkan dari video ke-$((cp_done+1))"
        echo -e "   ${C}2.${NC} Mulai ulang dari awal"
        read -rp "  ➤ Pilihan (1/2): " cp_choice

        if [ "$cp_choice" = "1" ]; then
            CHECKPOINT_START[$channel]=$cp_done
            echo -e "${GR}[✅] Melanjutkan dari checkpoint!${NC}"
        else
            rm -f "$cp_file"
            CHECKPOINT_START[$channel]=0
            echo -e "${GR}[✅] Mulai ulang dari awal.${NC}"
        fi
    else
        CHECKPOINT_START[$channel]=0
    fi
}

# ==============================================================================
# ESTIMASI WAKTU
# ==============================================================================
show_estimate() {
    local total_videos="$1"
    local jobs="$2"

    # Rata-rata: 1.8 detik per video dengan youtube-transcript-api
    # + jeda 0.5-1.5 detik = ~2.5 detik per video per slot
    local est_sec=$(( (total_videos * 25) / (jobs * 10) ))
    local est_min=$(( est_sec / 60 ))
    local est_sek=$(( est_sec % 60 ))

    echo ""
    draw_line
    echo -e "${W}[📊] RINGKASAN SESI${NC}"
    draw_line
    echo -e "   👤 Eksekutor     : ${BOLD}$EXECUTOR${NC}"
    echo -e "   📺 Channel       : ${#TARGET_CHANNELS[@]} channel"
    echo -e "   📹 Total video   : ~$total_videos video"
    echo -e "   🎬 Tipe konten   : $CONTENT_LABEL"
    echo -e "   ⚡ Mode speed    : $JOB_LABEL"
    echo -e "   ⏱️  Estimasi      : ~${est_min} menit ${est_sek} detik"
    echo -e "${DIM}   (estimasi kasar, tergantung koneksi dan ketersediaan transkrip)${NC}"
    draw_line
}

# ==============================================================================
# JALANKAN ENGINE PYTHON
# ==============================================================================
run_engine() {
    local channel="$1"
    local limit="$2"
    local start_from="${CHECKPOINT_START[$channel]:-0}"
    local mode="$3"

    termux-wake-lock 2>/dev/null || true

    python3 "$PYTHON_ENGINE" \
        --channel "$channel" \
        --limit "$limit" \
        --jobs "$MAX_JOBS" \
        --content-type "$CONTENT_TYPE" \
        --executor "$EXECUTOR" \
        --mode "$mode" \
        --start-from "$start_from" \
        --checkpoint-dir "$CHECKPOINT_DIR" \
        --config-dir "$CONFIG_DIR" \
        --webhook-url "$WEBHOOK_URL" \
        --lang "$LANG_CHOICE"

    local exit_code=$?
    termux-wake-unlock 2>/dev/null || true
    return $exit_code
}

# ==============================================================================
# MODE: TIDUR
# ==============================================================================
mode_tidur() {
    draw_box_title "💤 MODE TIDUR — Full Background" "$DIM"

    input_channels 999 "Tidur"
    input_content_type
    input_job_preset

    declare -gA CHECKPOINT_START
    for CH in "${TARGET_CHANNELS[@]}"; do
        check_checkpoint "$CH"
    done

    input_video_limits
    show_estimate "$TOTAL_VIDEOS_ALL" "$MAX_JOBS"

    echo ""
    echo -e "${W}[💤] Mode Tidur: Proses akan berjalan penuh di background.${NC}"
    echo -e "${DIM}     Laporan dikirim ke Discord saat selesai.${NC}"
    echo -e "${DIM}     Jika terjadi rate limit, notif darurat akan dikirim ke Discord.${NC}"
    echo ""
    read -rp "  ➤ Konfirmasi mulai? (y/n): " konfirm
    [[ ! "$konfirm" =~ ^[Yy]$ ]] && echo -e "${Y}Dibatalkan.${NC}" && return

    echo -e "\n${GR}[🚀] Memulai... selamat tidur nyenyak! 💤${NC}\n"

    for CH in "${TARGET_CHANNELS[@]}"; do
        run_engine "$CH" "${CHANNEL_LIMITS[$CH]}" "tidur"
    done
echo -e "\n${GR}[✅] Semua channel selesai diproses. Menutup Termux...${NC}"
    sleep 2
    exit 0
}

# ==============================================================================
# MODE: SEMI PANTAU
# ==============================================================================
mode_semi() {
    draw_box_title "⚖️  MODE SEMI PANTAU — Multi-Channel" "$Y"

    input_channels 5 "Semi Pantau"
    input_content_type
    input_job_preset

    declare -gA CHECKPOINT_START
    for CH in "${TARGET_CHANNELS[@]}"; do
        check_checkpoint "$CH"
    done

    input_video_limits
    show_estimate "$TOTAL_VIDEOS_ALL" "$MAX_JOBS"

    echo ""
    read -rp "  ➤ Mulai proses? (y/n): " konfirm
    [[ ! "$konfirm" =~ ^[Yy]$ ]] && echo -e "${Y}Dibatalkan.${NC}" && return

    # Jalankan channel satu per satu (engine Python yang handle display ringkas)
    for CH in "${TARGET_CHANNELS[@]}"; do
        echo -e "\n${C}[🔍] Memulai @$CH...${NC}"
        run_engine "$CH" "${CHANNEL_LIMITS[$CH]}" "semi"
    done

while true; do
        echo ""
        draw_line
        echo -e "${W}[🔄] Sesi selesai! Mau cari lagi?${NC}"
        echo -e "   ${C}1.${NC} Cari channel baru"
        echo -e "   ${C}2.${NC} Ulangi channel yang sama"
        echo -e "   ${C}3.${NC} Kembali ke menu utama"
        read -rp "  ➤ Pilihan (1/2/3): " next_semi

        case "$next_semi" in
            1) mode_semi ; return ;;
            2)
                declare -gA CHECKPOINT_START
                for CH in "${TARGET_CHANNELS[@]}"; do
                    CHECKPOINT_START[$CH]=0
                done
                for CH in "${TARGET_CHANNELS[@]}"; do
                    echo -e "\n${C}[🔍] Mengulang @$CH...${NC}"
                    run_engine "$CH" "${CHANNEL_LIMITS[$CH]}" "semi"
                done
                ;;
            3) return ;;
            *) echo -e "${Y}Pilihan tidak valid.${NC}" ;;
        esac
    done
}

# ==============================================================================
# MODE: PANTAU
# ==============================================================================
mode_pantau() {
    draw_box_title "👁️  MODE PANTAU — Live Dashboard" "$GR"

    input_channels 999 "Pantau"
    input_content_type
    input_job_preset

    declare -gA CHECKPOINT_START
    for CH in "${TARGET_CHANNELS[@]}"; do
        check_checkpoint "$CH"
    done

    input_video_limits
    show_estimate "$TOTAL_VIDEOS_ALL" "$MAX_JOBS"

    echo ""
    read -rp "  ➤ Mulai proses? (y/n): " konfirm
    [[ ! "$konfirm" =~ ^[Yy]$ ]] && echo -e "${Y}Dibatalkan.${NC}" && return

    for CH in "${TARGET_CHANNELS[@]}"; do
        echo -e "\n${GR}[👁️] Mode Pantau aktif untuk @$CH${NC}"
        run_engine "$CH" "${CHANNEL_LIMITS[$CH]}" "pantau"
    done

    # Setelah selesai, tanya lagi
    echo ""
    draw_line
    echo -e "${W}[🔄] Sesi selesai! Mau apa selanjutnya?${NC}"
    echo -e "   ${C}1.${NC} Cari channel lain"
    echo -e "   ${C}2.${NC} Ulangi channel yang sama"
    echo -e "   ${C}3.${NC} Kembali ke menu utama"
    read -rp "  ➤ Pilihan (1/2/3): " next_action

    case "$next_action" in
        1) mode_pantau ;;
        2)
            declare -gA CHECKPOINT_START
            for CH in "${TARGET_CHANNELS[@]}"; do
                CHECKPOINT_START[$CH]=0
            done
            for CH in "${TARGET_CHANNELS[@]}"; do
                run_engine "$CH" "${CHANNEL_LIMITS[$CH]}" "pantau"
            done
            ;;
        *) return ;;
    esac
}

# ==============================================================================
# MODE: INDEX (Channel Besar)
# ==============================================================================
mode_index() {
    draw_box_title "📦 INDEX MODE — Channel Besar" "$C"
 
    local INDEX_ENGINE="$SCRIPT_DIR/cs20_index_engine.py"
 
    # Cek engine tersedia
    if [ ! -f "$INDEX_ENGINE" ]; then
        echo -e "${R}[❌] File cs20_index_engine.py tidak ditemukan!${NC}"
        echo -e "${Y}     Pastikan cs20_index_engine.py dan cs20_index_parser.py${NC}"
        echo -e "${Y}     ada di folder yang sama dengan cs20.sh${NC}"
        sleep 2
        return
    fi
 
    # ── Input channel ────────────────────────────────────────────────
    echo ""
    draw_line
    echo -e "${W}[📺] INPUT TARGET CHANNEL${NC}"
    echo -e "${DIM}   Format: nama channel tanpa '@' (contoh: r_perjuangan)${NC}"
    draw_line
    read -rp "  ➤ Channel: " CH_INPUT
    CH_INPUT="${CH_INPUT#@}"
    CH_INPUT="${CH_INPUT// /}"
 
    if [ -z "$CH_INPUT" ]; then
        echo -e "${R}[❌] Channel tidak boleh kosong!${NC}"
        return
    fi
 
    # ── Cek sesi existing ────────────────────────────────────────────
    # Deteksi cache root (sama dengan logic Python)
    local SHARED="$HOME/storage/shared"
    if [ -d "$SHARED" ]; then
        local CACHE_ROOT="$SHARED/CS20_Index"
    else
        local CACHE_ROOT="$HOME/.cs20/index_cache"
    fi
    local SESSION_META="$CACHE_ROOT/$CH_INPUT/meta.json"
    local SESSION_EXISTS=0
    local START_BATCH=1
 
    if [ -f "$SESSION_META" ]; then
        SESSION_EXISTS=1
        local META_TOTAL META_DONE META_BATCHES
        META_INFO=$(python3 - "$SESSION_META" <<'PYEOF'
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    batches    = d.get("batches", [])
    total_b    = len(batches)
    done_b     = sum(1 for b in batches if b.get("status") == "done")
    pending_b  = next(
        (b["batch_no"] for b in batches if b.get("status") == "pending"), total_b + 1
    )
    total_v    = d.get("total_videos", 0)
    created    = d.get("created_at", "?")
    print(f"{total_b}|{done_b}|{pending_b}|{total_v}|{created}")
except Exception as e:
    print(f"0|0|1|0|?")
PYEOF
)
        IFS='|' read -r META_TB META_DB META_NB META_TV META_CA <<< "$META_INFO"
 
        echo ""
        echo -e "${Y}[💾] SESI EXISTING DITEMUKAN untuk @${CH_INPUT}${NC}"
        echo -e "   Total video  : ${W}${META_TV}${NC}"
        echo -e "   Total batch  : ${W}${META_TB}${NC}"
        echo -e "   Selesai      : ${GR}${META_DB}${NC} batch"
        echo -e "   Dibuat       : ${DIM}${META_CA}${NC}"
        echo ""
        echo -e "   ${C}1.${NC} Lanjutkan dari batch ${META_NB}"
        echo -e "   ${C}2.${NC} Mulai sesi baru (hapus sesi lama)"
        echo -e "   ${DIM}3.${NC} Batal"
        echo ""
        read -rp "  ➤ Pilihan (1/2/3): " SESS_CHOICE
 
        case "$SESS_CHOICE" in
            1)
                START_BATCH=$META_NB
                echo -e "${GR}[✅] Melanjutkan dari batch ${START_BATCH}.${NC}"
                # Bersihkan cache batch-batch sebelumnya yang sudah selesai
                for (( b=1; b<START_BATCH; b++ )); do
                    local BATCH_CACHE="$CACHE_ROOT/$CH_INPUT/batch_$(printf '%02d' $b)"
                    if [ -d "$BATCH_CACHE" ]; then
                        rm -rf "$BATCH_CACHE"
                        echo -e "${DIM}  🗑️  Cache batch $(printf '%02d' $b) dibersihkan.${NC}"
                    fi
                done
                # Gunakan config dari sesi existing — langsung jalankan engine
                _run_index_engine "$CH_INPUT" "$START_BATCH" "" "" "" "" ""
                return
                ;;
            2)
                echo -e "${Y}  Menghapus sesi lama...${NC}"
                rm -rf "$CACHE_ROOT/$CH_INPUT"
                echo -e "${GR}  Sesi lama dihapus.${NC}"
                ;;
            3|*)
                echo -e "${Y}  Dibatalkan.${NC}"
                return
                ;;
        esac
    fi
 
    # ── Tipe konten ───────────────────────────────────────────────────
    input_content_type
 
    # ── Bahasa (sudah diset di input_language sebelumnya) ─────────────
 
    # ── Hitung video otomatis ─────────────────────────────────────────
    echo ""
    draw_line
    echo -e "${W}[📊] MENGHITUNG JUMLAH VIDEO${NC}"
    draw_line
    echo -e "   ${DIM}Mengambil playlist_count dari YouTube...${NC}"
 
    local V_COUNT
    V_COUNT=$(python3 - "$CH_INPUT" "$CONTENT_TYPE" <<'PYEOF'
import sys, subprocess
channel      = sys.argv[1]
content_type = sys.argv[2]
if content_type == "live":
    url = f"https://www.youtube.com/@{channel}/streams"
else:
    url = f"https://www.youtube.com/@{channel}/videos"
cmd = [
    "yt-dlp",
    "--playlist-items", "0",
    "--print",          "playlist_count",
    "--quiet",
    "--no-warnings",
    "--socket-timeout", "15",
    url,
]
try:
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    lines = [l.strip() for l in r.stdout.splitlines() if l.strip().isdigit()]
    print(lines[0] if lines else "0")
except Exception:
    print("0")
PYEOF
)
 
    if [[ ! "$V_COUNT" =~ ^[0-9]+$ ]] || [ "$V_COUNT" -eq 0 ]; then
        echo -e "   ${Y}Tidak bisa menghitung otomatis.${NC}"
        echo -e "   ${DIM}Masukkan perkiraan jumlah video secara manual:${NC}"
        read -rp "  ➤ Jumlah video: " V_COUNT
        if [[ ! "$V_COUNT" =~ ^[0-9]+$ ]] || [ "$V_COUNT" -eq 0 ]; then
            echo -e "${R}[❌] Input tidak valid.${NC}"
            return
        fi
    else
        echo -e "   ${GR}✓ Terdeteksi: ~${V_COUNT} video${NC}"
        echo -e "   ${DIM}(angka ini mungkin tidak akurat untuk channel 5000+ video)${NC}"
        echo -e "   ${DIM}Ketik angka untuk override, atau Enter untuk gunakan ini:${NC}"
        read -rp "  ➤ Jumlah video [${V_COUNT}]: " V_OVERRIDE
        if [[ "$V_OVERRIDE" =~ ^[0-9]+$ ]] && [ "$V_OVERRIDE" -gt 0 ]; then
            V_COUNT=$V_OVERRIDE
        fi
    fi
 
    echo -e "   ${GR}✓ Total video: ${V_COUNT}${NC}"
 
    # ── Input jumlah batch ────────────────────────────────────────────
    echo ""
    draw_line
    echo -e "${W}[📦] KONFIGURASI BATCH${NC}"
    draw_line
 
    local VPB_HINT=$(( V_COUNT / 10 ))
    echo -e "   ${DIM}Rekomendasi: 10 batch (~${VPB_HINT} video/batch)${NC}"
    echo -e "   ${DIM}Makin banyak batch = makin kecil tiap sesi = lebih aman di HP${NC}"
    echo ""
    read -rp "  ➤ Jumlah total batch: " TOTAL_BATCHES
    if [[ ! "$TOTAL_BATCHES" =~ ^[0-9]+$ ]] || [ "$TOTAL_BATCHES" -lt 1 ]; then
        TOTAL_BATCHES=10
        echo -e "   ${Y}  Input tidak valid, default: 10 batch${NC}"
    fi
 
    local VPB=$(( (V_COUNT + TOTAL_BATCHES - 1) / TOTAL_BATCHES ))
    echo -e "   ${GR}✓ ${TOTAL_BATCHES} batch × ~${VPB} video/batch${NC}"
 
    # ── Berapa batch sekaligus? ───────────────────────────────────────
    echo ""
    echo -e "   ${DIM}Proses berapa batch sekaligus sebelum pause?${NC}"
    echo -e "   ${DIM}(Misal: 2 = proses 2 batch, pause, tanya lanjut atau tidak)${NC}"
    read -rp "  ➤ Batch per run: " BATCHES_PER_RUN
    if [[ ! "$BATCHES_PER_RUN" =~ ^[0-9]+$ ]] || [ "$BATCHES_PER_RUN" -lt 1 ]; then
        BATCHES_PER_RUN=2
        echo -e "   ${Y}  Input tidak valid, default: 2${NC}"
    fi
    if [ "$BATCHES_PER_RUN" -gt "$TOTAL_BATCHES" ]; then
        BATCHES_PER_RUN=$TOTAL_BATCHES
    fi
 
    # ── Kecepatan (cap 3 worker) ──────────────────────────────────────
    echo ""
    draw_line
    echo -e "${W}[⚡] MODE KECEPATAN — INDEX MODE${NC}"
    echo -e "${DIM}   Max 3 worker untuk keamanan rate limit${NC}"
    draw_line
    echo -e "   ${C}1.${NC} 🐢 AMAN    — 1 worker  ${DIM}(HP kentang / koneksi lemah)${NC}"
    echo -e "   ${C}2.${NC} ⚖️  BALANCE — 2 worker  ${DIM}(default, direkomendasikan)${NC}"
    echo -e "   ${C}3.${NC} 🚀 TURBO   — 3 worker  ${DIM}(koneksi stabil)${NC}"
    echo ""
    read -rp "  ➤ Pilihan (1/2/3): " SPEED_INPUT
    case "$SPEED_INPUT" in
        1) INDEX_JOBS=1 ; INDEX_JOB_LABEL="🐢 AMAN (1 worker)" ;;
        3) INDEX_JOBS=3 ; INDEX_JOB_LABEL="🚀 TURBO (3 worker)" ;;
        *) INDEX_JOBS=2 ; INDEX_JOB_LABEL="⚖️ BALANCE (2 worker)" ;;
    esac
    echo -e "${GR}[✅] Kecepatan: $INDEX_JOB_LABEL${NC}"
 
    # ── Ringkasan & konfirmasi ────────────────────────────────────────
    echo ""
    draw_line
    echo -e "${W}[📋] RINGKASAN INDEX MODE${NC}"
    draw_line
    echo -e "   👤 Eksekutor    : ${BOLD}$EXECUTOR${NC}"
    echo -e "   📺 Channel      : ${C}@${CH_INPUT}${NC}"
    echo -e "   🎬 Tipe konten  : $CONTENT_LABEL"
    echo -e "   🌐 Bahasa       : $LANG_CHOICE"
    echo -e "   📹 Total video  : ~${V_COUNT}"
    echo -e "   📦 Total batch  : ${TOTAL_BATCHES} batch (~${VPB} video/batch)"
    echo -e "   🔁 Batch/run    : ${BATCHES_PER_RUN} batch sekaligus"
    echo -e "   ⚡ Kecepatan    : $INDEX_JOB_LABEL"
    echo -e "   💾 Cache dir    : ${DIM}${CACHE_ROOT}/${CH_INPUT}${NC}"
    draw_line
    echo ""
    read -rp "  ➤ Mulai Index Mode? (y/n): " KONFIRM_INDEX
    [[ ! "$KONFIRM_INDEX" =~ ^[Yy]$ ]] && echo -e "${Y}Dibatalkan.${NC}" && return
 
    # ── Jalankan engine ───────────────────────────────────────────────
    _run_index_engine \
        "$CH_INPUT" \
        "$START_BATCH" \
        "$V_COUNT" \
        "$TOTAL_BATCHES" \
        "$BATCHES_PER_RUN" \
        "$INDEX_JOBS" \
        "$CONTENT_TYPE"
}
 
# ── Helper: jalankan cs20_index_engine.py ────────────────────────────────────
_run_index_engine() {
    local channel="$1"
    local start_batch="$2"
    local total_videos="$3"
    local total_batches="$4"
    local batches_per_run="$5"
    local jobs="$6"
    local content_type_arg="$7"
 
    # Kalau lanjut sesi existing, baca config dari meta.json
    if [ -z "$total_batches" ] || [ "$total_batches" = "" ]; then
        local SHARED="$HOME/storage/shared"
        [ -d "$SHARED" ] && local CROOT="$SHARED/CS20_Index" || local CROOT="$HOME/.cs20/index_cache"
        META_INFO=$(python3 - "$CROOT/$channel/meta.json" <<'PYEOF'
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    print(f"{d.get('total_videos',0)}|{d.get('total_batches',10)}|{d.get('batches_per_run',2)}|{d.get('max_workers',2)}|{d.get('content_type','video')}")
except:
    print("0|10|2|2|video")
PYEOF
)
        IFS='|' read -r total_videos total_batches batches_per_run jobs content_type_arg <<< "$META_INFO"
    fi
 
    termux-wake-lock 2>/dev/null || true
 
    python3 "$SCRIPT_DIR/cs20_index_engine.py" \
        --channel         "$channel" \
        --content-type    "${content_type_arg:-$CONTENT_TYPE}" \
        --executor        "$EXECUTOR" \
        --lang            "${LANG_CHOICE:-id}" \
        --webhook-url     "$WEBHOOK_URL" \
        --config-dir      "$CONFIG_DIR" \
        --jobs            "${jobs:-2}" \
        --total-videos    "${total_videos:-0}" \
        --total-batches   "${total_batches:-10}" \
        --batches-per-run "${batches_per_run:-2}" \
        --start-batch     "${start_batch:-1}"
 
    termux-wake-unlock 2>/dev/null || true
}

# ==============================================================================
# MENU: LOG BLOCKED VIDEO
# ==============================================================================
menu_blocked_log() {
    show_banner
    draw_box_title "📋 LOG BLOCKED & ERROR VIDEO" "$C"

    local LOG_FILES=()
    while IFS= read -r -d '' f; do
        LOG_FILES+=("$f")
    done < <(find "$CONFIG_DIR" -maxdepth 1 -name "*_blocked.json" -print0 2>/dev/null)

    if [ ${#LOG_FILES[@]} -eq 0 ]; then
        echo -e "${Y}  Tidak ada log blocked/error video.${NC}"
        echo ""
        read -rp "  ➤ Tekan Enter untuk kembali..." _
        return
    fi

    echo -e "${W}  Log yang tersedia:${NC}"
    echo ""
    for i in "${!LOG_FILES[@]}"; do
        local f="${LOG_FILES[$i]}"
        local info
        info=$(python3 - "$f" <<'PYEOF'
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    vids = d.get('videos', [])
    total = len(vids)
    blocked = sum(1 for v in vids if not v.get('reason','').startswith(('network','unknown','rate_limit')))
    network = sum(1 for v in vids if v.get('reason','').startswith('network'))
    unknown = sum(1 for v in vids if v.get('reason','').startswith('unknown'))
    ratelimit = sum(1 for v in vids if v.get('reason','').startswith('rate_limit'))
    ch = d.get('channel','?')
    cr = d.get('created_at','?')
    print(f"{ch}|{total}|{blocked}|{network}|{unknown}|{ratelimit}|{cr}")
except Exception as e:
    print(f"?|0|0|0|0|0|?")
PYEOF
)
        IFS='|' read -r ch total blocked network unknown ratelimit created <<< "$info"
        echo -e "   ${C}$((i+1)).${NC} @${ch}  ${W}${total} video${NC}"
        echo -e "      ${DIM}blocked:${NC}${R}${blocked}${NC}  ${DIM}network:${NC}${Y}${network}${NC}  ${DIM}unknown:${NC}${Y}${unknown}${NC}  ${DIM}ratelimit:${NC}${Y}${ratelimit}${NC}"
        echo -e "      ${DIM}dibuat: ${created}${NC}"
        echo ""
    done

    echo -e "   ${R}H.${NC}  Hapus semua log"
    echo -e "   ${DIM}0.${NC}  Kembali ke menu utama"
    echo ""
    draw_line
    read -rp "  ➤ Pilihan: " log_input

    case "$log_input" in
        0) return ;;
        H|h)
            read -rp "  ➤ Yakin hapus semua log? (y/n): " konfirm_hapus
            if [[ "$konfirm_hapus" =~ ^[Yy]$ ]]; then
                rm -f "$CONFIG_DIR"/*_blocked.json
                echo -e "${GR}  Semua log dihapus.${NC}"
            else
                echo -e "${Y}  Dibatalkan.${NC}"
            fi
            sleep 1
            menu_blocked_log
            return
            ;;
        *)
            if ! [[ "$log_input" =~ ^[0-9]+$ ]] || \
               [ "$log_input" -lt 1 ] || \
               [ "$log_input" -gt "${#LOG_FILES[@]}" ]; then
                echo -e "${R}  Pilihan tidak valid.${NC}"
                sleep 1
                menu_blocked_log
                return
            fi

            local selected="${LOG_FILES[$((log_input-1))]}"
            local sel_info
            sel_info=$(python3 - "$selected" <<'PYEOF'
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    vids = d.get('videos', [])
    total = len(vids)
    ch = d.get('channel','?')
    lang = d.get('lang','id')
    print(f"{ch}|{total}|{lang}")
except:
    print("?|0|id")
PYEOF
)
            IFS='|' read -r sel_channel video_count sel_lang <<< "$sel_info"

            echo ""
            echo -e "${W}  Channel  : @${sel_channel}${NC}"
            echo -e "${W}  Videos   : ${video_count} video di log${NC}"
            echo -e "${W}  Lang     : ${sel_lang}${NC}"
            echo ""
            echo -e "   ${C}1.${NC} Scan ulang sekarang"
            echo -e "   ${R}2.${NC} Hapus log ini"
            echo -e "   ${DIM}3.${NC} Kembali"
            echo ""
            read -rp "  ➤ Pilihan (1/2/3): " aksi

            case "$aksi" in
                1)
                    echo -e "\n${GR}[🔄] Memulai scan ulang @${sel_channel} (${video_count} video)...${NC}\n"
                    termux-wake-lock 2>/dev/null || true
                    python3 "$PYTHON_ENGINE" \
                        --channel "$sel_channel" \
                        --retry-blocked-log "$selected" \
                        --webhook-url "$WEBHOOK_URL" \
                        --config-dir "$CONFIG_DIR" \
                        --checkpoint-dir "$CHECKPOINT_DIR" \
                        --executor "$EXECUTOR" \
                        --lang "$sel_lang" \
                        --mode "semi"
                    termux-wake-unlock 2>/dev/null || true

                    # Cek apakah masih ada sisa error di log baru
                    local new_log="$CONFIG_DIR/${sel_channel}_blocked.json"
                    local sisa=0
                    if [ -f "$new_log" ]; then
                        sisa=$(python3 -c "
import json
try:
    d = json.load(open('$new_log'))
    print(len(d.get('videos', [])))
except:
    print(0)
")
                    fi

                    # Hapus log lama yang kita retry
                    rm -f "$selected"

                    if [ "$sisa" -gt 0 ]; then
                        echo ""
                        echo -e "${Y}  ⚠ Masih ada ${sisa} video yang error setelah retry.${NC}"
                        echo -e "${W}  Mau apa dengan sisa error ini?${NC}"
                        echo -e "   ${C}1.${NC} Simpan ke log baru (retry lagi nanti)"
                        echo -e "   ${R}2.${NC} Hapus saja, lupakan"
                        echo ""
                        read -rp "  ➤ Pilihan (1/2): " sisa_aksi
                        case "$sisa_aksi" in
                            1)
                                echo -e "${GR}  Log sisa disimpan: ${new_log}${NC}"
                                echo -e "${DIM}  Bisa di-retry lagi dari menu ini kapan saja.${NC}"
                                ;;
                            2)
                                rm -f "$new_log"
                                echo -e "${GR}  Log sisa dihapus.${NC}"
                                ;;
                            *)
                                echo -e "${Y}  Pilihan tidak valid — log disimpan.${NC}"
                                ;;
                        esac
                    else
                        echo -e "${GR}  Semua video berhasil di-scan ulang, tidak ada sisa error!${NC}"
                    fi

                    sleep 2
                    menu_blocked_log
                    ;;
                2)
                    rm -f "$selected"
                    echo -e "${GR}  Log dihapus.${NC}"
                    sleep 1
                    menu_blocked_log
                    ;;
                3) menu_blocked_log ;;
                *) menu_blocked_log ;;
            esac
            ;;
    esac
}

# ==============================================================================
# MODE: RECOVERY AGE RESTRICTED
# ==============================================================================
mode_age_restricted() {
    local AGE_ENGINE="$SCRIPT_DIR/cs20_age_engine.py"

    # Cek engine tersedia
    if [ ! -f "$AGE_ENGINE" ]; then
        echo -e "${R}[❌] File cs20_age_engine.py tidak ditemukan!${NC}"
        echo -e "${Y}     Pastikan cs20_age_engine.py ada di folder yang sama dengan cs20.sh${NC}"
        sleep 2
        return
    fi

    draw_box_title "🔞 RECOVERY AGE RESTRICTED — Bypass Mode" "$R"

    # Input channel (boleh kosong — engine akan tanya sendiri jika ada log)
    echo ""
    draw_line
    echo -e "${W}[📺] TARGET CHANNEL${NC}"
    echo -e "${DIM}   Kosongkan + Enter jika ingin pilih dari log yang ada${NC}"
    draw_line
    read -rp "  ➤ Channel (tanpa '@', atau Enter skip): " CH_AGE
    CH_AGE="${CH_AGE#@}"
    CH_AGE="${CH_AGE// /}"

    termux-wake-lock 2>/dev/null || true

    python3 "$AGE_ENGINE" \
        --channel       "${CH_AGE:-__none__}" \
        --executor      "$EXECUTOR" \
        --lang          "${LANG_CHOICE:-id}" \
        --webhook-url   "$WEBHOOK_URL" \
        --config-dir    "$CONFIG_DIR"

    termux-wake-unlock 2>/dev/null || true

    echo ""
    draw_line
    echo -e "${W}[🔄] Sesi selesai.${NC}"
    echo -e "   ${C}1.${NC} Jalankan lagi (channel/log lain)"
    echo -e "   ${DIM}2.${NC} Kembali ke menu utama"
    read -rp "  ➤ Pilihan (1/2): " next_age
    case "$next_age" in
        1) mode_age_restricted ;;
        *) return ;;
    esac
}

# ==============================================================================
# MODE: CHATSEEKER (VTuber Live-Chat Clip Finder)
# ==============================================================================
mode_chatseeker() {
    local CS_ENGINE="$SCRIPT_DIR/chatseeker.py"

    if [ ! -f "$CS_ENGINE" ]; then
        echo -e "${R}[❌] File chatseeker.py tidak ditemukan!${NC}"
        echo -e "${Y}     Pastikan chatseeker.py ada di folder yang sama dengan cs20.sh${NC}"
        sleep 2
        return
    fi

    draw_box_title "🎬 CHATSEEKER — VTuber Live-Chat Clip Finder" "$M"
    echo -e "${DIM}   Engine & keyword terpisah dari Fast Search, tidak diubah sama sekali.${NC}"
    echo ""

    termux-wake-lock 2>/dev/null || true

    # chatseeker.py sepenuhnya interaktif sendiri (operator name, mode, channel, dst)
    # jadi cukup dipanggil langsung — tidak ada argumen yang disuntik dari sini.
    python3 "$CS_ENGINE"
    local cs_exit=$?

    termux-wake-unlock 2>/dev/null || true

    if [ $cs_exit -ne 0 ]; then
        echo ""
        echo -e "${Y}[⚠️] ChatSeeker berhenti dengan exit code $cs_exit.${NC}"
        echo -e "${DIM}     Kemungkinan penyebab umum:${NC}"
        echo -e "${DIM}     • Video/live yang dipilih tidak punya live chat (VOD tanpa replay chat)${NC}"
        echo -e "${DIM}     • Koneksi terputus saat fetch transcript${NC}"
        echo -e "${DIM}     • Cookies kadaluarsa (kalau video age-restricted)${NC}"
    fi

    echo ""
    draw_line
    echo -e "${W}[🔄] Sesi ChatSeeker selesai.${NC}"
    echo -e "   ${C}1.${NC} Jalankan lagi"
    echo -e "   ${DIM}2.${NC} Kembali ke menu utama"
    read -rp "  ➤ Pilihan (1/2): " next_cs
    case "$next_cs" in
        1) mode_chatseeker ;;
        *) return ;;
    esac
}

# ==============================================================================
# MODE: AUTO DRIVE (Discovery channel baru otomatis)
# ==============================================================================
mode_autodrive() {
    local AD_ENGINE="$SCRIPT_DIR/cs20_autodrive_engine.py"

    if [ ! -f "$AD_ENGINE" ]; then
        echo -e "${R}[❌] File cs20_autodrive_engine.py tidak ditemukan!${NC}"
        echo -e "${Y}     Pastikan file ada di folder yang sama dengan cs20.sh${NC}"
        sleep 2
        return
    fi

    draw_box_title "🚗 AUTO DRIVE — Channel Discovery Otomatis" "$M"
    echo -e "${DIM}   Nyari channel baru otomatis via search, scan pakai engine utama.${NC}"
    echo -e "${DIM}   Fokus transcript (cs20_engine.py) — BUKAN chatseeker.${NC}"
    echo ""
    echo -e "   ${C}1.${NC} Mulai sesi baru"
    echo -e "   ${C}2.${NC} 🗑️  Hapus history (per-bahasa)"
    echo -e "   ${DIM}3.${NC}    Kembali ke menu utama"
    echo ""
    read -rp "  ➤ Pilihan (1-3): " ad_choice

    case "$ad_choice" in
        1) : ;;   # lanjut ke bawah
        2) autodrive_clear_history; return ;;
        *) return ;;
    esac

    # ── Pilih bahasa (reuse input_language, sets LANG_CHOICE & WEBHOOK_URL) ──
    input_language

    # ── Query custom (SESI INI SAJA, tidak ditulis ke SEED_QUERIES) ────────
    echo ""
    echo -e "${W}[🔎] QUERY PENCARIAN${NC}"
    echo -e "   ${DIM}Kosongkan untuk pakai seed query bawaan bahasa ini.${NC}"
    echo -e "   ${DIM}Isi buat query custom sesi ini saja (gak disimpan permanen).${NC}"
    echo -e "   ${DIM}Pisah pakai '|' kalau mau lebih dari 1 variasi.${NC}"
    read -rp "  ➤ Query custom (opsional): " AD_CUSTOM_QUERY

    # ── Rentang waktu upload ──────────────────────────────────────────────
    echo ""
    echo -e "${W}[⏱️] RENTANG WAKTU UPLOAD${NC}"
    echo -e "   ${C}1.${NC} Semua waktu (tanpa filter)"
    echo -e "   ${C}2.${NC} 24 jam terakhir"
    echo -e "   ${C}3.${NC} 7 hari terakhir"
    echo -e "   ${C}4.${NC} 1 bulan terakhir"
    echo -e "   ${C}5.${NC} 1 tahun terakhir"
    read -rp "  ➤ Pilihan (1-5): " tr_choice
    case "$tr_choice" in
        1) AD_TIME_RANGE="all" ;;
        2) AD_TIME_RANGE="1d" ;;
        3) AD_TIME_RANGE="7d" ;;
        4) AD_TIME_RANGE="1m" ;;
        5) AD_TIME_RANGE="1y" ;;
        *) echo -e "${Y}Default: semua waktu.${NC}"; AD_TIME_RANGE="all" ;;
    esac

    # ── Limit video per channel baru ──────────────────────────────────────
    echo ""
    echo -e "${W}[🎬] LIMIT VIDEO PER CHANNEL BARU${NC}"
    echo -e "   ${DIM}Isi angka, atau 0 untuk SEMUA arsip live (unlimited).${NC}"
    read -rp "  ➤ Limit (default 10, 0=semua): " ad_limit
    [[ "$ad_limit" =~ ^[0-9]+$ ]] || ad_limit=10

    # ── Max siklus (kosong = tanpa batas) ──────────────────────────────────
    read -rp "  ➤ Max siklus, kosongkan untuk tanpa batas: " ad_max_cycles
    [[ "$ad_max_cycles" =~ ^[0-9]+$ ]] || ad_max_cycles=0

    echo ""
    echo -e "${GR}[✅] Konfigurasi:${NC}"
    echo -e "   Bahasa         : $LANG_CHOICE"
    echo -e "   Query          : ${AD_CUSTOM_QUERY:-(bawaan/default)}"
    echo -e "   Rentang waktu  : $AD_TIME_RANGE"
    echo -e "   Limit/channel  : $([ "$ad_limit" = "0" ] && echo "SEMUA (unlimited)" || echo "$ad_limit")"
    echo -e "   Max siklus     : ${ad_max_cycles:-tanpa batas}"
    echo ""
    read -rp "  ➤ Mulai? (y/n): " confirm_ad
    if [[ ! "$confirm_ad" =~ ^[Yy]$ ]]; then
        echo -e "${DIM}Dibatalkan.${NC}"
        return
    fi

    termux-wake-lock 2>/dev/null || true

    python3 "$AD_ENGINE" \
        --lang "$LANG_CHOICE" \
        --time-range "$AD_TIME_RANGE" \
        --limit-per-channel "$ad_limit" \
        --max-cycles "$ad_max_cycles" \
        --config-dir "$CONFIG_DIR" \
        --checkpoint-dir "$CHECKPOINT_DIR" \
        --webhook-url "$WEBHOOK_URL" \
        --custom-query "$AD_CUSTOM_QUERY"
    local ad_exit=$?

    termux-wake-unlock 2>/dev/null || true

    if [ $ad_exit -ne 0 ]; then
        echo ""
        echo -e "${Y}[⚠️] Auto Drive berhenti dengan exit code $ad_exit.${NC}"
    fi

    echo ""
    draw_line
    echo -e "${W}[🔄] Sesi Auto Drive selesai.${NC}"
    echo -e "   ${C}1.${NC} Kembali ke menu Auto Drive"
    echo -e "   ${DIM}2.${NC} Kembali ke menu utama"
    read -rp "  ➤ Pilihan (1/2): " next_ad
    case "$next_ad" in
        1) mode_autodrive ;;
        *) return ;;
    esac
}

autodrive_clear_history() {
    local AD_ENGINE="$SCRIPT_DIR/cs20_autodrive_engine.py"
    input_language
    echo ""
    echo -e "${R}[⚠️] Ini akan menghapus history Auto Drive untuk bahasa '$LANG_CHOICE'.${NC}"
    echo -e "${Y}     Channel yang sudah pernah di-scan akan dianggap BARU lagi.${NC}"
    read -rp "  ➤ Yakin hapus? Ketik 'HAPUS' untuk konfirmasi: " confirm_del
    if [ "$confirm_del" != "HAPUS" ]; then
        echo -e "${DIM}Dibatalkan.${NC}"
        sleep 1
        return
    fi
    python3 "$AD_ENGINE" --lang "$LANG_CHOICE" --config-dir "$CONFIG_DIR" \
        --checkpoint-dir "$CHECKPOINT_DIR" --clear-history
    sleep 2
}

# ==============================================================================
# MENU UTAMA
# ==============================================================================
main_menu() {
    show_banner
    load_profile
    input_language
    echo ""
    draw_line
    echo -e "${W}[🎯] PILIH MODE OPERASI${NC}"
    draw_line
    echo -e ""
    echo -e "   ${GR}1.${NC} ⚡ ${BOLD}FAST SEARCH${NC}  — Live dashboard, unlimited channel"
    echo -e "         ${DIM}Real-time stats, live hit counter, notif Discord otomatis${NC}"
    echo ""
    echo -e "   ${DIM}2.${NC}    Hapus profile (ganti nama alias)"
    echo -e "   ${DIM}3.${NC}    Keluar"
    echo -e "   ${C}4.${NC} 📋 Log Blocked Video"
    echo -e "   ${C}5.${NC} 📦 Index Mode  ${DIM}(channel besar 1000+ video)${NC}"
    echo -e "   ${R}6.${NC} 🔞 ${BOLD}RECOVERY AGE${NC}  — Bypass video age-restricted"
    echo -e "         ${DIM}Bypass via cookies, auto-detect log dari mode lain${NC}"
    echo -e "   ${M}7.${NC} 🎬 ${BOLD}CHATSEEKER${NC}  — VTuber live-chat clip finder"
    echo -e "         ${DIM}Engine terpisah, keyword & logika sendiri${NC}"
    echo -e "   ${GR}8.${NC} 🚗 ${BOLD}AUTO DRIVE${NC}  — Discovery channel baru otomatis"
    echo -e "         ${DIM}Search massal + dedup history, pakai engine utama${NC}"
    echo ""
    draw_line
    read -rp "  ➤ Pilihan: " MENU_INPUT

    case "$MENU_INPUT" in
        1) mode_pantau ;;
        2)
            rm -f "$PROFILE_FILE"
            echo -e "${GR}Profile dihapus. Restart skrip untuk buat profile baru.${NC}"
            exit 0
            ;;
        3) echo -e "${DIM}Sampai jumpa!${NC}" ; exit 0 ;;
        4) menu_blocked_log ;;
        5) mode_index ;;
        6) mode_age_restricted ;;
        7) mode_chatseeker ;;
        8) mode_autodrive ;;
        *) echo -e "${R}Pilihan tidak valid.${NC}" ; sleep 1 ; main_menu ;;
    esac
}

# ==============================================================================
# ENTRY POINT
# ==============================================================================
check_and_install_deps
mkdir -p "$CONFIG_DIR"
inject_webhook
main_menu
