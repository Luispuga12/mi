import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
import requests
from bs4 import BeautifulSoup

print("=== INICIANDO GENERADOR DE EPG MULTI-DÍA (SEMANAL) ===")

ARCHIVO_M3U = "lista.m3u"
ARCHIVO_SALIDA = "epg.xml"

# Cantidad de días a extraer a partir de hoy (ej. 3 o 7)
DIAS_A_EXTRAER = 7

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "es-MX,es;q=0.9"
}

# Zona horaria de México (UTC-6)
MEXICO_TZ = timezone(timedelta(hours=-6))

def convertir_a_formato_xmltv(hora_str, fecha_objetivo):
    """Convierte texto de hora de GatoTV al formato XMLTV con la fecha exacta ingresada."""
    try:
        hora_str = hora_str.upper().replace(".", "").strip()
        dt_hora = datetime.strptime(hora_str, "%I:%M %p")
        dt_completo = dt_hora.replace(
            year=fecha_objetivo.year, 
            month=fecha_objetivo.month, 
            day=fecha_objetivo.day, 
            tzinfo=MEXICO_TZ
        )
        return dt_completo.strftime("%Y%m%d%H%M00 -0600")
    except Exception:
        return fecha_objetivo.strftime("%Y%m%d%H%M00 -0600")

def extraer_programacion_dia(slug, fecha_obj):
    """Extrae los programas de un canal para una fecha específica."""
    fecha_str = fecha_obj.strftime("%Y-%m-%d")
    
    # El día de hoy usa la URL base; los días futuros usan /YYYY-MM-DD
    hoy_str = datetime.now(MEXICO_TZ).strftime("%Y-%m-%d")
    if fecha_str == hoy_str:
        url = f"https://www.gatotv.com/canal/{slug}"
    else:
        url = f"https://www.gatotv.com/canal/{slug}/{fecha_str}"
        
    programas = []
    
    try:
        response = requests.get(url, headers=HEADERS, timeout=8)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            tabla = soup.find('table', class_='tbl_planificacion') or soup
            
            for tr in tabla.find_all('tr'):
                tds = tr.find_all('td')
                if len(tds) >= 3:
                    hora_inicio_raw = tds[0].text.strip()
                    hora_fin_raw = tds[1].text.strip()
                    programa_td = tds[2]
                    
                    if not ("AM" in hora_inicio_raw.upper() or "PM" in hora_inicio_raw.upper()):
                        continue
                    
                    titulo_elem = programa_td.find('a')
                    titulo_str = titulo_elem.text.strip() if titulo_elem else programa_td.text.strip()
                    titulo_str = " ".join(titulo_str.split())
                    
                    titulo_lower = titulo_str.lower()
                    if (
                        len(titulo_str) > 80 or 
                        not titulo_str or
                        "horarios para" in titulo_lower or
                        "horarios de programación" in titulo_lower or
                        titulo_lower in ["programa", "mañana", "tarde", "noche", "guía de tv"]
                    ):
                        continue

                    start_time = convertir_a_formato_xmltv(hora_inicio_raw, fecha_obj)
                    
                    # Si el programa termina después de la medianoche, se ajusta al día siguiente
                    fecha_fin_obj = fecha_obj
                    if "AM" in hora_fin_raw.upper() and "PM" in hora_inicio_raw.upper():
                        fecha_fin_obj = fecha_obj + timedelta(days=1)
                        
                    stop_time = convertir_a_formato_xmltv(hora_fin_raw, fecha_fin_obj)
                    
                    if titulo_elem:
                        titulo_elem.extract()
                    desc_real = programa_td.text.strip()
                    desc_real = " ".join(desc_real.split())

                    if not desc_real or len(desc_real) < 3:
                        desc_real = f"{titulo_str} ({hora_inicio_raw} - {hora_fin_raw})"

                    programas.append({
                        "start": start_time,
                        "stop": stop_time,
                        "titulo": titulo_str,
                        "desc": desc_real
                    })
    except Exception as e:
        pass
        
    return programas

def generar_epg():
    if not os.path.exists(ARCHIVO_M3U):
        print(f"[!] ERROR: No se encontró el archivo '{ARCHIVO_M3U}'.")
        return

    print("--> 1. Leyendo lista M3U...")
    canales_a_procesar = []
    
    with open(ARCHIVO_M3U, "r", encoding="utf-8", errors="ignore") as f:
        for linea in f:
            if linea.startswith("#EXTINF:"):
                match_id = re.search(r'tvg-id="([^"]*)"', linea)
                tvg_id = match_id.group(1).strip() if match_id else ""
                
                partes = linea.split(",")
                nombre_raw = partes[-1].strip() if len(partes) > 1 else "Canal sin nombre"
                
                canales_a_procesar.append({
                    "nombre": nombre_raw,
                    "tvg_id": tvg_id
                })

    print(f"   [+] Canales totales leídos en el M3U: {len(canales_a_procesar)}")

    tv = ET.Element("tv", {
        "generator-info-name": "Tvg-Id Multi-Day EPG Generator",
        "generator-info-url": "https://github.com/Luispuga12/mi"
    })

    programas_totales = 0
    canales_con_guia = 0
    hoy = datetime.now(MEXICO_TZ)

    print(f"\n--> 2. Extrayendo programación de {DIAS_A_EXTRAER} días desde GatoTV...")
    for idx, canal in enumerate(canales_a_procesar, 1):
        nombre = canal["nombre"]
        tvg_id = canal["tvg_id"]
        
        xml_channel_id = tvg_id if tvg_id else re.sub(r'[^a-z0-9]', '', nombre.lower())

        ch_elem = ET.SubElement(tv, "channel", {"id": xml_channel_id})
        dn_elem = ET.SubElement(ch_elem, "display-name", {"lang": "es"})
        dn_elem.text = nombre

        if tvg_id:
            slug = tvg_id.strip().lower().replace(" ", "_")
            slug = re.sub(r'[^a-z0-9_]', '', slug)
            
            eventos_canal = []
            # Recorrer cada uno de los días configurados
            for i in range(DIAS_A_EXTRAER):
                fecha_consulta = hoy + timedelta(days=i)
                evs_dia = extraer_programacion_dia(slug, fecha_consulta)
                eventos_canal.extend(evs_dia)
            
            if eventos_canal:
                print(f"[{idx}/{len(canales_a_procesar)}] '{nombre}' (ID: {slug}) -> ¡{len(eventos_canal)} programas cargados para {DIAS_A_EXTRAER} días!")
                for ev in eventos_canal:
                    prog = ET.SubElement(tv, "programme", {
                        "start": ev["start"],
                        "stop": ev["stop"],
                        "channel": xml_channel_id
                    })
                    
                    t = ET.SubElement(prog, "title", {"lang": "es"})
                    t.text = ev["titulo"]
                    
                    d = ET.SubElement(prog, "desc", {"lang": "es"})
                    d.text = ev["desc"]
                    
                    programas_totales += 1
                canales_con_guia += 1
            else:
                print(f"[{idx}/{len(canales_a_procesar)}] '{nombre}' (ID: {slug}) -> [!] Sin eventos.")
        else:
            print(f"[{idx}/{len(canales_a_procesar)}] '{nombre}' -> Omitido (Sin tvg-id).")

    tree = ET.ElementTree(tv)
    tree.write(ARCHIVO_SALIDA, encoding="utf-8", xml_declaration=True)
    print(f"\n[OK] ¡Generación finalizada! Se cargaron {programas_totales} programas abarcando {DIAS_A_EXTRAER} días para {canales_con_guia} canales.")

if __name__ == "__main__":
    generar_epg()
