import io
import re
import json
import streamlit as st
import pandas as pd

# Validación de email
from email_validator import validate_email, EmailNotValidError

# Lectura de documentos
from docx import Document as DocxDocument
from pdfminer.high_level import extract_text as pdf_extract_text

# Envío por SendGrid (opcional)
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

# Envío por SMTP (fallback)
import smtplib, ssl
from email.message import EmailMessage

# =============== Configuración ===============
st.set_page_config(page_title="Auto-corrección de Prácticos", page_icon="📝", layout="centered")
st.title("📝 Auto-corrección de Prácticos")
st.caption(
    "Subí el archivo, elegí el práctico y escribí **Nombre y Apellido** y el **correo** del alumno. "
    "La app devuelve puntaje por criterios y envía la devolución al alumno y a la cátedra."
)

# =============== Lista de prácticos (extendida + dinámica) ===============
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
    # 1) Secrets (JSON)
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
    # 2) CSV
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
    # 3) Manual
    if manual_practicos_text.strip():
        for ln in manual_practicos_text.splitlines():
            s = ln.strip()
            if s and s not in merged:
                merged.append(s)
    # 4) Base
    for s in PRACTICOS_BASE:
        if s not in merged:
            merged.append(s)
    return merged

PRACTICOS = cargar_practicos()

# =============== Rúbricas por práctico ===============
# Formato: lista de tuplas (NombreCriterio, Puntos, [patrones_regex])
RUBRICA_GENERICA = [
    ("Tema y Título", 20, [r"\btema\b", r"\bt[ií]tulo\b"]),
    ("Paradigma", 15, [r"\bparadigma\b"]),
    ("Pregunta de investigación", 20, [r"\bpregunta de investigaci[oó]n\b", r"\bpregunta problema\b"]),
    ("Objetivos", 30, [r"\bobjetivo(s)?\b", r"\bobjetivo general\b", r"\bobjetivos espec[íi]ficos\b"]),
    ("Hipótesis (si corresponde)", 15, [r"\bhip[oó]tesis\b"]),
]

# Rúbrica específica — Práctico N° 7 (según tus correos “buenos”)
RUBRICA_CUANTITATIVO = [
    ("Medidas descriptivas", 25, [
        r"\bmedia\b|\bpromedio\b|\bdesviaci[oó]n estándar\b|\bmediana\b|\bmoda\b|\bfrecuencias?\b"
    ]),
    ("Significancia / Mann-Whitney", 25, [
        r"\bp-?value\b|\bp valor\b|\bsignificancia\b|\bmann-?whitney\b|\bU de Mann-Whitney\b"
    ]),
    ("Confiabilidad \(Cronbach\)", 25, [
        r"\bcronbach\b|\balfa de cronbach\b|\balpha de cronbach\b"
    ]),
    ("Relación entre variables", 25, [
        r"\bcorrelaci[oó]n\b|\bspearman\b|\bpearson\b|\ban[aá]lisis de cl[úu]ster\b|\bcluster\b"
    ]),
]

def obtener_rubrica(nombre_practico: str):
    if "cuantitativ" in nombre_practico.lower():  # “Análisis cuantitativo”
        return RUBRICA_CUANTITATIVO
    # Podés seguir agregando casos especiales aquí (cualitativo, etc.)
    return RUBRICA_GENERICA

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
    try:
        validate_email(alumno_email, check_deliverability=False)
    except EmailNotValidError as e:
        st.warning(f"Correo del alumno no válido: {e}")
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

    # =============== Valoración según PRÁCTICO ELEGIDO ===============
    CRITERIOS = obtener_rubrica(practico)
    TOTAL_MAX = sum(p for _, p, _ in CRITERIOS)

    desglose = []
    puntaje_total = 0
    explicaciones = []

    for nombre, puntaje_max, patrones in CRITERIOS:
        hallado = any(re.search(pat, text_lc, flags=re.IGNORECASE) for pat in patrones)
        puntos = puntaje_max if hallado else 0
        puntaje_total += puntos
        if "Cronbach" in nombre:
            exp_ok = "Menciona alfa de Cronbach con valor." if hallado else "Menciona alfa de Cronbach sin valor o no lo incluye."
        elif "Significancia" in nombre:
            exp_ok = "Menciona prueba de significancia (p-value o Mann-Whitney)." if hallado else "No menciona significancia (p-value o Mann-Whitney)."
        elif "Relación entre variables" in nombre:
            exp_ok = "Presenta correlación (Spearman/Pearson) o análisis de clúster." if hallado else "No presenta relación entre variables (Spearman/cluster)."
        elif "Medidas descriptivas" in nombre:
            exp_ok = "Menciona al menos una medida." if hallado else "No incluye medidas descriptivas."
        else:
            exp_ok = f"Incluye {nombre.lower()}." if hallado else f"No se identificó {nombre.lower()}."

        desglose.append((nombre, puntos, puntaje_max, exp_ok))
        explicaciones.append(f"- {nombre}: {puntos}/{puntaje_max}. {exp_ok}")

    puntaje_total = min(puntaje_total, TOTAL_MAX)

    # =============== Mensaje de devolución (preview) ===============
    desglose_por_criterios = "\n".join(explicaciones)
    comentarios_generales = "Se evaluó la presencia de secciones fundamentales del práctico."

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

    # =============== Envío de correos ===============

    # Intento 1: SendGrid (si hay API Key y remitente)
    SENDGRID_API_KEY = st.secrets.get("SENDGRID_API_KEY", "")
    SENDER_EMAIL_SG  = st.secrets.get("SENDER_EMAIL", "")

    # Fallback: SMTP Gmail con tus secrets viejos
    SMTP_HOST   = "smtp.gmail.com"
    SMTP_PORT   = 465
    EMAIL_USER  = st.secrets.get("EMAIL_USER", "")
    EMAIL_PASS  = st.secrets.get("EMAIL_PASS", "")
    EMAIL_CATEDRA = st.secrets.get("EMAIL_CATEDRA", st.secrets.get("TEACHER_BCC", "investigacion@uccuyo.edu.ar"))

    def enviar_por_sendgrid(to_email: str, subject: str, body: str):
        message = Mail(from_email=SENDER_EMAIL_SG, to_emails=to_email, subject=subject, plain_text_content=body)
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        sg.send(message)

    def enviar_por_smtp(to_email: str, subject: str, body: str):
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = EMAIL_USER
        msg["To"] = to_email
        msg.set_content(body)
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx) as server:
            server.login(EMAIL_USER, EMAIL_PASS)
            server.send_message(msg)

    subject = f"Resultado — {practico} · {alumno_nombre}"

    try:
        if SENDGRID_API_KEY and SENDER_EMAIL_SG:
            # Alumno
            enviar_por_sendgrid(alumno_email, subject, mensaje_preview)
            # Cátedra (incluye correo del alumno)
            mensaje_catedra = f"Correo del alumno: {alumno_email}\n\n{mensaje_preview}"
            enviar_por_sendgrid(EMAIL_CATEDRA, subject, mensaje_catedra)
        elif EMAIL_USER and EMAIL_PASS:
            enviar_por_smtp(alumno_email, subject, mensaje_preview)
            mensaje_catedra = f"Correo del alumno: {alumno_email}\n\n{mensaje_preview}"
            enviar_por_smtp(EMAIL_CATEDRA, subject, mensaje_catedra)
        else:
            st.warning("⚠️ Falta configuración de correo (SendGrid o EMAIL_USER/EMAIL_PASS). Descargá el TXT.")
    except Exception as e:
        st.warning(f"No se pudo enviar el correo: {e}")

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
