"""Auditor de visibilidad en IA para webs de clínicas y laboratorios dentales.

Descarga la web, busca la página del tratamiento y comprueba las señales que
comparten las clínicas que salen primeras en las búsquedas hechas por IA.
Solo usa la biblioteca estándar de Python.
"""
import html as _html
import ipaddress
import socket
import json
import sys
import re
import ssl
import unicodedata
import urllib.error
import urllib.request
import os
import threading
import shutil
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse, quote_plus

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
BOTS_IA = ["GPTBot", "OAI-SearchBot", "ChatGPT-User", "ClaudeBot",
           "Claude-SearchBot", "PerplexityBot", "Google-Extended"]
TIPOS_CLINICA = {"dentist", "medicalclinic", "medicalbusiness", "localbusiness",
                 "physician", "medicalorganization", "dentallaboratory"}
PERFILES = {
    "Doctoralia": r"doctoralia\.es",
    "Top Doctors": r"topdoctors\.es",
    "Google Maps": r"g\.page|google\.[a-z.]+/maps|maps\.app\.goo\.gl|goo\.gl/maps|g\.co/kgs",
    "Trustpilot": r"trustpilot\.com",
}


# clave: (peso IA, peso Google, plazo)
PESOS = {
    "pagina": (12, 14, "mes"), "fondo": (8, 10, "mes"), "schema": (12, 8, "semana"),
    "valoracion": (8, 5, "semana"), "faq": (8, 4, "semana"), "precio": (10, 3, "mes"),
    "autoria": (10, 6, "mes"), "casos": (5, 3, "mes"), "opiniones": (7, 5, "mes"),
    "contacto": (5, 5, "semana"), "titulo": (5, 8, "semana"), "robots": (5, 0, "semana"),
    "llms": (5, 0, "semana"), "https": (0, 4, "semana"), "movil": (0, 6, "semana"),
    "sitemap": (0, 5, "semana"), "canonical": (0, 3, "semana"), "longitudes": (0, 4, "semana"),
    "alt": (0, 3, "mes"), "velocidad": (0, 4, "mes"),
}


def detectar_cms(html):
    h = html.lower()
    if "wp-content" in h or "wp-includes" in h or re.search(r'name="generator" content="wordpress', h):
        extra = "Yoast SEO" if "yoast" in h else "Rank Math" if "rank-math" in h or "rank math" in h else \
                "All in One SEO" if "aioseo" in h or "all in one seo" in h else ""
        return "wordpress", "WordPress" + (f" con {extra}" if extra else " (sin plugin de SEO detectado)"), extra
    if "wixstatic.com" in h or "wix.com" in h:
        return "wix", "Wix", ""
    for clave, nombre in (("squarespace", "Squarespace"), ("webflow", "Webflow"), ("shopify", "Shopify"),
                          ("joomla", "Joomla"), ("jimdo", "Jimdo"), ("godaddy", "GoDaddy")):
        if clave in h:
            return "otro", nombre, ""
    return "otro", "", ""


COMO = {
    "wordpress": {
        "pagina": "Páginas → Añadir nueva. Pon el titular como título de la página y añádela al menú en Apariencia → Menús.",
        "fondo": "Páginas → edita la página del tratamiento y amplía el texto con apartados (un encabezado por cada pregunta).",
        "schema": "Instala el plugin gratuito WPCode. Fragmentos de código → Cabecera y pie → pega el bloque «Dentist» del anexo en «Cabecera» y guarda.",
        "valoracion": "Va dentro del mismo bloque «Dentist»: rellena «aggregateRating» con la nota y el número reales de opiniones.",
        "faq": "{seo_faq}",
        "precio": "Edita la página del tratamiento y añade un apartado «Precio» con la cifra «desde» y qué incluye.",
        "autoria": "Edita la página del tratamiento y añade un apartado «Quién realiza el tratamiento» con nombre, titulación, universidad y número de colegiado.",
        "casos": "Edita la página y añade una galería o bloque de imágenes con un texto breve por caso.",
        "opiniones": "Edita la portada y enlaza con un botón a tu ficha de Google y a tu perfil de Doctoralia o Top Doctors.",
        "contacto": "En el editor, selecciona el teléfono, pulsa «Enlace» y escribe tel:+34 seguido del número. La dirección va en el bloque «Dentist».",
        "titulo": "{seo_titulo}",
        "longitudes": "{seo_titulo}",
        "robots": "{seo_robots}",
        "llms": "Súbelo a la carpeta principal de la web con el administrador de archivos de tu alojamiento (o por FTP).",
        "https": "En el panel de tu alojamiento activa el certificado SSL gratuito. Después, en WordPress: Ajustes → Generales, las dos direcciones deben empezar por https.",
        "movil": "Apariencia → Temas: usa un tema adaptable a móvil (todos los actuales lo son).",
        "sitemap": "{seo_sitemap}",
        "canonical": "{seo_canonical}",
        "alt": "Medios → Biblioteca → pulsa cada imagen y rellena «Texto alternativo».",
        "velocidad": "Instala un plugin de caché (por ejemplo WP Super Cache) y sube las imágenes en formato WebP.",
    },
    "wix": {
        "pagina": "En el editor: Páginas y menú → Añadir página. Pon el titular como título principal de la página.",
        "fondo": "Abre la página del tratamiento en el editor y añade bloques de texto, uno por apartado.",
        "schema": "Páginas y menú → ⋯ de la portada → Ajustes de SEO → Avanzado → Datos estructurados → Añadir nuevo marcado. Pega solo el contenido entre llaves del anexo, sin las líneas <script>.",
        "valoracion": "Va dentro del mismo marcado «Dentist»: rellena «aggregateRating» con datos reales.",
        "faq": "Mismo sitio que el anterior, en la página del tratamiento: Ajustes de SEO → Avanzado → Datos estructurados. Las preguntas deben verse también en la página.",
        "precio": "Edita la página del tratamiento y añade un apartado «Precio».",
        "autoria": "Edita la página del tratamiento y añade un apartado con quién lo realiza y su formación.",
        "casos": "Añade una galería a la página con un texto breve por caso.",
        "opiniones": "Añade en la portada botones con enlace a tu ficha de Google y a Doctoralia o Top Doctors.",
        "contacto": "Selecciona el teléfono → Enlace → Número de teléfono.",
        "titulo": "Páginas y menú → ⋯ de la portada → Ajustes de SEO → «Etiqueta de título» y «Meta descripción».",
        "longitudes": "Páginas y menú → ⋯ de la portada → Ajustes de SEO → «Etiqueta de título» y «Meta descripción».",
        "robots": "Panel de control → SEO → Herramientas de SEO → Editor de robots.txt.",
        "llms": "Wix no permite subir archivos a la carpeta principal de la web, así que este punto no se puede hacer en Wix.",
        "alt": "Pulsa la imagen → Ajustes → «¿Qué hay en la imagen?».",
        "velocidad": "Reduce vídeos, animaciones y aplicaciones instaladas en la portada.",
    },
    "otro": {},
}
COMO_GENERICO = "Pásale este punto, y el código del anexo si lo hay, a la persona o empresa que lleva tu web."


def como_hacerlo(cms, extra, clave):
    t = COMO.get(cms, {}).get(clave)
    if not t:
        return COMO_GENERICO if cms == "otro" else ""
    con = bool(extra)
    return t.format(
        seo_faq=("En el editor de la página añade el bloque «FAQ» de " + extra + ": escribe ahí las preguntas y respuestas y el marcado se crea solo."
                 if extra in ("Yoast SEO", "Rank Math") else
                 "Escribe las preguntas en la página y pega el bloque «FAQPage» del anexo con WPCode (Fragmentos de código → Cabecera y pie), o instala Yoast SEO, que trae un bloque «FAQ» que lo hace solo."),
        seo_titulo=("Edita la portada y baja hasta el cuadro de " + extra + ": rellena «Título SEO» y «Meta descripción»." if con else
                    "Instala el plugin gratuito Yoast SEO; después edita la portada y rellena «Título SEO» y «Meta descripción» en su cuadro."),
        seo_robots=("Yoast SEO → Herramientas → Editor de archivos → robots.txt." if extra == "Yoast SEO" else
                    "Rank Math → Ajustes generales → Editar robots.txt." if extra == "Rank Math" else
                    "Edita el archivo robots.txt de la carpeta principal con el administrador de archivos de tu alojamiento, o instala Yoast SEO (Herramientas → Editor de archivos)."),
        seo_sitemap=("Lo crea " + extra + " automáticamente; comprueba que esté activado en sus ajustes." if con else
                     "WordPress crea uno en /wp-sitemap.xml; comprueba que no esté desactivado, o instala Yoast SEO."),
        seo_canonical=("La pone " + extra + " automáticamente; si falta, revisa que el plugin esté activo en la portada." if con else
                       "Instala Yoast SEO: la añade automáticamente."))


def norm(s):
    s = unicodedata.normalize("NFD", s or "")
    return "".join(c for c in s if unicodedata.category(c) != "Mn").lower()


def es_direccion_publica(url):
    """Rechaza direcciones internas (localhost, redes privadas) para que nadie use el servidor para leerlas."""
    try:
        host = urlparse(url).hostname or ""
        for info in socket.getaddrinfo(host, None):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                return False
        return True
    except Exception:
        return False


def descargar(url, limite=3_000_000):
    """Devuelve (codigo, url_final, texto, aviso)."""
    aviso = None
    if urlparse(url).scheme not in ("http", "https") or not es_direccion_publica(url):
        return 0, url, "", "dirección no permitida"
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "es-ES,es;q=0.9"})
    for verificar in (True, False):
        ctx = ssl.create_default_context()
        if not verificar:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        try:
            with urllib.request.urlopen(req, timeout=15, context=ctx) as r:
                datos = r.read(limite)
                cs = r.headers.get_content_charset() or "utf-8"
                try:
                    texto = datos.decode(cs, "replace")
                except LookupError:
                    texto = datos.decode("utf-8", "replace")
                return r.status, r.geturl(), texto, aviso
        except urllib.error.HTTPError as e:
            return e.code, url, "", aviso
        except ssl.SSLError:
            aviso = "El certificado de seguridad (https) de la web da error."
            continue
        except urllib.error.URLError as e:
            if verificar and isinstance(e.reason, ssl.SSLError):
                aviso = "El certificado de seguridad (https) de la web da error."
                continue
            return 0, url, "", str(e.reason)
        except Exception as e:  # tiempo agotado, conexión cortada...
            return 0, url, "", str(e)
    return 0, url, "", aviso


def quitar_etiquetas(h):
    h = re.sub(r"<(script|style|noscript|svg)\b.*?</\1>", " ", h, flags=re.S | re.I)
    h = _html.unescape(re.sub(r"<[^>]+>", " ", h))
    return re.sub(r"\s+", " ", h).strip()


def recorrer(o, nodos):
    if isinstance(o, dict):
        if "@type" in o:
            nodos.append(o)
        for v in o.values():
            recorrer(v, nodos)
    elif isinstance(o, list):
        for v in o:
            recorrer(v, nodos)


def analizar_pagina(html, url):
    p = {"url": url}
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    p["titulo"] = quitar_etiquetas(m.group(1)) if m else ""
    m = (re.search(r'<meta[^>]+name=["\']description["\'][^>]*content=["\'](.*?)["\']', html, re.S | re.I)
         or re.search(r'<meta[^>]+content=["\'](.*?)["\'][^>]*name=["\']description["\']', html, re.S | re.I))
    p["descripcion"] = _html.unescape(m.group(1).strip()) if m else ""
    m = re.search(r'<meta[^>]+property=["\']og:site_name["\'][^>]*content=["\'](.*?)["\']', html, re.S | re.I)
    p["sitio"] = _html.unescape(m.group(1).strip()) if m else ""
    nodos = []
    for bloque in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, re.S | re.I):
        try:
            recorrer(json.loads(bloque.strip()), nodos)
        except Exception:
            pass
    tipos = set()
    for n in nodos:
        t = n["@type"]
        for x in (t if isinstance(t, list) else [t]):
            if isinstance(x, str):
                tipos.add(x)
    p["tipos"] = sorted(tipos)
    p["nodos"] = nodos
    for tag in ("h1", "h2"):
        p[tag] = [quitar_etiquetas(x) for x in re.findall(rf"<{tag}\b[^>]*>(.*?)</{tag}>", html, re.S | re.I)]
    p["texto"] = quitar_etiquetas(html)
    p["palabras"] = len(p["texto"].split())
    enlaces = []
    for href, ancla in re.findall(r'<a\b[^>]*href=["\']([^"\'#]+)["\'][^>]*>(.*?)</a>', html, re.S | re.I):
        enlaces.append((urljoin(url, href.strip()), quitar_etiquetas(ancla)))
    p["enlaces"] = enlaces
    p["html"] = html
    return p


def raices(tratamiento):
    return [w[:6] for w in re.findall(r"[a-z]+", norm(tratamiento)) if len(w) > 3 and w not in ("dental", "dentales", "para", "clinica")] \
        or [w[:6] for w in re.findall(r"[a-z]+", norm(tratamiento)) if len(w) > 3]


def buscar_pagina_tratamiento(home, tratamiento):
    host = urlparse(home["url"]).netloc.replace("www.", "")
    rs = raices(tratamiento)
    if not rs:
        return None
    mejor, mejor_p = None, 0
    for href, ancla in home["enlaces"]:
        u = urlparse(href)
        if u.scheme not in ("http", "https") or u.netloc.replace("www.", "") != host:
            continue
        ruta = norm(u.path)
        if ruta.strip("/") == "" or re.search(r"\.(pdf|jpg|png|webp)$", ruta):
            continue
        pts = 0
        for r in rs:
            if r in ruta:
                pts += 3
            if r in norm(ancla):
                pts += 2
        if not pts:
            continue
        if re.search(r"/(blog|noticias|category|tag|20\d\d)/", ruta):
            pts -= 3
        pts -= ruta.strip("/").count("/") * 0.5  # preferimos páginas principales
        if pts > mejor_p:
            mejor, mejor_p = href.split("?")[0], pts
    return mejor


def robots_bloqueados(txt):
    grupos, agentes, reglas, ultimo = [], [], [], None
    for linea in txt.splitlines():
        linea = linea.split("#")[0].strip()
        if ":" not in linea:
            continue
        k, v = [x.strip() for x in linea.split(":", 1)]
        k = k.lower()
        if k == "user-agent":
            if ultimo != "ua" and agentes:
                grupos.append((agentes, reglas))
                agentes, reglas = [], []
            agentes.append(v.lower())
            ultimo = "ua"
        elif k in ("disallow", "allow"):
            reglas.append((k, v))
            ultimo = "regla"
    if agentes:
        grupos.append((agentes, reglas))

    def cerrado(reglas):
        return ("disallow", "/") in reglas and not any(k == "allow" for k, _ in reglas)

    general = any("*" in a and cerrado(r) for a, r in grupos)
    bloqueados, citados = [], []
    for bot in BOTS_IA:
        propios = [r for a, r in grupos if bot.lower() in a]
        if propios:
            citados.append(bot)
            if any(cerrado(r) for r in propios):
                bloqueados.append(bot)
        elif general:
            bloqueados.append(bot)
    return bloqueados, citados


def nombre_clinica(home):
    """Nombre del negocio tal como lo declara la web; si viene mezclado con eslóganes, se queda con la parte propia."""
    bruto = ""
    for n in home["nodos"]:
        t = n.get("@type")
        ts = [x.lower() for x in (t if isinstance(t, list) else [t]) if isinstance(x, str)]
        if set(ts) & (TIPOS_CLINICA | {"organization"}) and isinstance(n.get("name"), str) and n["name"].strip():
            bruto = n["name"].strip()
            break
    bruto = bruto or home["sitio"] or home["titulo"] or urlparse(home["url"]).netloc
    partes = [x.strip(" ®™") for x in re.split(r"\s[|\-–—·]\s", bruto) if x.strip(" ®™")]
    if len(partes) <= 1:
        return bruto.strip(" ®™")
    resto = distintivo_host(urlparse(home["url"]).netloc.lower().replace("www.", ""))
    for p in partes:
        if coincide_distintivo(resto, p):
            return p
    propias = [p for p in partes if any(w not in GENERICAS and len(w) > 2 for w in re.findall(r"[a-z0-9]+", norm(p)))]
    return min(propias or partes, key=len)


def auditar(url, ciudad, tratamiento, pagina=None):
    url = url.strip()
    if not re.match(r"https?://", url, re.I):
        url = "https://" + url
    u = urlparse(url)
    if not u.netloc or "." not in u.netloc:
        return {"error": "La dirección de la web no es válida."}
    ciudad, tratamiento = ciudad.strip(), tratamiento.strip()
    avisos = []

    t0 = time.time()
    codigo, final, html, aviso = descargar(url)
    segundos = time.time() - t0
    aviso_cert = bool(aviso)
    if aviso:
        avisos.append(aviso)
    if codigo != 200 or not html:
        return {"error": f"No se pudo abrir {url} (respuesta {codigo or 'sin conexión'}). "
                         "Comprueba la dirección; algunas webs bloquean las visitas automáticas."}
    home = analizar_pagina(html, final)
    cms, cms_nombre, cms_extra = detectar_cms(html)
    base = f"{urlparse(final).scheme}://{urlparse(final).netloc}"
    if home["palabras"] < 150:
        avisos.append("La portada casi no tiene texto en el código que recibe un robot "
                      f"({home['palabras']} palabras). Probablemente se dibuja con JavaScript. Esta herramienta no puede "
                      "leerla bien, así que la lista de «lo que te falta» NO es fiable para esta web; "
                      "la visibilidad en Google y en la IA sí lo es.")

    url_trat = buscar_pagina_tratamiento(home, tratamiento) or pagina
    trat = None
    if url_trat:
        c2, f2, h2, _ = descargar(url_trat)
        if c2 == 200 and h2:
            trat = analizar_pagina(h2, f2)
    paginas = [home] + ([trat] if trat else [])
    foco = trat or home
    todo_html = " ".join(p["html"] for p in paginas)
    todo_texto = " ".join(p["texto"] for p in paginas)
    tipos = {t.lower() for p in paginas for t in p["tipos"]}
    nciudad, rs = norm(ciudad), raices(tratamiento)

    cr, _, robots, _ = descargar(base + "/robots.txt")
    robots = robots if cr == 200 and "<html" not in robots[:500].lower() else ""
    cl, _, llms, _ = descargar(base + "/llms.txt")
    hay_llms = cl == 200 and len(llms.strip()) > 20 and "<html" not in llms[:500].lower() and "<!doctype" not in llms[:200].lower()

    pruebas = []

    def prueba(clave, nombre, peso, estado, detalle, arreglo, donde="web"):
        pi, pg, plazo = PESOS[clave]
        f = {"ok": 1, "parcial": 0.5, "falta": 0}[estado]
        pruebas.append({"clave": clave, "nombre": nombre, "estado": estado, "peso_ia": pi, "peso_google": pg,
                        "puntos_ia": pi * f, "puntos_google": pg * f, "plazo": plazo,
                        "afecta": "ambos" if pi and pg else "ia" if pi else "google",
                        "detalle": detalle, "arreglo": arreglo, "como": como_hacerlo(cms, cms_extra, clave) if arreglo else ""})

    # 1. Página propia del tratamiento
    if trat:
        h1 = norm(" ".join(trat["h1"]))
        t_ok, c_ok = any(r in h1 for r in rs), bool(nciudad) and nciudad in h1
        estado = "ok" if t_ok and c_ok else "parcial"
        falta = [] if t_ok else ["el tratamiento"]
        falta += [] if c_ok else ["la ciudad"]
        det = f"Encontrada: {trat['url']}. Titular principal: «{(trat['h1'] or ['(sin titular)'])[0]}»."
        if falta:
            det += " Al titular le falta " + " y ".join(falta) + "."
        prueba("pagina", "Página propia del tratamiento con la ciudad en el titular", 12, estado, det,
               f"El titular principal (H1) debe ser literal: «{tratamiento.capitalize()} en {ciudad}».")
    else:
        prueba("pagina", "Página propia del tratamiento con la ciudad en el titular", 12, "falta",
               f"No hay ningún enlace en la portada que lleve a una página de «{tratamiento}».",
               f"Crear una página dedicada, enlazada desde el menú, titulada «{tratamiento.capitalize()} en {ciudad}».")

    # 2. Profundidad
    if trat:
        n = trat["palabras"]
        estado = "ok" if n >= 1500 else "parcial" if n >= 700 else "falta"
        prueba("fondo", "Contenido a fondo en la página del tratamiento", 8, estado,
               f"La página del tratamiento tiene unas {n} palabras.",
               "Desarrollar más la página: en qué consiste, pasos, duración, dolor, "
               "alternativas, riesgos, cuidados posteriores y casos.")
    else:
        prueba("fondo", "Contenido a fondo en la página del tratamiento", 8, "falta",
               "Sin página de tratamiento no hay contenido que una IA pueda citar.",
               "Depende del punto anterior: crear la página y desarrollarla.")

    # 3. Datos estructurados de clínica
    if tipos & TIPOS_CLINICA:
        prueba("schema", "Datos estructurados de clínica dental (schema.org)", 12, "ok",
               "Tipos encontrados: " + ", ".join(sorted(tipos & TIPOS_CLINICA)) + ".", "")
    elif "organization" in tipos:
        prueba("schema", "Datos estructurados de clínica dental (schema.org)", 12, "parcial",
               "Solo se declara como «Organization» genérica; no dice que es una clínica dental ni dónde está.",
               "Pegar en la portada el bloque «Dentist» que tienes abajo, rellenado.")
    else:
        prueba("schema", "Datos estructurados de clínica dental (schema.org)", 12, "falta",
               "La web no declara datos estructurados de negocio.",
               "Pegar en la portada el bloque «Dentist» que tienes abajo, rellenado.")

    # 4. Valoración en datos estructurados
    if "aggregaterating" in tipos:
        prueba("valoracion", "Valoración media declarada en los datos estructurados", 8, "ok",
               "La web declara su nota media y número de opiniones.", "")
    elif "review" in tipos:
        prueba("valoracion", "Valoración media declarada en los datos estructurados", 8, "parcial",
               "Hay opiniones sueltas marcadas, pero no la nota media ni el total.",
               "Añadir «aggregateRating» con la nota y el número reales de opiniones.")
    else:
        prueba("valoracion", "Valoración media declarada en los datos estructurados", 8, "falta",
               "No se declara ninguna valoración.",
               "Añadir «aggregateRating» con datos reales (nunca inventados) dentro del bloque «Dentist».")

    # 5. Preguntas frecuentes
    hay_faq_texto = bool(re.search(r"preguntas\s+frecuentes|\bFAQs?\b", todo_texto, re.I))
    if "faqpage" in tipos:
        prueba("faq", "Preguntas frecuentes marcadas para buscadores e IAs", 8, "ok",
               "Hay preguntas frecuentes con marcado FAQPage.", "")
    elif hay_faq_texto:
        prueba("faq", "Preguntas frecuentes marcadas para buscadores e IAs", 8, "parcial",
               "Hay preguntas frecuentes visibles pero sin marcado FAQPage.",
               "Añadir el bloque «FAQPage» de abajo con las mismas preguntas y respuestas que se ven en la página.")
    else:
        prueba("faq", "Preguntas frecuentes marcadas para buscadores e IAs", 8, "falta",
               "No hay sección de preguntas frecuentes.",
               "Añadir 6-10 preguntas reales de pacientes con respuesta de 2-4 frases, visibles y con marcado FAQPage.")

    # 6. Precios
    precios = re.findall(r"\d[\d.,]*\s?(?:€|euros)|€\s?\d[\d.,]*|&euro;", foco["html"], re.I)
    if len(precios) >= 2:
        prueba("precio", "Precios publicados", 10, "ok",
               f"Se han encontrado {len(precios)} cifras de precio en la página analizada.", "")
    elif precios or re.search(r"precio|tarifa|financiaci", norm(foco["texto"])):
        prueba("precio", "Precios publicados", 10, "parcial",
               "Se habla de precio o financiación pero casi sin cifras concretas.",
               "Publicar un precio «desde» o una horquilla, qué incluye y la financiación.")
    else:
        prueba("precio", "Precios publicados", 10, "falta",
               "No aparece ningún precio.",
               "Publicar un precio «desde» o una horquilla, y qué incluye.")

    # 7. Autoría médica
    doctores = set(re.findall(r"\bDra?\.\s+[A-ZÁÉÍÓÚÑ][\wáéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][\wáéíóúñ]+)?", todo_texto))
    sen = {
        "nombres de doctores": len(doctores) >= 1,
        "número de colegiado": bool(re.search(r"colegiad|n[ºo°.]\s*col", todo_texto, re.I)),
        "formación (máster, universidad)": bool(re.search(r"m[aá]ster|universidad|licenciad|grado en odontolog|posgrado|postgrado", todo_texto, re.I)),
    }
    n_ok = sum(sen.values())
    estado = "ok" if n_ok == 3 else "parcial" if n_ok else "falta"
    faltan = [k for k, v in sen.items() if not v]
    prueba("autoria", "Profesionales identificados: nombre, formación y colegiado", 10, estado,
           ("Aparecen: " + ", ".join(k for k, v in sen.items() if v) + ". " if n_ok else "") +
           ("Faltan: " + ", ".join(faltan) + "." if faltan else "Están las tres señales."),
           "En la página del tratamiento, indicar quién lo realiza: nombre completo, titulación, "
           "universidad, número de colegiado y sociedades científicas.")

    # 8. Casos reales
    if re.search(r"antes y despu[eé]s|casos? (?:real|cl[ií]nic|de [eé]xito)", todo_texto, re.I):
        prueba("casos", "Casos reales o antes y después", 5, "ok",
               "En la web aparecen las expresiones «antes y después» o «casos» (no se comprueba si hay fotos).", "")
    else:
        prueba("casos", "Casos reales o antes y después", 5, "falta",
               "En el texto de la web no aparecen «antes y después» ni «casos reales/clínicos».",
               "Añadir 3-5 casos con foto, problema inicial, tratamiento y resultado (con consentimiento del paciente).")

    # 9. Opiniones y perfiles externos
    enlazados = [n for n, pat in PERFILES.items() if re.search(r'href=["\'][^"\']*(?:' + pat + ")", todo_html, re.I)]
    if enlazados:
        prueba("opiniones", "Opiniones con enlace a perfiles externos", 7, "ok",
               "La web enlaza a: " + ", ".join(enlazados) + ".", "")
    elif re.search(r"opiniones|rese[ñn]as|testimonios", todo_texto, re.I):
        prueba("opiniones", "Opiniones con enlace a perfiles externos", 7, "parcial",
               "Hay opiniones en la web, pero sin enlace a Google, Doctoralia o Top Doctors que las respalde.",
               "Enlazar desde la web a la ficha de Google y a los perfiles de Doctoralia / Top Doctors.")
    else:
        prueba("opiniones", "Opiniones con enlace a perfiles externos", 7, "falta",
               "La web no muestra opiniones de pacientes.",
               "Mostrar opiniones reales y enlazar a la ficha de Google y a Doctoralia / Top Doctors.")

    # 10. Datos de contacto local
    tel = re.search(r'href=["\']tel:([+\d\s().-]{7,})', todo_html)
    direccion = "postaladdress" in tipos
    n_ok = int(bool(tel)) + int(direccion)
    prueba("contacto", "Teléfono y dirección legibles por máquinas", 5,
           "ok" if n_ok == 2 else "parcial" if n_ok else "falta",
           ("Teléfono pulsable: sí. " if tel else "Teléfono pulsable: no. ") +
           ("Dirección en datos estructurados: sí." if direccion else "Dirección en datos estructurados: no."),
           "Poner el teléfono como enlace (tel:) y la dirección dentro del bloque «Dentist», "
           "idénticos a los de la ficha de Google.")

    # 11. Título y descripción con ciudad
    en_t = bool(nciudad) and nciudad in norm(home["titulo"])
    en_d = bool(nciudad) and nciudad in norm(home["descripcion"])
    prueba("titulo", "Ciudad en el título y la descripción de la portada", 5,
           "ok" if en_t and en_d else "parcial" if en_t or en_d else "falta",
           f"Título: «{home['titulo'][:90]}». Descripción: «{home['descripcion'][:120] or '(vacía)'}».",
           f"Título recomendado: «Clínica dental en {ciudad} | NOMBRE». Descripción de 140-160 caracteres "
           f"con la ciudad y los 2-3 tratamientos principales.")

    # 12. Robots de IA
    bloqueados, citados = robots_bloqueados(robots) if robots else ([], [])
    if bloqueados:
        prueba("robots", "Acceso permitido a los rastreadores de IA", 5, "falta",
               "El archivo robots.txt bloquea a: " + ", ".join(bloqueados) + ".",
               "Quitar ese bloqueo y pegar las líneas de robots.txt de abajo.")
    else:
        prueba("robots", "Acceso permitido a los rastreadores de IA", 5, "ok",
               ("Permitidos de forma expresa: " + ", ".join(citados) + "." if citados else
                "No están bloqueados (tampoco se les nombra; es recomendable hacerlo de forma expresa)."), "")

    # 13. llms.txt
    prueba("llms", "Archivo llms.txt (resumen de la web para IAs)", 5, "ok" if hay_llms else "falta",
           "Existe y es legible." if hay_llms else "No existe.",
           "Subir a la raíz de la web el archivo llms.txt de abajo, revisado.")

    # --- Señales propias de Google ---
    es_https = final.startswith("https://") and not aviso_cert
    prueba("https", "Web segura (https)", 0, "ok" if es_https else "falta",
           "La web carga por https sin errores." if es_https else "La web no carga por https o su certificado da error.",
           "Instalar o renovar el certificado SSL (lo hace el proveedor de alojamiento) y redirigir todo a https.")
    movil = bool(re.search(r'<meta[^>]+name=["\']viewport["\']', html, re.I))
    prueba("movil", "Preparada para móvil", 0, "ok" if movil else "falta",
           "Declara la etiqueta de adaptación a móvil." if movil else "No declara la etiqueta de adaptación a móvil (viewport).",
           "Usar una plantilla adaptable a móvil; Google posiciona según la versión móvil.")
    hay_sitemap = "sitemap:" in robots.lower()
    if not hay_sitemap:
        for ruta in ("/sitemap.xml", "/sitemap_index.xml"):
            cs, _, sm, _ = descargar(base + ruta, 200_000)
            if cs == 200 and "<urlset" in sm or cs == 200 and "<sitemapindex" in sm:
                hay_sitemap = True
                break
    prueba("sitemap", "Mapa del sitio (sitemap.xml)", 0, "ok" if hay_sitemap else "falta",
           "Hay mapa del sitio." if hay_sitemap else "No se ha encontrado sitemap.xml ni está declarado en robots.txt.",
           "Generar el sitemap (los plugins de SEO lo hacen solos) y enviarlo en Google Search Console.")
    canon = bool(re.search(r'<link[^>]+rel=["\']canonical["\']', html, re.I))
    prueba("canonical", "Dirección canónica declarada", 0, "ok" if canon else "falta",
           "La portada declara su dirección canónica." if canon else "La portada no declara dirección canónica.",
           "Activar la etiqueta «canonical» (plugin de SEO) para evitar contenido duplicado.")
    lt, ld = len(home["titulo"]), len(home["descripcion"])
    bien = int(20 <= lt <= 65) + int(70 <= ld <= 165)
    prueba("longitudes", "Título y descripción con la longitud adecuada", 0,
           "ok" if bien == 2 else "parcial" if bien else "falta",
           f"Título: {lt} caracteres (ideal 20-65). Descripción: {ld} caracteres (ideal 70-165).",
           "Ajustar título y descripción a esas longitudes para que Google no los corte ni los reescriba.")
    imgs = re.findall(r"<img\b[^>]*>", foco["html"], re.I)
    con_alt = [i for i in imgs if re.search(r'alt=["\'][^"\']{3,}', i, re.I)]
    prop = len(con_alt) / len(imgs) if imgs else 1
    prueba("alt", "Imágenes con texto alternativo", 0, "ok" if prop >= 0.8 else "parcial" if prop >= 0.5 else "falta",
           f"{len(con_alt)} de {len(imgs)} imágenes tienen descripción." if imgs else "La página no tiene imágenes en el código.",
           f"Describir cada imagen (alt) con lo que muestra, p. ej. «{tratamiento}: caso antes y después».")
    prueba("velocidad", "Rapidez de respuesta del servidor", 0,
           "ok" if segundos < 2.5 else "parcial",
           f"La portada respondió en {segundos:.1f} s ({len(html) // 1024} KB de código) en una sola medición desde este ordenador; no es la carga completa.",
           "Medir en pagespeed.web.dev y aplicar lo que indique: caché, imágenes en WebP, menos plugins.")

    total_ia = round(sum(p["puntos_ia"] for p in pruebas))
    total_google = round(sum(p["puntos_google"] for p in pruebas))
    orden = {"falta": 0, "parcial": 1, "ok": 2}
    pruebas.sort(key=lambda p: (orden[p["estado"]], -(p["peso_ia"] + p["peso_google"])))

    nombre = nombre_clinica(home)
    telefono = re.sub(r"\s+", " ", tel.group(1)).strip() if tel else "TELÉFONO"
    return {
        "url": final, "nombre": nombre, "ciudad": ciudad, "tratamiento": tratamiento,
        "cms": cms_nombre, "cms_clave": cms, "avisos": avisos,
        "pagina_tratamiento": trat["url"] if trat else None,
        "palabras_portada": home["palabras"], "palabras_trat": trat["palabras"] if trat else 0,
        "tipos": sorted({t for p in paginas for t in p["tipos"]}),
        "pruebas": pruebas,
        "plantillas": plantillas(nombre, base, ciudad, tratamiento, telefono, home, trat),
    }


def plantillas(nombre, base, ciudad, tratamiento, telefono, home, trat):
    T = tratamiento.capitalize()
    dentist = {
        "@context": "https://schema.org", "@type": "Dentist", "name": nombre, "url": base + "/",
        "telephone": telefono, "image": base + "/RUTA-A-UNA-FOTO-DE-LA-CLINICA.jpg",
        "priceRange": "RANGO DE PRECIOS (p. ej. €€)",
        "address": {"@type": "PostalAddress", "streetAddress": "CALLE Y NÚMERO", "postalCode": "CÓDIGO POSTAL",
                    "addressLocality": ciudad, "addressCountry": "ES"},
        "geo": {"@type": "GeoCoordinates", "latitude": "LATITUD", "longitude": "LONGITUD"},
        "openingHoursSpecification": [{"@type": "OpeningHoursSpecification",
                                       "dayOfWeek": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
                                       "opens": "HORA DE APERTURA (HH:MM)", "closes": "HORA DE CIERRE (HH:MM)"}],
        "medicalSpecialty": "Dentistry",
        "availableService": {"@type": "MedicalProcedure", "name": T,
                             "url": (trat["url"] if trat else base + "/URL-DE-LA-PAGINA-DEL-TRATAMIENTO/")},
        "employee": [{"@type": "Person", "name": "Dr./Dra. NOMBRE Y APELLIDOS", "jobTitle": "Odontólogo/a",
                      "identifier": "Nº DE COLEGIADO",
                      "alumniOf": "UNIVERSIDAD"}],
        "aggregateRating": {"@type": "AggregateRating", "ratingValue": "NOTA REAL (p. ej. 4.8)",
                            "reviewCount": "Nº REAL DE OPINIONES"},
        "sameAs": ["URL FICHA DE GOOGLE", "URL PERFIL DOCTORALIA", "URL INSTAGRAM"],
    }
    preguntas = [
        f"¿Cuánto cuesta {tratamiento} en {ciudad}?",
        f"¿Cuánto dura el tratamiento de {tratamiento}?",
        f"¿Duele el tratamiento de {tratamiento}?",
        f"¿Quién realiza {tratamiento} en {nombre} y qué formación tiene?",
        f"¿Qué alternativas hay a {tratamiento}?",
        f"¿Se puede financiar {tratamiento}?",
        f"¿Cuánto duran los resultados de {tratamiento}?",
    ]
    faq = {"@context": "https://schema.org", "@type": "FAQPage",
           "mainEntity": [{"@type": "Question", "name": p,
                           "acceptedAnswer": {"@type": "Answer", "text": "RESPUESTA REAL DE LA CLÍNICA EN 2-4 FRASES, CON CIFRAS."}}
                          for p in preguntas]}
    envolver = lambda o: '<script type="application/ld+json">\n' + json.dumps(o, ensure_ascii=False, indent=2) + "\n</script>"
    robots = "\n".join(f"User-agent: {b}\nAllow: /\n" for b in BOTS_IA) + f"\nSitemap: {base}/sitemap.xml\n"
    vistos, lineas = set(), []
    for href, ancla in home["enlaces"]:
        u = urlparse(href)
        if u.netloc.replace("www.", "") != urlparse(base).netloc.replace("www.", ""):
            continue
        limpio = href.split("?")[0]
        if limpio in vistos or len(ancla) < 4 or len(ancla) > 60 or u.path.strip("/") == "":
            continue
        if re.search(r"cookie|legal|privacidad|login|carrito|\.(pdf|jpg|png)$", norm(limpio)):
            continue
        vistos.add(limpio)
        lineas.append(f"- [{ancla}]({limpio})")
        if len(lineas) >= 15:
            break
    llms = (f"# {nombre}\n\n"
            f"> Clínica dental en {ciudad}. {home['descripcion'] or 'DESCRIPCIÓN DE 1-2 FRASES: especialidades, años de experiencia, zona.'}\n\n"
            f"- Dirección: CALLE Y NÚMERO, CÓDIGO POSTAL, {ciudad}\n- Teléfono: {telefono}\n"
            f"- Horario: HORARIO\n- Director/a médico/a: NOMBRE, Nº DE COLEGIADO\n\n"
            f"## Tratamientos y páginas principales\n\n" + ("\n".join(lineas) or "- [NOMBRE DE LA PÁGINA](URL)") + "\n\n"
            f"## Precios orientativos\n\n- {T}: desde PRECIO €\n\n"
            f"## Opiniones\n\n- Google: NOTA sobre 5 (Nº opiniones)\n- Doctoralia: NOTA sobre 5 (Nº opiniones)\n")
    return [
        {"titulo": "Bloque de datos estructurados «Dentist»",
         "donde": "Pegar en el código de la portada (en WordPress: plugin de «código en cabecera» o el de SEO). Sustituir lo que está en MAYÚSCULAS por datos reales.",
         "codigo": envolver(dentist)},
        {"titulo": "Preguntas frecuentes (FAQPage)",
         "donde": f"Pegar en la página de {tratamiento}. Las mismas preguntas y respuestas deben verse en la página.",
         "codigo": envolver(faq)},
        {"titulo": "Líneas para robots.txt", "donde": "Añadir al archivo robots.txt de la raíz de la web.", "codigo": robots},
        {"titulo": "Archivo llms.txt", "donde": f"Guardar como {base}/llms.txt tras completar los datos en MAYÚSCULAS.", "codigo": llms},
    ]


# ---------------------------------------------------------------------------
# Búsqueda: quién sale primero para «tratamiento + ciudad»
# ---------------------------------------------------------------------------
DIRECTORIOS = ["clinicpoint", "doctoralia", "topdoctors", "whatclinic", "masquemedicos", "treatwell", "bookimed",
               "saludonnet", "sanitas", "adeslas", "paginasamarillas", "yelp.", "tripadvisor",
               "cylex", "qdq.com", "infoisinfo", "europages", "habitissimo", "dentalia", "medicosdoc"]
BASURA = re.compile(
    r"google|facebook|instagram|twitter|^x\.com|youtube|youtu\.be|linkedin|tiktok|whatsapp|wa\.me|pinterest|"
    r"wordpress|gstatic|apple\.|microsoft|amazon|cloudflare|gravatar|w3\.org|schema\.org|creativecommons|"
    r"bit\.ly|t\.me|telegram|spotify|cookie|iubenda|\.gob\.|\.gov|europa\.eu|wikipedia|trustpilot|duckduckgo|"
    r"brave\.com|bing\.com|jquery|bootstrap|fonts\.|vimeo|shopify|wix\.com|elementor|yoast|addtoany|sharethis|"
    r"mozilla|adobe|paypal|stripe|cdn\.|maps\.|goo\.gl|g\.page|calendly|typeform|hubspot|mailchi|onetrust|"
    r"cookiebot|aepd|boe\.es|colegio|consejodentistas|\.edu|universidad|ucm\.es")
PRENSA = re.compile(r"cope\.es|elmundo|elpais|abc\.es|lavanguardia|20minutos|que\.es|moncloa\.com|merca2|hola\.com|"
                    r"europapress|elconfidencial|larazon|okdiario|elespanol|marca\.com|telecinco|antena3|rtve|"
                    r"lasexta|eldiario|expansion|cincodias|infobae|marie-claire|vogue|elle\.com|telva|emprendedores")


LISTADO_HOST = re.compile(r"mejor|top|ranking|guia|directorio|compara|cercano|opiniones|zona|\.place$|^aqui\.")


def host_de(u):
    return urlparse(u).netloc.lower().replace("www.", "")


def es_directorio(h):
    return any(d in h for d in DIRECTORIOS)


ARCHIVO_CLAVE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "clave_google.txt")
AVISO_GOOGLE = []


def clave_google():
    k = os.environ.get("SERPER_API_KEY", "").strip()
    if not k and os.path.exists(ARCHIVO_CLAVE):
        with open(ARCHIVO_CLAVE) as f:
            k = f.read().strip()
    return k


def buscar_google(consulta, clave):
    """Resultados reales de Google (España, en español) a través de Serper.dev."""
    cuerpo = json.dumps({"q": consulta, "gl": "es", "hl": "es", "num": 10}).encode()
    req = urllib.request.Request("https://google.serper.dev/search", data=cuerpo, method="POST",
                                 headers={"X-API-KEY": clave, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        d = json.loads(r.read().decode("utf-8", "replace"))
    return [o["link"] for o in d.get("organic", []) if isinstance(o, dict) and str(o.get("link", "")).startswith("http")]


GUION_SAFARI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "google_safari.applescript")


CERROJO_SAFARI = threading.Lock()


def pagina_google_safari(consulta):
    """Abre la búsqueda en Safari y devuelve (dirección final, código de la página). Una cada vez."""
    q = quote_plus(consulta)
    marca = f"q={q}&hl=es&gl=es&num=10"
    with CERROJO_SAFARI:
        p = subprocess.run(["osascript", GUION_SAFARI, "https://www.google.com/search?" + marca, marca],
                           capture_output=True, text=True, timeout=40)
    url, _, h = p.stdout.partition("\n")
    if "/sorry/" in url or "recaptcha" in h[:20000].lower() and "<h3" not in h:
        raise RuntimeError("captcha")
    return url, h


def buscar_google_safari(consulta):
    """Busca en Google abriendo Safari en este Mac (como haría una persona) y lee el orden de los resultados.
    Google oculta las direcciones completas, así que se devuelve la portada de cada web en su orden."""
    _, h = pagina_google_safari(consulta)
    vistos = []
    for u in re.findall(r'<a jsname="UWckNb".{0,8000}?<cite[^>]*>(https?://[^<\s]+)', h, re.S):
        u = _html.unescape(u).rstrip("/") + "/"
        if u not in vistos:
            vistos.append(u)
    return vistos


def hay_safari():
    return sys.platform == "darwin" and os.path.exists(GUION_SAFARI) and not os.environ.get("SIN_SAFARI")


def resenas_google(nombre, ciudad):
    """Nota y número de reseñas de la ficha que Google muestra al buscar «nombre ciudad». None si no se puede leer."""
    consulta = f"{nombre} {ciudad}"
    aentero = lambda x: int(re.sub(r"\D", "", x) or 0)
    try:
        if hay_safari():
            _, h = pagina_google_safari(consulta)
            t = re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<(script|style)\b.*?</\1>", " ", h, flags=re.S))))
            m = re.search(r"(\d,\d)\s+([\d.]+)\s+reseñas\s+(?:Más información|de Google)", t)
            if m:
                return {"nota": m.group(1), "n": aentero(m.group(2)), "varias": False, "consulta": consulta}
            # Si Google muestra varias fichas (varias sedes u otros negocios), no se puede saber cuál es: no se da cifra.
        elif clave_google():
            cuerpo = json.dumps({"q": consulta, "gl": "es", "hl": "es"}).encode()
            req = urllib.request.Request("https://google.serper.dev/search", data=cuerpo, method="POST",
                                         headers={"X-API-KEY": clave_google(), "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=20) as r:
                kg = json.loads(r.read().decode("utf-8", "replace")).get("knowledgeGraph", {})
            if kg.get("rating") and kg.get("ratingCount"):
                return {"nota": str(kg["rating"]).replace(".", ","), "n": int(kg["ratingCount"]), "varias": False, "consulta": consulta}
    except Exception:
        pass
    return None


MOTIVOS = [
    ("Opiniones y valoraciones de pacientes", r"opini|rese[ñn]|valoraci|testimon|puntuaci"),
    ("Formación y experiencia de los profesionales", r"formaci|m[aá]ster|especiali|experiencia|trayectoria|colegiad|universi|docen|acredit|board|equipo"),
    ("Tecnología y planificación del tratamiento", r"digital|esc[aá]ner|3d|tecnolog|planificaci|guiada|mock|prueba"),
    ("Precio y financiación", r"precio|financi|coste|presupuesto|€|económic"),
    ("Casos y resultados publicados", r"casos|antes y despu|resultado|galer"),
]


def contar_motivos(respuestas):
    """Cuenta qué razones da la IA en sus recomendaciones. Es una cuenta de palabras sobre sus propios textos."""
    textos = [norm(x.get("motivo", "")) for r in respuestas for x in r["recomendadas"]]
    total = len(textos)
    filas = [{"motivo": nombre, "n": sum(1 for t in textos if re.search(norm(patron), t)), "total": total}
             for nombre, patron in MOTIVOS]
    return sorted((f for f in filas if f["n"]), key=lambda f: -f["n"])


def buscar(consulta):
    """Devuelve (lista de URL, buscador usado). Google real con Safari; si no se puede, clave de Serper;
    y si tampoco, DuckDuckGo y Brave."""
    from urllib.parse import unquote, parse_qs
    if hay_safari():
        try:
            urls = buscar_google_safari(consulta)
            if urls:
                AVISO_GOOGLE[:] = []
                return urls, "Google"
            AVISO_GOOGLE[:] = ["Safari no ha devuelto resultados de Google (puede pedir aceptar su aviso de privacidad: ábrelo una vez a mano)."]
        except RuntimeError:
            AVISO_GOOGLE[:] = ["Google ha pedido una verificación «no soy un robot» en Safari; hay que resolverla a mano y repetir."]
        except Exception:
            AVISO_GOOGLE[:] = ["No se ha podido usar Safari para buscar en Google."]
    clave = clave_google()
    if clave:
        try:
            urls = buscar_google(consulta, clave)
            if urls:
                return urls, "Google"
        except urllib.error.HTTPError as e:
            AVISO_GOOGLE[:] = [f"La clave de Google ha sido rechazada (respuesta {e.code}): puede ser incorrecta o haberse agotado."]
        except Exception:
            AVISO_GOOGLE[:] = ["No se ha podido conectar con el servicio de resultados de Google."]
    c, _, h, _ = descargar("https://html.duckduckgo.com/html/?kl=es-es&q=" + quote_plus(consulta))
    urls = []
    for href in re.findall(r'class="result__a"[^>]*href="([^"]+)"', h):
        href = _html.unescape(href)
        if "uddg=" in href:
            href = unquote(parse_qs(urlparse(href).query).get("uddg", [""])[0])
        if href.startswith("http") and "duckduckgo.com/y.js" not in href:
            urls.append(href)
    if urls:
        return urls, "DuckDuckGo"
    c, _, h, _ = descargar("https://search.brave.com/search?country=es&q=" + quote_plus(consulta))
    urls = re.findall(r'data-type="web".{0,600}?<a href="(https?://[^"]+)"', h, re.S)
    return urls, "Brave"


def encontrar_primeras(ciudad, tratamiento, negocio, host_propio, n=3):
    plural = "laboratorios dentales" if "laboratorio" in negocio else "clínicas"
    consultas = [f"mejor {negocio} {tratamiento} {ciudad}",
                 f"mejores {plural} de {tratamiento} en {ciudad}",
                 f"{negocio} {tratamiento} {ciudad}" if "laboratorio" in negocio else f"{tratamiento} en {ciudad}"]
    resultados, buscadores = [], set()
    for i, q in enumerate(consultas):
        if i:
            time.sleep(1.2)
        urls, motor = buscar(q)
        if urls:
            buscadores.add(motor)
        resultados.append((q, urls[:10]))
    if not any(u for _, u in resultados):
        return {"error": "Los buscadores no han devuelto resultados (suelen limitar las consultas "
                         "automáticas seguidas). Espera un par de minutos y vuelve a intentarlo."}

    # Páginas distintas que han salido, con su mejor posición
    paginas, en_consulta = {}, {}
    for q, urls in resultados:
        for pos, u in enumerate(urls):
            paginas.setdefault(u.split("#")[0], []).append(pos)
            en_consulta.setdefault(host_de(u), set()).add(q)
    a_leer = [u for u in paginas if not es_directorio(host_de(u))][:16]
    with ThreadPoolExecutor(8) as ex:
        leidas = dict(zip(a_leer, ex.map(lambda u: descargar(u, 1_500_000), a_leer)))

    candidatos, fuentes = {}, []

    def sumar(h, pts, motivo, pagina=None):
        c = candidatos.setdefault(h, {"host": h, "puntos": 0, "listados": [], "directa": False, "pagina": None, "pos": 99})
        c["puntos"] += pts
        if motivo == "directa":
            c["directa"] = True
            c["pagina"] = c["pagina"] or pagina
        elif motivo not in c["listados"]:
            c["listados"].append(motivo)

    for u in paginas:
        h = host_de(u)
        if es_directorio(h):
            fuentes.append({"host": h, "url": u, "tipo": "Directorio", "clinicas": None, "apareces": None})
    for u, (cod, final, html, _) in leidas.items():
        h = host_de(u)
        externos = {}
        if cod == 200 and html:
            for href, ancla in re.findall(r'<a\b[^>]*href=["\'](https?://[^"\'#]+)["\'][^>]*>(.*?)</a>', html, re.S | re.I):
                eh = host_de(href)
                if not eh or eh == h or eh.endswith("." + h) or BASURA.search(eh) or PRENSA.search(eh) or es_directorio(eh):
                    continue
                externos.setdefault(eh, href)
        dentales = [e for e in externos if re.search(r"dent|clinic|odont|implant|sonri|smile|orto|protes|maxilo|dr|estetic", e)]
        es_listado = len(dentales) >= 3 or bool(PRENSA.search(h)) or bool(LISTADO_HOST.search(h))
        if es_listado:
            apareces = bool(host_propio) and host_propio in html.lower()
            fuentes.append({"host": h, "url": u, "tipo": "Prensa" if PRENSA.search(h) else "Listado",
                            "clinicas": len(dentales), "apareces": apareces})
            if not PRENSA.search(h) or len(dentales) >= 2:
                for e in (dentales if len(dentales) >= 3 else externos):
                    sumar(e, 3, h)
        elif cod == 200:
            sumar(h, 2 + max(0, 5 - min(paginas[u])) * 0.3, "directa", u)
            candidatos[h]["pos"] = min(candidatos[h]["pos"], min(paginas[u]))

    vistos, fu = set(), []
    for f in fuentes:  # un directorio o listado por dominio
        if f["host"] not in vistos:
            vistos.add(f["host"])
            fu.append(f)

    ajenos = [c for c in candidatos.values() if c["host"] != host_propio]
    por_ia = sorted(ajenos, key=lambda c: -c["puntos"])[:9]
    por_google = sorted((c for c in ajenos if c["directa"]), key=lambda c: c["pos"])[:7]
    orden = por_ia + [c for c in por_google if c not in por_ia]

    # Posición de la web propia
    mejor = None
    for q, urls in resultados:
        for i, u in enumerate(urls):
            if host_propio and host_de(u) == host_propio and (mejor is None or i < mejor[0]):
                mejor = (i, q)
    listados = [f for f in fu if f["tipo"] != "Directorio"]
    citas = [f["host"] for f in listados if f["apareces"]]
    posicion = {
        "google": (f"Puesto {mejor[0] + 1} para «{mejor[1]}»" if mejor else "No sales entre los 10 primeros resultados"),
        "google_ok": bool(mejor),
        "ia": (f"Te citan {len(citas)} de {len(listados)} listados ({', '.join(citas)})" if citas
               else f"No te cita ninguno de los {len(listados)} listados que lee la IA" if listados
               else "No han salido listados para esta búsqueda"),
        "ia_ok": bool(citas),
        "google_veces": len(en_consulta.get(host_propio, ())), "total": len(resultados),
        "ia_veces": len(citas), "ia_total": len(listados),
    }
    for c in candidatos.values():
        c["veces"] = len(en_consulta.get(c["host"], ()))

    def validar(c):
        cod, final, html, _ = descargar("https://" + c["host"] + "/", 1_500_000)
        if cod != 200:
            return None
        t = norm(quitar_etiquetas(html))
        if len(t.split()) < 120 or not re.search(r"dent|odontolog|protesi", t):
            return None
        if "laboratorio" not in negocio and not re.search(r"clinica|dentista|consulta|cita", t):
            return None
        return c

    with ThreadPoolExecutor(9) as ex:
        validos = [c for c in ex.map(validar, orden) if c]
    return {"ia": [c for c in por_ia if c in validos][:n], "google": [c for c in por_google if c in validos][:n],
            "posicion": posicion, "fuentes": fu, "consultas": [q for q, _ in resultados],
            "detalle": [{"pregunta": q, "motor": " y ".join(sorted(buscadores)),
                         "lista": [{"nombre": host_de(u), "yo": host_de(u) == host_propio} for u in urls]}
                        for q, urls in resultados],
            "buscador": " y ".join(sorted(buscadores))}


N_PREGUNTAS = 21
TROZOS_GENERICOS = ["clinicas", "clinica", "dentales", "dental", "dentista", "odontologia", "odontologica", "estetica",
                    "implantes", "implantologia", "ortodoncia", "madrid", "barcelona", "valencia", "sevilla",
                    "centro", "doctora", "doctor", "www", "smile", "sonrisa", "clinic", "dent"]


def distintivo_host(host):
    """Lo que queda del dominio al quitar palabras genéricas: clinicadentalbernabeu.es -> «bernabeu»."""
    r = norm(host.split(".")[0])
    for t in TROZOS_GENERICOS:
        r = r.replace(t, " ")
    r = re.sub(r"[^a-z0-9]+", "", r)
    return r if len(r) >= 2 else ""


def coincide_distintivo(resto, nombre):
    """¿El nombre que da la IA corresponde al dominio? Exige coincidencia clara para no contar a otra clínica."""
    if not resto:
        return False
    pegado = re.sub(r"[^a-z0-9]+", "", norm(nombre))
    if len(resto) >= 5:
        return resto in pegado
    return any(t == resto or (t.startswith(resto) and t[len(resto):] in ("dental", "dentales", "clinic", "clinica"))
               for t in re.findall(r"[a-z0-9]+", norm(nombre)))


def nombre_corto(nombre):
    """Clave para juntar «Clínica Dental Ferrus & Bratos» y «Ferrus & Bratos» en una sola fila."""
    return " ".join(w for w in re.findall(r"[a-z0-9]+", norm(re.split(r"\s[—–|-]\s", nombre)[0])) if w not in GENERICAS) \
        or norm(nombre)

GENERICAS = {"clinica", "clinicas", "dental", "dentales", "dentista", "dentistas", "centro", "laboratorio",
             "odontologia", "odontologica", "doctor", "doctora", "madrid", "para", "the"}
CODEX = "/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex"
ESQ_RECOMENDAR = {"type": "object", "additionalProperties": False, "required": ["recomendadas", "fuentes"], "properties": {
    "recomendadas": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                 "required": ["nombre", "web", "motivo"],
                                                 "properties": {"nombre": {"type": "string"}, "web": {"type": "string"},
                                                                "motivo": {"type": "string"}}}},
    "fuentes": {"type": "array", "items": {"type": "string"}}}}
ESQ_CONSEJO = {"type": "object", "additionalProperties": False, "required": ["diagnostico", "cambios"], "properties": {
    "diagnostico": {"type": "string"},
    "cambios": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["titulo", "detalle"],
                                           "properties": {"titulo": {"type": "string"}, "detalle": {"type": "string"}}}}}}
FORMATO = ('En "recomendadas" pon, en orden de preferencia, los 5 negocios concretos que recomendarías (no directorios ni '
           'comparadores), con la dirección de su web oficial y el motivo en una frase. En "fuentes" pon las páginas que has consultado.')


def sin_enlaces(t):
    t = re.sub(r"\[([^\]]+)\]\(https?://[^)]+\)", r"\1", t or "")
    return re.sub(r"\s+([.,;])", r"\1", re.sub(r"\s{2,}", " ", t)).strip()


def pedir_chatgpt(prompt, esquema, espera=200):
    """Consulta real a ChatGPT con búsqueda web, usando el Codex que trae la aplicación de ChatGPT y su sesión."""
    exe = shutil.which("codex") or CODEX
    if not os.path.exists(exe):
        return {"error": "ChatGPT no está instalado en este equipo."}
    carpeta = tempfile.mkdtemp(prefix="auditor-")
    try:
        with open(os.path.join(carpeta, "esquema.json"), "w") as f:
            json.dump(esquema, f)
        salida = os.path.join(carpeta, "respuesta.json")
        p = subprocess.run([exe, "exec", "-s", "read-only", "--skip-git-repo-check", "--ephemeral",
                            "-c", 'web_search="live"', "--output-schema", os.path.join(carpeta, "esquema.json"),
                            "-o", salida, prompt + " No ejecutes comandos ni leas archivos del equipo; usa solo la búsqueda web."],
                           capture_output=True, text=True, timeout=espera, stdin=subprocess.DEVNULL, cwd=carpeta)
        if not os.path.exists(salida):
            cola = (p.stderr or p.stdout or "")[-300:]
            if re.search(r"log ?in|auth|401", cola, re.I):
                return {"error": "ChatGPT no tiene la sesión iniciada en este equipo."}
            return {"error": "ChatGPT no ha respondido (puede haberse agotado el límite de uso)."}
        with open(salida) as f:
            return json.load(f)
    except subprocess.TimeoutExpired:
        return {"error": "ChatGPT ha tardado demasiado en responder."}
    except Exception:
        return {"error": "No se ha podido leer la respuesta de ChatGPT."}
    finally:
        shutil.rmtree(carpeta, ignore_errors=True)


def pedir_openai_api(prompt, esquema, espera=200):
    """Consulta a un modelo de OpenAI con búsqueda web mediante su API (para la versión en servidor).
    Necesita OPENAI_API_KEY; el modelo se elige con OPENAI_MODEL."""
    clave = os.environ.get("OPENAI_API_KEY", "").strip()
    cuerpo = json.dumps({
        "model": os.environ.get("OPENAI_MODEL", "gpt-5"),
        "tools": [{"type": "web_search"}],
        "input": prompt,
        "text": {"format": {"type": "json_schema", "name": "respuesta", "schema": esquema, "strict": True}},
    }).encode()
    req = urllib.request.Request("https://api.openai.com/v1/responses", data=cuerpo, method="POST",
                                 headers={"Authorization": "Bearer " + clave, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=espera) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
        texto = "".join(c.get("text", "") for o in d.get("output", []) if o.get("type") == "message"
                        for c in o.get("content", []) if c.get("type") == "output_text")
        return json.loads(re.search(r"\{.*\}", texto, re.S).group(0))
    except urllib.error.HTTPError as e:
        detalle = ""
        try:
            detalle = json.loads(e.read().decode("utf-8", "replace")).get("error", {}).get("message", "")[:160]
        except Exception:
            pass
        return {"error": f"La API de OpenAI ha rechazado la consulta (respuesta {e.code}). {detalle}"}
    except Exception:
        return {"error": "No se ha podido leer la respuesta de la API de OpenAI."}


def motor_ia():
    """Qué IA se puede consultar aquí: el ChatGPT instalado (uso local) o la API de OpenAI (servidor)."""
    if os.path.exists(shutil.which("codex") or CODEX):
        return "ChatGPT", pedir_chatgpt
    if os.environ.get("OPENAI_API_KEY", "").strip():
        return "ChatGPT (API de OpenAI)", pedir_openai_api
    return None, None


def capacidades():
    safari = hay_safari()
    return {"ia": motor_ia()[0],
            "google": "Google desde Safari" if safari else "Google (servicio con clave)" if clave_google() else None,
            "preguntas": n_preguntas()}


def n_preguntas():
    try:
        return max(1, min(40, int(os.environ.get("N_PREGUNTAS_IA", "20"))))
    except ValueError:
        return 20


def pedir_claude(prompt, espera=200):
    """Consulta real a Claude con búsqueda web, usando el Claude de terminal y su sesión."""
    exe = shutil.which("claude") or os.path.expanduser("~/.local/bin/claude")
    if not os.path.exists(exe):
        return {"error": "Claude no está instalado en este equipo."}
    try:
        p = subprocess.run([exe, "-p", prompt + ' Responde SOLO con un JSON, sin texto alrededor: '
                            '{"recomendadas":[{"nombre":"","web":"","motivo":""}],"fuentes":["url"]}',
                            "--allowedTools", "WebSearch", "--model", "sonnet", "--output-format", "json"],
                           capture_output=True, text=True, timeout=espera, stdin=subprocess.DEVNULL, cwd=tempfile.gettempdir())
        d = json.loads(p.stdout)
        if d.get("is_error"):
            return {"error": "Claude no tiene la sesión iniciada en la terminal (se arregla con «claude auth login»)."}
        return json.loads(re.search(r"\{.*\}", str(d.get("result", "")), re.S).group(0))
    except subprocess.TimeoutExpired:
        return {"error": "Claude ha tardado demasiado en responder."}
    except Exception:
        return {"error": "No se ha podido leer la respuesta de Claude."}


def preguntar_ia(ciudad, tratamiento, negocio):
    """Hace 20 preguntas de paciente a ChatGPT (10 formulaciones, dos veces) y una a Claude."""
    qs = [f"¿Cuál es la mejor {negocio} para {tratamiento} en {ciudad}?",
          f"Quiero hacerme {tratamiento} en {ciudad}. ¿A qué {negocio} me recomiendas ir?",
          f"Busco {negocio} de confianza en {ciudad} para {tratamiento}, con buenas opiniones. ¿Cuáles me recomiendas?",
          f"¿Qué {negocio} de {ciudad} tiene mejores resultados en {tratamiento}?",
          f"Recomiéndame especialistas en {tratamiento} en {ciudad}.",
          f"¿Dónde hacen mejor {tratamiento} en {ciudad}?",
          f"Necesito {tratamiento} y vivo en {ciudad}. ¿Qué opciones buenas tengo?",
          f"¿Qué {negocio} me recomiendas en {ciudad} para {tratamiento} con buena relación calidad-precio?",
          f"Dime las {negocio.replace('clínica dental', 'clínicas dentales').replace('laboratorio dental', 'laboratorios dentales')} más recomendadas de {ciudad} para {tratamiento}.",
          f"¿Quiénes son los mejores profesionales de {tratamiento} en {ciudad}?"]
    if "laboratorio" in negocio:
        qs[1] = f"Soy dentista en {ciudad} y necesito un {negocio} para {tratamiento}. ¿Cuál me recomiendas?"
        qs[6] = f"Tengo una clínica en {ciudad} y busco {negocio} para {tratamiento}. ¿Qué opciones buenas tengo?"
    nombre_motor, pedir = motor_ia()
    if not pedir:
        return {"error": "Este equipo no tiene ninguna IA configurada: falta la aplicación de ChatGPT (uso local) "
                         "o la variable OPENAI_API_KEY (servidor)."}
    # La IA no responde igual dos veces: se repiten las preguntas hasta llegar al número pedido y se promedia.
    n = n_preguntas()
    trabajos = [(nombre_motor, qs[i % len(qs)]) for i in range(n)]
    if os.path.exists(shutil.which("claude") or os.path.expanduser("~/.local/bin/claude")):
        trabajos.append(("Claude", qs[0]))

    def uno(t):
        motor, q = t
        base = f'Un paciente te pregunta: "{q}". Busca en la web como harías normalmente para responderle. ' + FORMATO
        r = pedir_claude(base) if motor == "Claude" else pedir(base, ESQ_RECOMENDAR)
        recs = [x for x in r.get("recomendadas", []) if isinstance(x, dict) and x.get("nombre")][:5] if "error" not in r else []
        if not recs:
            return {"motor": motor, "error": r.get("error", f"{motor} no ha recomendado ningún negocio concreto.")}
        return {"motor": motor, "pregunta": q, "recomendadas": recs,
                "fuentes": [f for f in r.get("fuentes", []) if isinstance(f, str) and f.startswith("http")]}

    with ThreadPoolExecutor(5) as ex:
        hechas = list(ex.map(uno, trabajos))
    buenas = [h for h in hechas if "error" not in h]
    errores = list(dict.fromkeys(h["error"] for h in hechas if "error" in h))
    if not buenas:
        return {"error": " ".join(errores)}
    return {"respuestas": buenas, "errores": errores, "pedidas": len(trabajos)}


def comparar(url, ciudad, tratamiento, negocio="clínica dental", modo="ambos"):
    """Dos vías separadas: cómo sales en un buscador y qué responde una IA. Compara con las primeras de cada una."""
    propia = auditar(url, ciudad, tratamiento)
    if "error" in propia:
        return propia
    ciudad, tratamiento = ciudad.strip(), tratamiento.strip()
    canales = ["google", "ia"] if modo == "ambos" else [modo]
    host_propio = host_de(propia["url"])
    claves = [w for w in re.findall(r"[a-z0-9]+", norm(propia["nombre"])) if len(w) > 2 and w not in GENERICAS]
    resto_host = distintivo_host(host_propio)

    def soy_yo(nombre, web=""):
        if web and host_de(web if "//" in web else "https://" + web) == host_propio:
            return True
        n = norm(nombre)
        if claves and len(claves) <= 3 and all(c in n for c in claves):
            return True
        return coincide_distintivo(resto_host, nombre)

    with ThreadPoolExecutor(2) as ex:
        f_ia = ex.submit(preguntar_ia, ciudad, tratamiento, negocio) if "ia" in canales else None
        b = encontrar_primeras(ciudad, tratamiento, negocio, host_propio)
        ia = f_ia.result() if f_ia else None
    hay_busqueda = "error" not in b
    vias, f_consejo = {}, None
    ex_consejo = ThreadPoolExecutor(1)

    if "google" in canales:
        es_google = b.get("buscador") == "Google"
        v = {"titulo": "Búsqueda en Google", "real": es_google, "motor": "Google (España, desde tu Safari)" if es_google else (b.get("buscador") or "DuckDuckGo"),
             "unidad": "búsquedas",
             "aviso": None if es_google else (" ".join(AVISO_GOOGLE) + " " if AVISO_GOOGLE else "") +
                      "Estos resultados NO son de Google: son de otro buscador (DuckDuckGo) y solo orientan.",
             "consultas": b.get("consultas", []), "nombradas": [], "fuentes": [], "consejo": None,
             "pruebas_reales": b.get("detalle", [])}
        if hay_busqueda:
            p = b["posicion"]
            v.update(posicion=p["google"], veces=p["google_veces"], total=p["total"], cands=b["google"])
        else:
            v.update(posicion="Sin datos", veces=0, total=0, cands=[], aviso=b["error"])
        vias["google"] = v

    if "ia" in canales:
        if ia and "error" not in ia:
            resp = ia["respuestas"]
            total = len(resp)
            agr, puestos = {}, []
            web_de = lambda x: (lambda w: (w if "//" in w else "https://" + w) if w else "")((x.get("web") or "").strip())
            # Mismo negocio nombrado de formas distintas: se agrupa por dominio y, si no hay, por nombre corto.
            por_nombre = {}
            for r in resp:
                for x in r["recomendadas"]:
                    w = web_de(x)
                    if w and "." in host_de(w):
                        por_nombre.setdefault(nombre_corto(x["nombre"]), host_de(w))
            for r in resp:
                contadas = set()
                for i, x in enumerate(r["recomendadas"]):
                    w = web_de(x)
                    yo = soy_yo(x["nombre"], w)
                    h = host_de(w) if w and "." in host_de(w) else por_nombre.get(nombre_corto(x["nombre"]), "")
                    k = "yo" if yo else (h or nombre_corto(x["nombre"]))
                    if k in contadas:  # una clínica cuenta una sola vez por respuesta
                        continue
                    contadas.add(k)
                    if yo:
                        puestos.append(i + 1)
                    a = agr.setdefault(k, {"nombre": propia["nombre"] if yo else x["nombre"], "host": h, "veces": 0, "puntos": 0,
                                           "motivo": sin_enlaces(x.get("motivo", "")), "yo": yo, "motores": []})
                    a["veces"] += 1
                    a["puntos"] += 6 - i
                    if r["motor"] not in a["motores"]:
                        a["motores"].append(r["motor"])
            orden_ia = sorted(agr.values(), key=lambda a: (-a["veces"], -a["puntos"]))
            cands = [{"host": a["host"], "pagina": None, "listados": [], "directa": False, "pos": 99,
                      "motivo": a["motivo"], "veces": a["veces"], "nombre": a["nombre"]}
                     for a in orden_ia if not a["yo"] and a["host"]][:3]
            enlaces = list(dict.fromkeys(f for r in resp for f in r["fuentes"]))[:10]

            def mirar(u):
                cod, _, h, _ = descargar(u, 1_500_000)
                t = norm(quitar_etiquetas(h)) if cod == 200 else ""
                return {"host": host_de(u), "url": u, "tipo": "Directorio" if es_directorio(host_de(u)) else "Fuente",
                        "clinicas": None,
                        "apareces": None if cod != 200 else (host_propio in h.lower() or
                                                             (len(resto_host) >= 5 and resto_host in re.sub(r"[^a-z0-9]+", "", t)))}

            with ThreadPoolExecutor(8) as ex:
                fuentes = list(ex.map(mirar, enlaces))
            motores = list(dict.fromkeys(r["motor"] for r in resp))
            k = len(puestos)
            vias["ia"] = {"titulo": "Pregunta a una IA", "real": True, "motor": " y ".join(motores), "unidad": "respuestas",
                          "aviso": (f"Han llegado {total} respuestas de las {ia['pedidas']} pedidas. " + " ".join(ia["errores"]))
                          if ia["errores"] else None,
                          "consultas": list(dict.fromkeys(r["pregunta"] for r in resp)),
                          "pruebas_reales": [{"pregunta": r["pregunta"], "motor": r["motor"],
                                              "lista": [{"nombre": x["nombre"], "yo": soy_yo(x["nombre"], x.get("web") or "")}
                                                        for x in r["recomendadas"]]} for r in resp],
                          "posicion": (f"Te recomienda en {k} de {total} respuestas (mejor puesto: {min(puestos)}º)" if k
                                       else f"No te nombra en ninguna de las {total} respuestas"),
                          "veces": k, "total": total, "cands": cands, "fuentes": fuentes,
                          "motivos": contar_motivos(resp),
                          "nombradas": [{"nombre": a["nombre"], "motivo": a["motivo"], "yo": a["yo"], "veces": a["veces"],
                                         "motores": a["motores"]} for a in orden_ia[:12]]}
            if not k:
                vias["ia"]["nombradas"].append({"nombre": propia["nombre"], "motivo": "No aparece en ninguna respuesta.",
                                                "yo": True, "veces": 0, "motores": []})
            pedir_consejo = motor_ia()[1]
            if pedir_consejo:
                rivales = ", ".join(a["nombre"] for a in orden_ia if not a["yo"])[:400]
                pr = (f'Un paciente pregunta: "{resp[0]["pregunta"]}". Al buscar en la web sueles recomendar: {rivales}. '
                      f'Ahora mira la clínica «{propia["nombre"]}» ({propia["url"]}): busca en la web qué se dice de ella y revisa su página. '
                      'En "diagnostico" explica con sinceridad, en 2-3 frases, por qué la recomendarías o no frente a las otras. '
                      'En "cambios" da 5 cambios concretos, en su web o fuera de ella, que harían más probable que la recomendaras, '
                      'del más importante al menos. No inventes datos: básate solo en lo que encuentres. Responde en español.')
                f_consejo = ex_consejo.submit(pedir_consejo, pr, ESQ_CONSEJO)
        else:
            v = {"titulo": "Pregunta a una IA", "real": False, "motor": "estimación por listados", "unidad": "listados",
                 "aviso": "No se ha podido preguntar a ninguna IA. " + (ia or {}).get("error", "") +
                          " Se muestra una estimación: las clínicas más citadas en los listados que una IA leería.",
                 "consultas": b.get("consultas", []), "nombradas": [], "consejo": None, "pruebas_reales": []}
            if hay_busqueda:
                p = b["posicion"]
                v.update(posicion=p["ia"], veces=p["ia_veces"], total=p["ia_total"], cands=b["ia"], fuentes=b["fuentes"])
                for c in v["cands"]:
                    c["veces"] = len(c["listados"])
            else:
                v.update(posicion="Sin datos", veces=0, total=0, cands=[], fuentes=[])
            vias["ia"] = v

    elegidos = {}
    for v in vias.values():
        for cand in v["cands"]:
            elegidos.setdefault(cand["host"], cand)

    def una(c):
        r = auditar("https://" + c["host"] + "/", ciudad, tratamiento, pagina=c["pagina"])
        if "error" in r:
            return c["host"], None
        return c["host"], {"nombre": r["nombre"], "url": r["url"], "palabras_trat": r["palabras_trat"],
                           "ilegible": r["palabras_portada"] < 150,
                           "estados": {p["clave"]: p["estado"] for p in r["pruebas"]}}

    with ThreadPoolExecutor(6) as ex:
        hechas = dict(ex.map(una, elegidos.values()))
    orden = {"falta": 0, "parcial": 1, "ok": 2}
    for canal, v in vias.items():
        prim = []
        for c in v.pop("cands"):
            h = hechas.get(c["host"])
            if not h:
                continue
            partes = [c["motivo"]] if c.get("motivo") else []
            if c["listados"]:
                partes.append(f"Citada en: {', '.join(c['listados'][:4])}.")
            if c["directa"] and canal == "google":
                partes.append(f"Mejor puesto: {c['pos'] + 1}º.")
            prim.append(dict(h, nombre=c.get("nombre") or h["nombre"], veces=c.get("veces", 0), porque=" ".join(partes)))
        v["primeras"] = prim
        legibles = [x for x in prim if not x["ilegible"]]
        v["n_legibles"] = len(legibles)
        v["web_ilegible"] = propia["palabras_portada"] < 150
        pr = []
        for p in propia["pruebas"]:
            if not p["peso_" + canal] or v["web_ilegible"]:
                continue
            q = {k: p[k] for k in ("clave", "nombre", "estado", "detalle", "arreglo", "plazo", "como")}
            q["peso"] = p["peso_" + canal]
            q["top"] = [x["nombre"] for x in legibles if x["estados"].get(p["clave"]) == "ok"]
            pr.append(q)
        # Extensión de la página del tratamiento: se compara con la de las primeras, no con una cifra fija.
        largos = sorted(x["palabras_trat"] for x in legibles if x["palabras_trat"])
        for q in pr:
            if q["clave"] == "fondo" and largos:
                mia, med = propia["palabras_trat"], largos[len(largos) // 2]
                q["estado"] = "ok" if mia >= 0.7 * med else "parcial" if mia >= 0.35 * med else "falta"
                q["detalle"] = ((f"Tu página del tratamiento tiene unas {mia} palabras. " if mia else "No tienes página propia del tratamiento. ")
                                + "Las de las primeras tienen: " + ", ".join(str(n) for n in largos) + ".")
                q["arreglo"] = (f"Desarrollar la página hasta acercarse a la extensión de las primeras (unas {med} palabras): "
                                "en qué consiste, pasos, duración, dolor, alternativas, riesgos, cuidados y casos.")
                q["top"] = [x["nombre"] for x in legibles if x["palabras_trat"] >= 0.7 * med]
        # Solo cuenta como carencia lo que tiene al menos una de las primeras; lo demás no está respaldado por esta búsqueda.
        for q in pr:
            q["respaldada"] = bool(q["top"]) or not legibles
        pr.sort(key=lambda q: (q["estado"] == "ok", not q["respaldada"], -len(q["top"]), orden[q["estado"]], -q["peso"]))
        v["pruebas"] = pr
        resp_claves = [q["clave"] for q in pr if q["respaldada"]]
        faltan_yo = sum(1 for q in pr if q["estado"] != "ok" and q["respaldada"])
        faltan_ellas = [sum(1 for c in resp_claves if x["estados"].get(c) != "ok") for x in legibles]
        v["faltan"], v["senales"] = faltan_yo, len(resp_claves)
        for x in prim:
            x["faltan"] = None
        for x, f in zip(legibles, faltan_ellas):
            x["faltan"] = f
        v["web_primero"] = True
        if not v.get("nombradas"):
            v["nombradas"] = [{"nombre": x["nombre"], "motivo": x["porque"], "yo": False, "veces": x["veces"], "motores": []}
                              for x in prim] + [{"nombre": propia["nombre"], "motivo": v["posicion"], "yo": True,
                                                 "veces": v["veces"], "motores": []}]
            v["nombradas"].sort(key=lambda a: -a["veces"])
        if prim and v["total"]:
            mejor_veces = max(x["veces"] for x in prim)
            if v["veces"] >= mejor_veces:
                v["diagnostico"] = (f"Sales tanto o más que las demás ({v['veces']} de {v['total']} {v['unidad']}). "
                                    "Conviene repetir el análisis cada cierto tiempo para ver si se mantiene.")
            elif not legibles or propia["palabras_portada"] < 150:
                v["diagnostico"] = "No se han podido leer bien las webs, así que no hay comparación fiable de sus páginas."
            else:
                media = sum(faltan_ellas) / len(faltan_ellas)
                base = (f"De las {len(resp_claves)} señales de la web que tiene al menos una de las primeras, a ti te faltan "
                        f"{faltan_yo} y a ellas {media:.0f} de media. ")
                if faltan_yo <= media:
                    v["web_primero"] = False
                    v["diagnostico"] = base + ("En lo que esta herramienta puede comprobar, tu web no está peor que las suyas, "
                                               "así que la diferencia no se explica por la web. "
                                               + ("Mira los motivos que da la IA para recomendar a cada una." if canal == "ia"
                                                  else "En Google pesan además factores que aquí no se miden (enlaces, antigüedad, reseñas)."))
                else:
                    v["diagnostico"] = base + "Tu web tiene más carencias que las suyas: es lo primero que conviene completar."
        else:
            v["diagnostico"] = ""
    if f_consejo:
        c = f_consejo.result()
        if "error" not in c and c.get("cambios"):
            c["diagnostico"] = sin_enlaces(c.get("diagnostico", ""))
            for x in c["cambios"]:
                x["titulo"], x["detalle"] = sin_enlaces(x["titulo"]), sin_enlaces(x["detalle"])
            vias["ia"]["consejo"] = c
        else:
            vias["ia"]["consejo"] = None
    ex_consejo.shutdown(wait=False)
    # Reseñas de Google reales: la propia clínica frente a las que más salen en cada vía.
    nombres = list(dict.fromkeys([propia["nombre"]] + [x["nombre"] for v in vias.values() for x in v["primeras"]]))
    fichas = {n: resenas_google(n, ciudad) for n in nombres} if (hay_safari() or clave_google()) else {}
    for canal, v in vias.items():
        filas = []
        for n in [propia["nombre"]] + [x["nombre"] for x in v["primeras"]]:
            f = fichas.get(n)
            filas.append({"nombre": n, "yo": n == propia["nombre"], "nota": f["nota"] if f else None,
                          "n": f["n"] if f else None, "varias": bool(f and f["varias"]),
                          "consulta": f["consulta"] if f else f"{n} {ciudad}"})
        v["resenas"] = sorted(filas, key=lambda f: -(f["n"] or -1)) if fichas else []
        v.setdefault("motivos", [])
    for canal, v in vias.items():
        v["plan"] = plan_de_accion(propia, canal, v)
    propia.pop("pruebas")
    propia.pop("fuera", None)
    propia.update(vias=vias, canales=canales)
    return propia


def plan_de_accion(r, canal, v):
    """Recomendaciones de una vía, separadas según de dónde salen."""
    n3 = v.get("n_legibles", 0)
    con, sin = [], []
    for p in v["pruebas"]:
        if p["estado"] == "ok" or not p["arreglo"]:
            continue
        item = {"titulo": p["nombre"], "texto": p["arreglo"], "como": p.get("como", ""),
                "nota": (f"Lo tienen {len(p['top'])} de las {n3} primeras." if p["top"] and n3 else "")}
        (con if p["respaldada"] else sin).append(item)
    nombre, ciudad, trat = r["nombre"], r["ciudad"], r["tratamiento"]
    bloques = []
    if v.get("consejo"):
        bloques.append({"plazo": "Lo que dice ChatGPT que tendrías que cambiar (texto suyo; puede contener errores, compruébalo)",
                        "items": [{"titulo": c["titulo"], "texto": c["detalle"], "nota": ""} for c in v["consejo"]["cambios"][:6]]})
    if v.get("web_ilegible"):
        con = [{"titulo": "Que el contenido de la web llegue en el código de la página", "nota": "",
                "texto": "Al pedir tu portada, un programa recibe una página casi sin texto: el contenido se dibuja después con "
                         "JavaScript. Los buscadores pueden tardar en leerlo y varios rastreadores de IA no ejecutan JavaScript. "
                         "Pide a quien lleva la web que el texto venga ya en el HTML (renderizado en servidor o plantilla estática)."}]
    bloques.append({"plazo": "En tu web: lo que tienen las primeras y a ti te falta" if n3 and not v.get("web_ilegible")
                    else "En tu web: lo que falta", "items": con})
    datos = []
    if canal == "ia":
        fuera = [f for f in v.get("fuentes", []) if f["apareces"] is False]
        if fuera:
            datos.append({"titulo": "Páginas que la IA ha leído y donde tu clínica no aparece", "nota": "",
                          "texto": ", ".join(dict.fromkeys(f["host"] for f in fuera[:8]))
                                   + ". Son las fuentes reales de estas respuestas: conviene estar en ellas."})
    bloques.append({"plazo": "Fuera de tu web: lo que ha salido en este análisis", "items": datos})
    # --- Reseñas: lo que tiene que hacer la propia clínica ---
    res = v.get("resenas", [])
    mia = next((f for f in res if f["yo"]), None)
    suyas = [f for f in res if not f["yo"] and f["n"] is not None]
    if mia and mia["n"] is not None and suyas:
        lista = ", ".join(f"{f['nombre']} {f['n']} ({f['nota']})" for f in suyas)
        mayor = max(f["n"] for f in suyas)
        if mia["n"] < mayor:
            cabecera = (f"Tienes {mia['n']} reseñas en Google (nota {mia['nota']}). Las que más salen: {lista}. "
                        f"Te faltan {mayor - mia['n']} para igualar a la que más tiene.")
        else:
            cabecera = (f"Tienes {mia['n']} reseñas en Google (nota {mia['nota']}), tantas o más que las que más salen: {lista}. "
                        "Aquí no vas por detrás; mantén el ritmo.")
    elif mia and mia["n"] is not None:
        cabecera = f"Tienes {mia['n']} reseñas en Google (nota {mia['nota']}). No se han podido leer las de las demás para comparar."
    elif suyas:
        cabecera = ("No se ha podido leer tu ficha de Google al buscar tu nombre: comprueba que existe y que el nombre coincide con el de la web. "
                    "Las que más salen tienen: " + ", ".join(f"{f['nombre']} {f['n']} ({f['nota']})" for f in suyas) + ".")
    else:
        cabecera = ""
    motivo_op = next((m for m in v.get("motivos", []) if m["motivo"].startswith("Opiniones")), None)
    if motivo_op:
        cabecera += (f" En este análisis, la IA mencionó las opiniones de pacientes en {motivo_op['n']} de sus "
                     f"{motivo_op['total']} recomendaciones.")
    pasos = [
        {"titulo": "Situación real", "texto": cabecera, "nota": ""} if cabecera else None,
        {"titulo": "Consigue tu enlace directo de reseña", "nota": "",
         "texto": "Entra en tu Perfil de Empresa de Google (busca el nombre de tu clínica con tu cuenta de Google) → «Pedir reseñas» → copia el enlace. "
                  "Conviértelo en un código QR y ponlo en recepción y en la tarjeta de próxima cita."},
        {"titulo": "Pídela en el momento adecuado", "nota": "",
         "texto": "Al terminar un tratamiento con buen resultado, en persona. Ese mismo día, envía el enlace por WhatsApp o correo. "
                  "Nombra a una persona del equipo como responsable de pedirla."},
        {"titulo": "Anima a que cuenten qué tratamiento se hicieron", "nota": "",
         "texto": f"Una reseña que dice «me puse {trat} y…» describe lo que haces mejor que una que solo dice «muy bien»."},
        {"titulo": "Responde a todas, también a las negativas", "nota": "",
         "texto": "Con educación, sin datos clínicos del paciente y ofreciendo hablarlo en la clínica."},
        {"titulo": "No compres reseñas ni las cambies por descuentos", "nota": "",
         "texto": "Las normas de Google lo prohíben: puede retirarlas y sancionar la ficha."}]
    bloques.append({"plazo": "Reseñas: esto solo lo puedes hacer tú (los pasos son práctica habitual, no salen de este análisis)",
                    "items": [p for p in pasos if p]})
    general = []
    if canal == "ia":
        general += [
            {"titulo": "Perfiles en Doctoralia y Top Doctors", "nota": "",
             "texto": "Crear o reclamar el perfil, completarlo y pedir opinión a los pacientes."},
            {"titulo": "Menciones en prensa o blogs del sector", "nota": "",
             "texto": f"Entrevista, caso clínico o artículo que nombre «{nombre}» junto a «{trat}» y «{ciudad}»."},
            {"titulo": "Repetir este análisis cada mes", "nota": "",
             "texto": "Las respuestas de la IA cambian; así se ve si lo anterior funciona."}]
    else:
        general += [
            {"titulo": "Ficha de Google Business completa y activa", "nota": "",
             "texto": f"Categoría correcta, «{trat}» en servicios, fotos reales y horario al día. "
                      "Nombre, dirección y teléfono idénticos a los de la web."},
            {"titulo": "Enlaces desde webs locales y del sector", "nota": "",
             "texto": "Colegio profesional, sociedades científicas, proveedores y prensa local."},
            {"titulo": "Dar de alta la web en Google Search Console", "nota": "",
             "texto": "Es gratis y enseña la posición real en Google para cada búsqueda, mes a mes."}]
    bloques.append({"plazo": "Otras cosas que solo puedes hacer tú (prácticas generales, no salen de este análisis)", "items": general})
    bloques.append({"plazo": "Opcional: no lo tiene ninguna de las primeras, así que este análisis no demuestra que ayude",
                    "items": sin})
    return bloques


if __name__ == "__main__":
    a = sys.argv[1:] + ["Madrid", "implantes dentales", "ambos"]
    r = comparar(a[0], a[1], a[2], modo=a[3] if a[3] in ("ambos", "google", "ia") else "ambos")
    if "error" in r:
        print(r["error"]); sys.exit()
    print(r["nombre"], "|", r["url"], "| avisos:", r["avisos"])
    for c, v in r["vias"].items():
        print("==", v["titulo"], "| motor:", v["motor"], "| real:", v["real"], "|", v["posicion"], "|", v["veces"], "de", v["total"])
        print("   diagnóstico:", v["diagnostico"])
        print("   aviso:", v["aviso"])
        for x in v["nombradas"]:
            print("   RANKING:", x["veces"], x["nombre"], "<- YO" if x["yo"] else "")
        for x in v["primeras"]:
            print("   PRIMERA:", x["veces"], x["nombre"], x["url"], "| faltan:", x["faltan"], "| ilegible:", x["ilegible"])
        for p in v["pruebas"]:
            print(f"   [{p['estado']:7}] {'resp' if p['respaldada'] else 'SINR'} top={len(p['top'])} {p['nombre'][:50]} — {p['detalle'][:90]}")
        for b in v["plan"]:
            print("   PLAN:", b["plazo"][:60], "->", [i["titulo"][:28] for i in b["items"]])
