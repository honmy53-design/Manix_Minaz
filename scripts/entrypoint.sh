#!/bin/sh
# مانیکس / Manix entrypoint; trusted owner only.
set -eu
umask 077
DATA_DIR="${DATA_DIR:-/data}"
case "$DATA_DIR" in
  /|/app|/etc|/usr|'') echo "Unsafe DATA_DIR" >&2; exit 1 ;;
esac
if [ "$(id -u)" = "0" ]; then
  mkdir -p "$DATA_DIR"
  chown panel:panel "$DATA_DIR"
  for name in server panel engines backups exports tmp; do
    if [ -L "$DATA_DIR/$name" ]; then
      echo "Refusing symlink data directory: $name" >&2; exit 1
    fi
    mkdir -p "$DATA_DIR/$name"
    chown panel:panel "$DATA_DIR/$name"
  done
  exec gosu panel "$@"
fi
exec "$@"
