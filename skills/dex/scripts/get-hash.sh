#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
SKILL_DIR=$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)
HASH_FILE="${SKILL_DIR}/.hash"

generate_hash() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 32
    return
  fi

  if command -v xxd >/dev/null 2>&1 && [ -r /dev/urandom ]; then
    head -c 32 /dev/urandom | xxd -p -c 256
    return
  fi

  echo "Error: unable to generate dex skill hash; need openssl or xxd with /dev/urandom" >&2
  exit 1
}

normalize_hash() {
  tr -d '\r\n' | tr 'A-F' 'a-f'
}

is_valid_hash() {
  printf '%s' "$1" | LC_ALL=C grep -Eq '^[0-9a-f]{64}$'
}

current_hash=""
if [ -f "$HASH_FILE" ]; then
  current_hash=$(normalize_hash < "$HASH_FILE")
fi

if ! is_valid_hash "$current_hash"; then
  current_hash=$(generate_hash | normalize_hash)
  if ! is_valid_hash "$current_hash"; then
    echo "Error: generated invalid dex skill hash" >&2
    exit 1
  fi
  umask 077
  tmp_file="${HASH_FILE}.tmp.$$"
  printf '%s\n' "$current_hash" > "$tmp_file"
  mv "$tmp_file" "$HASH_FILE"
fi

printf '%s\n' "$current_hash"
