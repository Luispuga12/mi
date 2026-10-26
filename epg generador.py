import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
import requests
from bs4 import BeautifulSoup

print("=== INICIANDO GENERADOR DE EPG MULTI-DÍA (SEMANAL) ===")

ARCHIVO_M3U = "Listaiptv3"
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
    """Convierte texto de hora de GatoTV al formato XMLTV asegurando la hora local de México (-0600)."""
    try:
        hora_str = hora_str.upper().replace(".", "").strip()
        dt_hora = datetime.strptime(hora_str, "%I:%M %p")
        
        # Combinamos la fecha objetivo con la hora extraída de forma limpia
        dt_completo = datetime(
            year=fecha_objetivo.year,
            month=fecha_objetivo.month,
            day=fecha_objetivo.day,
            hour=dt_hora.hour,
            minute=dt_hora.minute,
            second=0
        )
        # Forzamos estrictamente el formato XMLTV con el sufijo de México (-0600)
        return dt_completo.strftime("%Y%m%d%H%M%S") + " -0600"
    except Exception:
        return fecha_objetivo.strftime("%Y%m%d%H%M%S") + " -0600"

def extraer_programacion_dia(slug, fecha_obj):
    """Extrae los programas de un canal detectando automáticamente el cambio de día por medianoche."""
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
            
            # Variables para rastrear el cambio de día automático en base a la secuencia horaria
            current_date_offset = 0
            last_minutes = -1
            
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

                    # Convertir hora de inicio a minutos del día para rastrear la secuencia
                    dt_temp_start = datetime.strptime(hora_inicio_raw.upper().replace(".", "").strip(), "%I:%M %p")
                    total_minutes = dt_temp_start.hour * 60 + dt_temp_start.minute
                    
                    # Si las horas retroceden bruscamente (ej: de noche a la 1 AM), cruzamos medianoche de forma automática
                    if last_minutes != -1 and total_minutes < last_minutes and last_minutes > 1200:
                        current_date_offset += 1
                    
                    last_minutes = total_minutes
                    fecha_prog_obj = fecha_obj + timedelta(days=current_date_offset)
                    
                    start_time = convertir_a_formato_xmltv(hora_inicio_raw, fecha_prog_obj)
                    
                    # Si el programa termina después de la medianoche
                    fecha_fin_obj = fecha_prog_obj
                    dt_temp_end = datetime.strptime(hora_fin_raw.upper().replace(".", "").strip(), "%I:%M %p")
                    end_minutes = dt_temp_end.hour * 60 + dt_temp_end.minute
                    
                    if end_minutes < total_minutes:
                        fecha_fin_obj = fecha_prog_obj + timedelta(days=1)
                        
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

    print(f"    [+] Canales totales leídos en el M3U: {len(canales_a_procesar)}")

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
    print(f"\n[OK] ¡Archivo {ARCHIVO_SALIDA} generado con éxito!")

if __name__ == "__main__":
    generar_epg()
