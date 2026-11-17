#!/bin/bash
# Doble clic para arrancar el auditor y abrirlo en el navegador.
cd "$(dirname "$0")"
if ! lsof -iTCP:4274 -sTCP:LISTEN >/dev/null 2>&1; then
  python3 server.py &
  sleep 1
fi
open "http://localhost:4274"
wait
