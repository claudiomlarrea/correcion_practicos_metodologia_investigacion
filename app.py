import streamlit as st
import io, re, smtplib, ssl
from email.message import EmailMessage
from pathlib import Path
from docx import Document
from pdfminer.high_level import extract_text
from email_validator import validate_email, EmailNotValidError

# ---- Configuración inicial ----
st.set_page_config(page_title="Auto-corrección | Metodología", layout="centered")
RUBRIC_MAX = {1: 100, 2: 100, 3: 100, 4: 100, 5: 100, 6: 100}

# ---- Funciones de parsing ----
def read_docx(file_bytes: bytes) -> dict:
    bio = io.BytesIO(file_bytes)
    doc = Document(bio)
    paragraphs, texts = [], []
    for p in doc.paragraphs:
        txt = p.text.strip()
        style = getattr(p.style, "name", "")
        if txt:
            paragraphs.append((txt, style))
            texts.append(txt)
    return {"plain_text": "\n".join(texts), "paragraphs": paragraphs}

def read_pdf(file_bytes: bytes) -> dict:
    bio = io.BytesIO(file_bytes)
    text = extract_text(bio) or ""
    return {"plain_text": text, "paragraphs": [(line, "") for line in text.splitlines() if line.strip()]}

def parse_file(uploaded) -> dict:
    suffix = Path(uploaded.name).suffix.lower()
    file_bytes = uploaded.read()
    if suffix == ".docx":
        return read_docx(file_bytes)
    elif suffix == ".pdf":
        return read_pdf(file_bytes)
    else:
        st.error("Formato no soportado. Suba un archivo .docx o .pdf")
        return {"plain_text": "", "paragraphs": []}

# ---- Evaluación por práctico ----
def evaluar_practico(num, text, paragraphs):
    score, feedback = 0, []

    if num == 1:
        for keyword in ["tema", "título", "paradigma", "pregunta", "objetivo", "hipótesis"]:
            if re.search(keyword, text.lower()):
                score += 15
        feedback.append("Se verificaron elementos clave del proyecto.")

    elif num == 2:
        if "variable" in text.lower(): score += 30
        if "instrumento" in text.lower(): score += 20
        if "ética" in text.lower(): score += 20
        feedback.append("Se analizaron variables, instrumentos y ética.")

    elif num == 3:
        for keyword in ["muestreo", "instrumento", "validez", "muestra"]:
            if keyword in text.lower(): score += 25
        feedback.append("Se revisó muestreo, instrumentos y tamaño muestral.")

    elif num == 4:
        palabras = len(text.split())
        if 900 <= palabras <= 1100: score += 40
        refs = len(re.findall(r"\(\w+\,\s?\d{4}\)", text))
        if refs >= 3: score += 30
        feedback.append("Revisión de extensión y referencias.")

    elif num == 5:
        if "bibliografía" in text.lower(): score += 40
        if "mendeley" in text.lower() or len(re.findall(r"\(\w+\,\s?\d{4}\)", text)) >= 5:
            score += 40
        feedback.append("Se verificaron citas y referencias con Mendeley.")

    elif num == 6:
        estilos = [s for (_, s) in paragraphs if "Heading" in s]
        if len(estilos) >= 3: score += 50
        if "contenido" in text.lower() or "índice" in text.lower():
            score += 40
        feedback.append("Se detectaron títulos jerarquizados e índice.")

    return min(score, RUBRIC_MAX[num]), "; ".join(feedback)

# ---- Envío de correo ----
def enviar_email(destinatario, asunto, mensaje):
    try:
        remitente = st.secrets["EMAIL_USER"]
        password = st.secrets["EMAIL_PASS"]
        smtp_server = "smtp.gmail.com"
        port = 465

        em = EmailMessage()
        em["From"] = remitente
        em["To"] = destinatario
        em["Subject"] = asunto
        em.set_content(mensaje)

        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(smtp_server, port, context=context) as server:
            server.login(remitente, password)
            server.send_message(em)
        return True
    except Exception as e:
        st.error(f"Error enviando correo: {e}")
        return False

# ---- Interfaz Streamlit ----
st.title("📑 Auto-corrección de Prácticos")
st.write("Suba su archivo, elija el práctico y escriba su correo electrónico.")

correo = st.text_input("Correo electrónico del alumno")
practico = st.selectbox("Número de práctico", list(RUBRIC_MAX.keys()))
uploaded = st.file_uploader("Subir archivo (.docx o .pdf)", type=["docx", "pdf"])

if st.button("Corregir y Enviar"):
    if not uploaded or not correo:
        st.warning("Debe subir un archivo y un correo válido.")
    else:
        try:
            validate_email(correo)
            parsed = parse_file(uploaded)
            text, paragraphs = parsed["plain_text"], parsed["paragraphs"]

            score, feedback = evaluar_practico(practico, text, paragraphs)

            mensaje = (
                f"Resultado de la corrección automática:\n\n"
                f"Práctico Nº {practico}\n"
                f"Puntaje: {score}/{RUBRIC_MAX[practico]}\n"
                f"Comentarios: {feedback}\n"
            )

            enviado = enviar_email(correo, f"Resultado Práctico {practico}", mensaje)
            if enviado:
                st.success("✅ Corregido y enviado al correo del alumno.")
                st.text_area("Mensaje enviado:", mensaje, height=200)
        except EmailNotValidError:
            st.error("Correo electrónico inválido.")

