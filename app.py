import io
import re
import json
import smtplib, ssl
from email.message import EmailMessage

import streamlit as st
import pandas as pd

# Lectura de documentos
from docx import Document as DocxDocument
from pdfminer.high_level import extract_text as pdf_extract_text

# =============== Configuración ===============
st.set_page_config(page_title="Auto-corrección de Prácticos", page_icon="📝", layout="centered")
st.title("📝 Auto-corrección de Prácticos")
st.caption(
    "Suba su archivo, elija el práctico y escriba **Nombre y Apellido** y el **correo** del alumno. "
    "La app devuelve puntaje por criterios y envía la devolución al alumno y a la cátedra."
)

# =============== Lista de prácticos (extendida + dinámica) ===============
# Base que viste en tu app; podés sumar más con Secrets/CSV/textarea sin tocar código.
PRACTICOS_BASE = [
    "Práctico N° 1 — IA en la escritura del proyecto",
    "Práctico N° 1 — IA en la escritura del proyecto (variante)",
    "Práctico N° 2 — Establecimiento de Métodos de Recolección de Datos y Tipos de Muestreos. Tamaño de muestra",
    "Práctico N° 3 — Operacionalización de Variables y Determinación de Métodos de Análisis de Datos",
    "Práctico N° 4 — Introducción + Marco teórico + Búsqueda (≈500 palabras en total)",
    "Trabajo práctico Módulo 5 — Mendeley: citas en Word y bibliografía",
    "Trabajo práctico Módulo 6 — Estilos de Word e índice automático",
    "Práctico N° 7 — Análisis cuantitativo",
    "Práctico N° 8 — Análisis cualitativo",
]

with st.expander("⚙️ Configurar lista de prácticos (opcional)"):
    st.write("La lista puede venir de **Secrets** (`PRACTICOS_JSON`), de un **CSV** (columna `practico`) o manual (uno por línea).")
    csv_practicos = st.file_uploader("CSV con columna 'practico' (opcional)", type=["csv"], key="csv_practicos")
    manual_practicos_text = st.text_area("Agregar prácticos manualmente (uno por línea)", value="", height=120)

def cargar_practicos() -> list:
    merged = []
    # 1) Secrets JSON
    if "PRACTICOS_JSON" in st.secrets:
        try:
            data = json.loads(st.secrets["PRACTICOS_JSON"])
            if isinstance(data, list):
                for x in data:
                    s = str(x).strip()
                    if s and s not in merged:
                        merged.append(s)
        except Exception:
            pass
    # 2) CSV opcional
    if csv_practicos is not None:
        try:
            dfp = pd.read_csv(csv_practicos)
            if "practico" in dfp.columns:
                for x in dfp["practico"].dropna().tolist():
                    s = str(x).strip()
                    if s and s not in merged:
                        merged.append(s)
        except Exception:
            pass
    # 3) Manual (textarea)
    if manual_practicos_text.strip():
        for ln in manual_practicos_text.splitlines():
            s = ln.strip()
            if s and s not in merged:
                merged.append(s)
    # 4) Base por defecto
    for s in PRACTICOS_BASE:
        if s not in merged:
            merged.append(s)
    return merged

PRACTICOS = cargar_practicos()

# =============== Criterios (misma rúbrica) ===============
CRITERIOS = [
    ("Tema y Título", 20, [r"\btema\b", r"\bt[ií]tulo\b"]),
    ("Paradigma", 15, [r"\bparadigma\b"]),
    ("Pregunta de investigación", 20, [r"\bpregunta de investigaci[oó]n\b", r"\bpregunta problema\b"]),
    ("Objetivos", 30, [r"\bobjetivo(s)?\b", r"\bobjetivo general\b", r"\bobjetivos espec[íi]ficos\b"]),
    ("Hipótesis (si corresponde)", 15, [r"\bhip[oó]tesis\b"]),
]
TOTAL_MAX = sum(p for _, p, _ in CRITERIOS)

# =============== Entradas ===============
alumno_nombre = st.text_input("Nombre y apellido del alumno", placeholder="Ej.: Ana María Pérez")
alumno_email  = st.text_input("Correo electrónico del alumno", placeholder="nombre@uccuyo.edu.ar")
practico      = st.selectbox("Práctico", PRACTICOS or ["(definí la lista en el panel de configuración)"])
archivo       = st.file_uploader("Subir archivo (.docx o .pdf)", type=["docx", "pdf"])

# =============== Botón principal ===============
if st.button("Corregir y Enviar"):
    # Validaciones mínimas
    if not alumno_nombre.strip():
        st.warning("Por favor, completá **Nombre y apellido del alumno**.")
        st.stop()
    if not alumno_email.strip():
        st.warning("Por favor, ingresá el **correo** del alumno.")
        st.stop()
    if not archivo:
        st.warning("Subí el archivo (.docx o .pdf).")
        st.stop()
    if not PRACTICOS:
        st.warning("Definí al menos un práctico.")
        st.stop()

    # =============== Lectura del archivo ===============
    texto = ""
    try:
        if archivo.name.lower().endswith(".docx"):
            with io.BytesIO(archivo.read()) as bio:
                doc = DocxDocument(bio)
                texto = "\n".join(p.text for p in doc.paragraphs)
        elif archivo.name.lower().endswith(".pdf"):
            with io.BytesIO(archivo.read()) as bio:
                texto = pdf_extract_text(bio)
        else:
            st.error("Formato no soportado.")
            st.stop()
    except Exception as e:
        st.error(f"No se pudo leer el archivo: {e}")
        st.stop()

    text_lc = texto.lower()

    # =============== Valoración simple por criterios ===============
    desglose = []
    puntaje_total = 0
    explicaciones = []
    for nombre, puntaje_max, patrones in CRITERIOS:
        hallado = any(re.search(pat, text_lc, flags=re.IGNORECASE) for pat in patrones)
        puntos = puntaje_max if hallado else 0
        puntaje_total += puntos
        exp = f"Incluye {nombre.lower()}." if hallado else f"No se identificó {nombre.lower()}."
        desglose.append((nombre, puntos, puntaje_max, exp))
        explicaciones.append(f"- {nombre}: {puntos}/{puntaje_max}. {exp}")

    puntaje_total = min(puntaje_total, TOTAL_MAX)

    # =============== Mensaje de devolución (preview) ===============
    desglose_por_criterios = "\n".join(explicaciones)
    comentarios_generales = "Se evaluó la presencia de secciones fundamentales de un anteproyecto."

    mensaje_preview = f"""Resultado de la corrección automática:

ALUMNO/A: {alumno_nombre}
{practico}
Puntaje: {puntaje_total}/{TOTAL_MAX}

Desglose por criterios:
{desglose_por_criterios}

Comentarios generales:
{comentarios_generales}
"""

    st.success("✔️ Corregido y enviado al correo del alumno.")
    st.text_area("Mensaje enviado:", mensaje_preview, height=420)

    # =============== Envío de correos (SMTP) ===============
    # Configurá estos secrets en Streamlit Cloud > Settings > Secrets
    SMTP_HOST     = st.secrets.get("SMTP_HOST", "")
    SMTP_PORT     = int(st.secrets.get("SMTP_PORT", 465))
    SMTP_USER     = st.secrets.get("SMTP_USER", "")
    SMTP_PASS     = st.secrets.get("SMTP_PASS", "")
    SENDER_EMAIL  = st.secrets.get("SENDER_EMAIL", "")
    # Si no definís EMAIL_CATEDRA en secrets, usa SIEMPRE esta casilla:
    EMAIL_CATEDRA = st.secrets.get("EMAIL_CATEDRA", "investigacion@uccuyo.edu.ar")

    if not all([SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SENDER_EMAIL]):
        st.warning("⚠️ Falta configurar credenciales SMTP en **st.secrets**. Abajo podés descargar el mensaje en TXT.")
    else:
        def enviar(destinatario: str, incluir_correo_alumno: bool = False):
            subject = f"Resultado — {practico} · {alumno_nombre}"

            # Para tu copia agregamos explícitamente el correo del alumno al inicio del cuerpo
            body = mensaje_preview
            if incluir_correo_alumno:
                body = f"Correo del alumno: {alumno_email}\n\n" + body

            msg = EmailMessage()
            msg["Subject"] = subject
            msg["From"] = SENDER_EMAIL
            msg["To"] = destinatario
            msg.set_content(body)

            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx) as server:
                server.login(SMTP_USER, SMTP_PASS)
                server.send_message(msg)

        try:
            enviar(alumno_email)                                # al alumno
            enviar(EMAIL_CATEDRA, incluir_correo_alumno=True)   # SIEMPRE a tu casilla, con la línea "Correo del alumno: ..."
        except Exception as e:
            st.warning(f"No se pudo enviar el correo automáticamente: {e}")

    # =============== Descarga local del resultado (TXT) ===============
    nombre_txt = f"Devolucion_{alumno_nombre.replace(' ', '_')}.txt"
    st.download_button(
        "⬇️ Descargar devolución (TXT)",
        data=mensaje_preview.encode("utf-8"),
        file_name=nombre_txt,
        mime="text/plain"
    )

    # Tabla de desglose (visual)
    df_desglose = pd.DataFrame([
        {"Criterio": n, "Puntos": p, "Máximo": m, "Explicación": e}
        for (n, p, m, e) in desglose
    ])
    st.subheader("Desglose por criterios")
    st.dataframe(df_desglose, use_container_width=True)
