# Publica el siguiente reel pendiente de reels.json (mas viejo primero).
# Corre en GitHub Actions cada 15 min. Los videos se sirven desde GitHub Pages.
#   python publicar.py            -> publica si toca
#   python publicar.py --prueba   -> sube el siguiente reel a Instagram pero NO lo publica
import csv, json, os, sys, time, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone

HORA_INICIO, HORA_FIN = 8, 23            # hora de Republica Dominicana
MAX_DIAS_INICIALES, DIAS_INICIALES = 10, 2  # arranque suave en cuenta nueva
MAX_POR_DIA = 30
MAX_ERRORES = 3                          # tras 3 fallos se salta ese reel

TZ = timezone(timedelta(hours=-4))  # Republica Dominicana, sin horario de verano
API = "https://graph.instagram.com/v23.0"
BASE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(BASE, "publicados.csv")
TOKEN = os.environ["IG_TOKEN"]
VIDEOS_URL = os.environ["VIDEOS_URL"].rstrip("/")  # https://<usuario>.github.io/<repo>


def call(method, url, params=None):
    data = urllib.parse.urlencode(dict(params or {}, access_token=TOKEN))
    req = (urllib.request.Request(url, data=data.encode(), method="POST") if method == "POST"
           else urllib.request.Request(f"{url}?{data}"))
    try:
        return json.load(urllib.request.urlopen(req, timeout=120))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{e.code} {e.read().decode()}") from None


def log(carpeta, estado, detalle=""):
    with open(LOG, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([datetime.now(TZ).isoformat(timespec="seconds"), carpeta, estado, detalle])


def main():
    prueba = "--prueba" in sys.argv
    hechos = list(csv.DictReader(open(LOG, encoding="utf-8")))
    ok = [h for h in hechos if h["estado"] == "publicado"]
    now = datetime.now(TZ)
    hoy = now.strftime("%Y-%m-%d")

    if not prueba:
        dias_previos = {h["fecha"][:10] for h in ok} - {hoy}
        maximo = MAX_DIAS_INICIALES if len(dias_previos) < DIAS_INICIALES else MAX_POR_DIA
        if not HORA_INICIO <= now.hour < HORA_FIN:
            return print("fuera de horario")
        if sum(h["fecha"][:10] == hoy for h in ok) >= maximo:
            return print(f"limite diario alcanzado ({maximo})")
        espacio = (HORA_FIN - HORA_INICIO) * 3600 / maximo
        if ok and (now - datetime.fromisoformat(ok[-1]["fecha"])).total_seconds() < espacio - 300:
            return print("todavia no toca")

    listos = {h["carpeta"] for h in ok}
    errores = {}
    for h in hechos:
        if h["estado"] == "error":
            errores[h["carpeta"]] = errores.get(h["carpeta"], 0) + 1
    reels = json.load(open(os.path.join(BASE, "reels.json"), encoding="utf-8"))
    pendientes = [r for r in reels if r["carpeta"] not in listos and errores.get(r["carpeta"], 0) < MAX_ERRORES]
    if not pendientes:
        return print("no quedan reels pendientes")
    r = pendientes[0]

    try:
        c = call("POST", f"{API}/me/media", {
            "media_type": "REELS", "video_url": f"{VIDEOS_URL}/{r['carpeta']}.mp4",
            "caption": r["caption"], "share_to_feed": "true"})
        for _ in range(60):  # hasta 10 min procesando
            st = call("GET", f"{API}/{c['id']}", {"fields": "status_code,status"})
            if st["status_code"] == "FINISHED":
                break
            if st["status_code"] == "ERROR":
                raise RuntimeError(st.get("status"))
            time.sleep(10)
        else:
            raise RuntimeError("Instagram tardo demasiado procesando el video")
        if prueba:
            return print(f"PRUEBA OK: {r['carpeta']} procesado, no publicado")
        pub = call("POST", f"{API}/me/media_publish", {"creation_id": c["id"]})
        log(r["carpeta"], "publicado", pub["id"])
        print(f"publicado {r['carpeta']} ({len(ok) + 1}/{len(reels)})")
    except Exception as e:
        if not prueba:
            log(r["carpeta"], "error", str(e)[:500])
        print(f"ERROR {r['carpeta']}: {e}")
        sys.exit(1)


def guardar_registro():
    # Sube publicados.csv al repo para no perder el estado si el job se corta
    import subprocess
    run = lambda *a: subprocess.run(["git", *a], cwd=BASE, check=False)
    run("add", "publicados.csv")
    if run("diff", "--cached", "--quiet").returncode:
        run("commit", "-q", "-m", "registro de publicaciones")
        run("pull", "-q", "--rebase")
        run("push", "-q")


if __name__ == "__main__":
    if "--bucle" in sys.argv:
        # ponytail: el cron de GitHub es poco fiable; el job revisa cada 5 min por ~5.5 h
        # y el workflow se relanza solo al terminar (limite de GitHub: 6 h por job)
        fin = time.time() + 5.5 * 3600
        while time.time() < fin:
            try:
                main()
            except SystemExit:
                pass
            guardar_registro()
            sys.stdout.flush()
            time.sleep(300)
    else:
        main()
