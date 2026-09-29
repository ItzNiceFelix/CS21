#!/bin/bash
# ==============================================================================
# CS21 — entry point tunggal (shim tipis)
#
# Semua logika ada di Python: `python3 -m cs_core` (menu interaktif + CLI).
# Skrip ini hanya menyiapkan PATH (Termux), lalu meneruskan argumen apa adanya.
#
#   bash cs20.sh                 -> menu interaktif
#   bash cs20.sh doctor --fix    -> perbaiki dependensi
#   bash cs20.sh scan --channel windahbasudara --limit 5
#
# Webhook tetap dari .cs20/.webhook_injected (dibuat oleh inject_webhook.sh).
# ==============================================================================

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Termux: pastikan binary pkg/pip/yt-dlp di PATH walau dijalankan dari sh lain.
if [ -d "/data/data/com.termux/files/usr/bin" ]; then
    case ":$PATH:" in
        *":/data/data/com.termux/files/usr/bin:"*) ;;
        *) PATH="/data/data/com.termux/files/usr/bin:$PATH" ;;
    esac
fi
export PATH

# Home yang benar saat dijalankan lewat proot/su (config & storage ikut HOME).
if [ -n "${TERMUX_HOME:-}" ]; then
    export HOME="$TERMUX_HOME"
fi

cd "$SCRIPT_DIR" || exit 1

if ! command -v python3 >/dev/null 2>&1; then
    printf '\033[0;31m[✗] python3 tidak ditemukan.\033[0m\n' >&2
    printf '\033[0;33m    Termux: pkg install python\033[0m\n' >&2
    exit 4
fi

exec python3 -m cs_core "$@"
