"""Servidor del auditor.

Uso local:      python3 server.py            ->  http://localhost:4274
En un servidor: define PORT (y HOST=0.0.0.0), CLAVE_ACCESO, OPENAI_API_KEY y SERPER_API_KEY.

El análisis tarda minutos, así que se lanza como trabajo en segundo plano:
  GET /api/audit?url=&ciudad=&tratamiento=&negocio=&modo=   -> {"id": "..."}
  GET /api/estado?id=...                                     -> {"estado": "en_cola|en_marcha|hecho", "resultado": {...}}
  GET /api/config                                            -> qué fuentes hay disponibles y si hace falta contraseña
"""
import hmac
import json
import os
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
from audit import capacidades, comparar  # noqa: E402

PUERTO = int(os.environ.get("PORT", "4274"))
EN_SERVIDOR = bool(os.environ.get("RENDER") or os.environ.get("HOST"))
HOST = os.environ.get("HOST") or ("0.0.0.0" if os.environ.get("RENDER") else "127.0.0.1")
CLAVE = os.environ.get("CLAVE_ACCESO", "").strip()
SIMULTANEOS = threading.Semaphore(int(os.environ.get("ANALISIS_SIMULTANEOS", "2")))
TRABAJOS, CERROJO = {}, threading.Lock()


def lanzar(args):
    ident = uuid.uuid4().hex
    with CERROJO:
        ahora = time.time()
        for k in [k for k, t in TRABAJOS.items() if ahora - t["creado"] > 3600]:
            del TRABAJOS[k]
        TRABAJOS[ident] = {"estado": "en_cola", "resultado": None, "creado": ahora}

    def correr():
        with SIMULTANEOS:
            TRABAJOS[ident]["estado"] = "en_marcha"
            try:
                r = comparar(*args)
            except Exception as e:
                r = {"error": f"Error inesperado al analizar la web: {e}"}
            TRABAJOS[ident].update(estado="hecho", resultado=r)

    threading.Thread(target=correr, daemon=True).start()
    return ident


class Manejador(BaseHTTPRequestHandler):
    def _enviar(self, codigo, cuerpo, tipo, con_cuerpo=True):
        self.send_response(codigo)
        self.send_header("Content-Type", tipo + "; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if con_cuerpo:
            self.wfile.write(cuerpo)

    def _json(self, datos, codigo=200):
        self._enviar(codigo, json.dumps(datos, ensure_ascii=False).encode("utf-8"), "application/json")

    def _autorizado(self):
        return not CLAVE or hmac.compare_digest(self.headers.get("X-Clave", "").encode(), CLAVE.encode())

    def do_HEAD(self):
        self._enviar(200, b"", "text/html", con_cuerpo=False)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ("/", "/index.html"):
            with open(os.path.join(AQUI, "index.html"), "rb") as f:
                return self._enviar(200, f.read(), "text/html")
        if u.path == "/api/config":
            return self._json(dict(capacidades(), clave=bool(CLAVE), servidor=EN_SERVIDOR))
        if u.path in ("/api/audit", "/api/estado") and not self._autorizado():
            return self._json({"error": "Contraseña incorrecta."}, 401)
        q = parse_qs(u.query)
        uno = lambda k, d="": (q.get(k) or [d])[0].strip()
        if u.path == "/api/audit":
            url, ciudad, tratamiento = uno("url"), uno("ciudad"), uno("tratamiento")
            if not url or not ciudad or not tratamiento:
                return self._json({"error": "Faltan datos: web, ciudad y tratamiento son obligatorios."})
            if max(len(url), len(ciudad), len(tratamiento)) > 200:
                return self._json({"error": "Alguno de los datos es demasiado largo."})
            negocio = uno("negocio", "clínica dental")
            negocio = negocio if negocio in ("clínica dental", "laboratorio dental") else "clínica dental"
            modo = uno("modo", "ambos")
            modo = modo if modo in ("ambos", "google", "ia") else "ambos"
            return self._json({"id": lanzar((url, ciudad, tratamiento, negocio, modo))})
        if u.path == "/api/estado":
            t = TRABAJOS.get(uno("id"))
            if not t:
                return self._json({"error": "Ese análisis ya no está disponible. Lánzalo de nuevo."})
            return self._json({"estado": t["estado"], "resultado": t["resultado"]})
        self._enviar(404, b"No encontrado", "text/plain")

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))


if __name__ == "__main__":
    print(f"Auditor de posicionamiento en http://{HOST}:{PUERTO}  |  fuentes: {capacidades()}", flush=True)
    ThreadingHTTPServer((HOST, PUERTO), Manejador).serve_forever()
