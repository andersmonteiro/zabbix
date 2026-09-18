#!/usr/bin/env bash
set -euo pipefail

SRC="${1:?Uso: package-externalscripts.sh <pasta-origem> <versao ex: v1.0.0>}"
VERSION="${2:?Uso: package-externalscripts.sh <pasta-origem> <versao ex: v1.0.0>}"
OUT="externalscripts-${VERSION}.tar.gz"
WORKDIR=$(mktemp -d)

echo "Copiando scripts de $SRC..."
cp -r "$SRC" "$WORKDIR/externalscripts"

echo "Removendo lixo temporário (tmp/, .swp)..."
rm -rf "$WORKDIR/externalscripts/tmp"
find "$WORKDIR/externalscripts" -name '*.swp' -delete

echo "Removendo símbolos de debug dos binários (strip)..."
find "$WORKDIR/externalscripts" -maxdepth 1 -type f -perm -u+x -print0 \
    | while IFS= read -r -d '' bin; do
        if file "$bin" | grep -q 'ELF'; then
            strip --strip-debug "$bin" 2>/dev/null || true
        fi
    done

echo "Empacotando em $OUT..."
tar czf "$OUT" -C "$WORKDIR" externalscripts

CHECKSUM=$(sha256sum "$OUT" | cut -d' ' -f1)
echo "$CHECKSUM  $OUT" > "$OUT.sha256"

rm -rf "$WORKDIR"
echo "Pronto: $OUT ($(du -h "$OUT" | cut -f1)), sha256: $CHECKSUM"
