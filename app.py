import io
import re
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

# Prácticos disponibles (podés editar la lista si querés)
PRACTICOS = [
    "Práctico N° 1 — IA en la escritura del proyecto",
    "Práctico N° 2 — Marco teórico y antecedentes",
    "Práctico N° 3 — Diseño metodológico",
]

# Criterios de ejemplo (como en tu app: Tema/Título, Paradigma, Pregunta, Objetivos, Hipótesis)
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
practico      = st.selectbox("Práctico", PRACTICOS)
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
    # Configurá estos secretos en Streamlit Cloud > Settings > Secrets
    SMTP_HOST    = st.secrets.get("SMTP_HOST", "")
    SMTP_PORT    = int(st.secrets.get("SMTP_PORT", 465))
    SMTP_USER    = st.secrets.get("SMTP_USER", "")
    SMTP_PASS    = st.secrets.get("SMTP_PASS", "")
    SENDER_EMAIL = st.secrets.get("SENDER_EMAIL", "")
    EMAIL_CATEDRA = st.secrets.get("EMAIL_CATEDRA", SENDER_EMAIL)

    if not all([SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SENDER_EMAIL]):
        st.warning("⚠️ Falta configurar credenciales SMTP en **st.secrets**. Abajo podés descargar el mensaje en TXT.")
    else:
        def enviar(destinatario: str):
            subject = f"Resultado — {practico} · {alumno_nombre}"  # ← nombre en asunto
            msg = EmailMessage()
            msg["Subject"] = subject
            msg["From"] = SENDER_EMAIL
            msg["To"] = destinatario
            msg.set_content(mensaje_preview)  # ← nombre en cuerpo

            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx) as server:
                server.login(SMTP_USER, SMTP_PASS)
                server.send_message(msg)

        try:
            enviar(alumno_email)       # al alumno
            if EMAIL_CATEDRA:
                enviar(EMAIL_CATEDRA)  # a la cátedra (tu casilla)
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
