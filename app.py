import streamlit as st
import io, re, smtplib, ssl
from email.message import EmailMessage
from pathlib import Path
from docx import Document
from pdfminer.high_level import extract_text
from email_validator import validate_email, EmailNotValidError

# -----------------------------
# Configuración inicial
# -----------------------------
st.set_page_config(page_title="Auto-corrección | Metodología", layout="centered")
RUBRIC_MAX = {1: 100, 2: 100, 3: 100, 4: 100, 5: 100, 6: 100}

# -----------------------------
# Lectura de archivos
# -----------------------------
def read_docx(file_bytes: bytes) -> dict:
    """Devuelve {'plain_text': str, 'paragraphs': [(text, style_name), ...], 'filetype': 'docx'}"""
    bio = io.BytesIO(file_bytes)
    doc = Document(bio)
    paragraphs, texts = [], []
    for p in doc.paragraphs:
        txt = (p.text or "").strip()
        style = getattr(p.style, "name", "") or ""
        if txt:
            paragraphs.append((txt, style))
            texts.append(txt)
    return {"plain_text": "\n".join(texts), "paragraphs": paragraphs, "filetype": "docx"}

def read_pdf(file_bytes: bytes) -> dict:
    """Devuelve {'plain_text': str, 'paragraphs': [(line, ''), ...], 'filetype': 'pdf'}"""
    bio = io.BytesIO(file_bytes)
    text = extract_text(bio) or ""
    return {
        "plain_text": text,
        "paragraphs": [(line.strip(), "") for line in text.splitlines() if line.strip()],
        "filetype": "pdf",
    }

def parse_file(uploaded) -> dict:
    suffix = Path(uploaded.name).suffix.lower()
    file_bytes = uploaded.read()
    if suffix == ".docx":
        return read_docx(file_bytes)
    elif suffix == ".pdf":
        return read_pdf(file_bytes)
    else:
        st.error("Formato no soportado. Suba un archivo .docx o .pdf")
        return {"plain_text": "", "paragraphs": [], "filetype": "unknown"}

# -----------------------------
# Utilidades de evaluación
# -----------------------------
def count_in_text(patterns, text_lower):
    return sum(1 for p in patterns if p in text_lower)

def apa_inline_citations(text):
    """Cuenta citas tipo (Apellido, 2020) aproximadamente."""
    return len(re.findall(r"\([A-Za-zÁÉÍÓÚÜÑáéíóúüñ\-]+,\s?(19|20)\d{2}\)", text))

def has_bibliography_section(text_lower):
    keys = ["bibliografía", "referencias", "referencias bibliográficas"]
    return any(k in text_lower for k in keys)

def word_count_between(text, min_w, max_w):
    n = len(re.findall(r"\w+", text))
    return n, (min_w <= n <= max_w)

def find_headings_docx(paragraphs):
    h1 = sum(1 for _, s in paragraphs if "Heading 1" in s or "Título 1" in s)
    h2 = sum(1 for _, s in paragraphs if "Heading 2" in s or "Título 2" in s)
    h3 = sum(1 for _, s in paragraphs if "Heading 3" in s or "Título 3" in s)
    return h1, h2, h3

def has_toc(text_lower, paragraphs, filetype):
    if "tabla de contenido" in text_lower or "contenido" in text_lower or "índice" in text_lower:
        return True
    if filetype == "docx":
        if any("Table of Contents" in p[0] or "Contents" in p[0] for p in paragraphs):
            return True
    return False

def build_feedback_message(num, score, breakdown, summary):
    lines = []
    lines.append("Resultado de la corrección automática:\n")
    lines.append(f"Práctico Nº {num}")
    lines.append(f"Puntaje: {score}/{RUBRIC_MAX[num]}\n")
    lines.append("Desglose por criterios:")
    for name, got, mx, expl in breakdown:
        lines.append(f" - {name}: {got}/{mx}. {expl}")
    lines.append("\nComentarios generales:")
    lines.append(summary if summary else "—")
    return "\n".join(lines)

# -----------------------------
# Rúbricas por práctico
# Devuelven: score:int, breakdown:list[(criterio, pts, max, explicación)], summary:str
# -----------------------------
def corregir_practico_1(text, paragraphs, filetype):
    """
    TP1: IA en la escritura del proyecto.
    Criterios:
     - Tema y Título (20)
     - Paradigma (15)
     - Pregunta de investigación (20)
     - Objetivo general y específicos (30)
     - Hipótesis (si corresponde) (15)
    """
    t = text.lower()
    total = 0
    bd = []

    # Tema y Título
    pts = 0
    found = count_in_text(["tema", "título"], t)
    if found >= 2:
        pts = 20; expl = "Se identificaron 'Tema' y 'Título' en el documento."
    elif found == 1:
        pts = 10; expl = "Solo se encontró uno de los apartados ('Tema' o 'Título')."
    else:
        expl = "No se detectaron secciones claras de 'Tema' y 'Título'."
    total += pts; bd.append(("Tema y Título", pts, 20, expl))

    # Paradigma
    pts = 15 if "paradigma" in t else 0
    expl = "Incluye el paradigma de investigación." if pts else "No se encontró el apartado de paradigma."
    total += pts; bd.append(("Paradigma", pts, 15, expl))

    # Pregunta
    pts = 20 if ("pregunta de investigación" in t or re.search(r"pregunta(s)?\s+de\s+investigación", t)) else 0
    expl = "Incluye pregunta de investigación." if pts else "No se detectó una pregunta de investigación explícita."
    total += pts; bd.append(("Pregunta de investigación", pts, 20, expl))

    # Objetivos
    has_general = "objetivo general" in t or "objetivo principal" in t
    has_especificos = "objetivos específicos" in t or "objetivos especificos" in t
    if has_general and has_especificos:
        pts = 30; expl = "Incluye objetivo general/principal y objetivos específicos."
    elif has_general or has_especificos:
        pts = 15; expl = "Solo se encontró uno (general/principal o específicos)."
    else:
        pts = 0; expl = "No se detectaron objetivos claros."
    total += pts; bd.append(("Objetivos", pts, 30, expl))

    # Hipótesis
    pts = 15 if ("hipótesis" in t or "hipotesis" in t) else 10
    expl = "Incluye hipótesis de investigación." if pts == 15 else "No se encontró hipótesis explícita; se otorgan 10 pts si el diseño no la requiere."
    total += pts; bd.append(("Hipótesis (si corresponde)", pts, 15, expl))

    summary = "Se evaluó la presencia de secciones fundamentales de un anteproyecto. Revise que cada apartado esté titulado claramente."
    return total, bd, summary

def corregir_practico_2(text, paragraphs, filetype):
    """
    TP2: Operacionalización de variables y métodos de análisis.
    Criterios:
     - Cuadro de operacionalización completo (45)
     - Métodos de análisis alineados a objetivos (25)
     - Validación cuantitativa/cualitativa (20)
     - Ética en recolección de datos (10)
    """
    t = text.lower()
    total = 0
    bd = []

    keys = ["variable", "independiente", "dependiente", "definición conceptual", "definicion conceptual",
            "definición operacional", "definicion operacional", "indicador", "escala", "instrumento",
            "unidad de análisis", "unidades de análisis"]
    found = count_in_text(keys, t)
    if found >= 7:
        pts = 45; expl = "Se identifican elementos centrales del cuadro de operacionalización."
    elif found >= 4:
        pts = 30; expl = "El cuadro está parcialmente completo; faltan campos."
    else:
        pts = 10; expl = "No se reconoce un cuadro completo de operacionalización."
    total += pts; bd.append(("Cuadro de operacionalización", pts, 45, expl))

    methods_keys = ["análisis", "regresión", "correlación", "anova", "t-student", "chi-cuadrado",
                    "temático", "codificación", "grounded theory", "análisis de contenido", "estadístico", "cualitativo"]
    found = count_in_text(methods_keys, t)
    if found >= 3:
        pts = 25; expl = "Se describen métodos de análisis y su pertinencia."
    elif found >= 1:
        pts = 15; expl = "Se mencionan métodos pero con detalle limitado."
    else:
        pts = 5; expl = "No se especifican métodos de análisis."
    total += pts; bd.append(("Métodos de análisis", pts, 25, expl))

    val_keys = ["validez", "fiabilidad", "confiabilidad", "triangulación", "alfa de cronbach", "pilotaje", "validación de instrumentos"]
    found = count_in_text(val_keys, t)
    if found >= 2:
        pts = 20; expl = "Se proponen estrategias de validación para datos cuantitativos/cualitativos."
    elif found == 1:
        pts = 10; expl = "Se menciona validación pero de forma breve."
    else:
        pts = 0; expl = "No se especifica cómo se validarán los datos/instrumentos."
    total += pts; bd.append(("Validación de datos/instrumentos", pts, 20, expl))

    pts = 10 if any(k in t for k in ["ética", "consentimiento informado", "anonimato", "confidencialidad"]) else 0
    expl = "Incluye consideraciones éticas (consentimiento, confidencialidad o similares)." if pts else "No se describen consideraciones éticas."
    total += pts; bd.append(("Ética", pts, 10, expl))

    summary = "Se verificó la completitud del cuadro de variables, la pertinencia de los métodos, la validación y la ética."
    return total, bd, summary

def corregir_practico_3(text, paragraphs, filetype):
    """
    TP3: Muestreo, recolección de datos y tamaño muestral.
    Criterios:
     - Tipo de muestreo y justificación (30)
     - Instrumentos y su adecuación (25)
     - Validez/fiabilidad de instrumentos (20)
     - Tamaño de muestra con fundamento (25)
    """
    t = text.lower()
    total = 0
    bd = []

    ms_keys = ["muestreo", "probabilístico", "no probabilístico", "aleatorio", "estratificado", "intencionado", "conglomerados", "bola de nieve", "sistemático"]
    found = count_in_text(ms_keys, t)
    if found >= 2 and ("fundament" in t or "justific" in t):
        pts = 30; expl = "Describe el tipo de muestreo y fundamenta la elección."
    elif found >= 1:
        pts = 20; expl = "Menciona el tipo de muestreo pero con poca justificación."
    else:
        pts = 10; expl = "No se identifica con claridad el tipo de muestreo."
    total += pts; bd.append(("Tipo de muestreo y justificación", pts, 30, expl))

    inst_keys = ["cuestionario", "encuesta", "entrevista", "guía", "observación", "escala", "test"]
    found = count_in_text(inst_keys, t)
    if found >= 2:
        pts = 25; expl = "Selecciona instrumentos y explica su adecuación."
    elif found == 1:
        pts = 15; expl = "Menciona un instrumento sin suficiente justificación."
    else:
        pts = 5; expl = "No se definen instrumentos de recolección."
    total += pts; bd.append(("Instrumentos y adecuación", pts, 25, expl))

    val_keys = ["validez", "fiabilidad", "confiabilidad", "pilotaje", "alfa de cronbach"]
    found = count_in_text(val_keys, t)
    if found >= 2:
        pts = 20; expl = "Incluye procedimientos para validez/fiabilidad."
    elif found == 1:
        pts = 10; expl = "Menciona brevemente validez/fiabilidad."
    else:
        pts = 0; expl = "No se aborda validez/fiabilidad de instrumentos."
    total += pts; bd.append(("Validez/fiabilidad de instrumentos", pts, 20, expl))

    tm_keys = ["tamaño de la muestra", "n=", "muestra de", "cálculo muestral", "error", "confianza"]
    found = count_in_text(tm_keys, t)
    if found >= 2:
        pts = 25; expl = "Estima tamaño de muestra y ofrece fundamentos (error/confianza/supuestos)."
    elif found == 1:
        pts = 15; expl = "Menciona el tamaño de la muestra sin fundamento claro."
    else:
        pts = 5; expl = "No se calcula ni fundamenta el tamaño muestral."
    total += pts; bd.append(("Tamaño de la muestra", pts, 25, expl))

    summary = "Se revisaron decisiones de muestreo, selección de instrumentos, validez y tamaño muestral."
    return total, bd, summary

def corregir_practico_4(text, paragraphs, filetype):
    """
    TP4: Introducción (500 palabras) + Marco teórico (500) + 3 referencias mínimas.
    Criterios:
     - Extensión Introducción ~500±10% (20)
     - Extensión Marco teórico ~500±10% (20)
     - 3+ citas en el texto (30)
     - Mención de uso de IA (15)
     - Sección de referencias/bibliografía (15)
    """
    t = text.lower()
    total = 0
    bd = []

    intro_idx = t.find("introducción")
    marco_idx = t.find("marco teórico")
    total_words = len(re.findall(r"\w+", text))
    intro_words = marco_words = None

    if intro_idx != -1 and marco_idx != -1 and marco_idx > intro_idx:
        intro_text = text[intro_idx: marco_idx]
        marco_text = text[marco_idx:]
        intro_words = len(re.findall(r"\w+", intro_text))
        marco_words = len(re.findall(r"\w+", marco_text))

    # Introducción
    if intro_words is not None:
        ok = 450 <= intro_words <= 550
        pts = 20 if ok else 10
        expl = f"Introducción con {intro_words} palabras (objetivo ~500)."
    else:
        ok = 900 <= total_words <= 1100
        pts = 10 if ok else 0
        expl = "No se detectó título 'Introducción'; se evaluó por extensión global."
    total += pts; bd.append(("Extensión Introducción", pts, 20, expl))

    # Marco teórico
    if marco_words is not None:
        ok = 450 <= marco_words <= 550
        pts = 20 if ok else 10
        expl = f"Marco teórico con {marco_words} palabras (objetivo ~500)."
    else:
        ok = 900 <= total_words <= 1100
        pts = 10 if ok else 0
        expl = "No se detectó título 'Marco teórico'; se evaluó por extensión global."
    total += pts; bd.append(("Extensión Marco teórico", pts, 20, expl))

    # Citas en el texto
    citas = apa_inline_citations(text)
    if citas >= 3:
        pts = 30; expl = f"Se detectaron {citas} citas en el texto (mínimo 3)."
    elif citas == 2:
        pts = 20; expl = "Solo se detectaron 2 citas en el texto."
    elif citas == 1:
        pts = 10; expl = "Solo se detectó 1 cita en el texto."
    else:
        pts = 0; expl = "No se detectaron citas en el texto con formato (Apellido, Año)."
    total += pts; bd.append(("Citas en el texto", pts, 30, expl))

    # Uso de IA
    pts = 15 if any(k in t for k in ["inteligencia artificial", "chatgpt", "herramienta de ia", "ia"]) else 5
    expl = "Se menciona el uso de IA para mejorar la redacción." if pts == 15 else "No se menciona explícitamente el apoyo de IA."
    total += pts; bd.append(("Uso de IA (mención)", pts, 15, expl))

    # Bibliografía
    pts = 15 if has_bibliography_section(t) else 0
    expl = "Incluye sección de referencias/bibliografía." if pts else "No se detectó sección de referencias/bibliografía."
    total += pts; bd.append(("Referencias/Bibliografía", pts, 15, expl))

    summary = "Se evaluó extensión por secciones, citas mínimas, mención de IA y presencia de bibliografía."
    return total, bd, summary

def corregir_practico_5(text, paragraphs, filetype):
    """
    TP5: Biblioteca mínima (5 refs) + citas en Word (Mendeley) + bibliografía final.
    Criterios:
     - 5+ citas en el texto (35)
     - Bibliografía generada (30)
     - Consistencia de formato (20)
     - Organización/metadatos (mención) (15)
    """
    t = text.lower()
    total = 0
    bd = []

    citas = apa_inline_citations(text)
    if citas >= 5:
        pts = 35; expl = f"Se detectaron {citas} citas en el texto (mínimo 5)."
    elif citas >= 3:
        pts = 20; expl = f"Solo {citas} citas detectadas; se requieren 5."
    elif citas >= 1:
        pts = 10; expl = "Muy pocas citas detectadas."
    else:
        pts = 0; expl = "No se detectaron citas en el texto."
    total += pts; bd.append(("Citas en el texto", pts, 35, expl))

    pts = 30 if has_bibliography_section(t) else 10
    expl = "Incluye bibliografía generada." if pts == 30 else "No se detecta sección de bibliografía clara."
    total += pts; bd.append(("Bibliografía final", pts, 30, expl))

    has_year = len(re.findall(r"(19|20)\d{2}", text)) >= 5
    has_doi_or_url = "doi" in t or "http" in t
    if has_year and (has_doi_or_url or "vol." in t or "pp." in t or "nº" in t or "no." in t):
        pts = 20; expl = "Las referencias muestran metadatos y formato consistente."
    else:
        pts = 10; expl = "Formato de referencias poco consistente o incompleto."
    total += pts; bd.append(("Consistencia de formato", pts, 20, expl))

    pts = 15 if any(k in t for k in ["mendeley", "carpeta", "grupo", "metadatos", "corrigiendo metadatos"]) else 5
    expl = "Se evidencia organización/corrección de metadatos o uso de Mendeley." if pts == 15 else "No se menciona organización/corrección de metadatos."
    total += pts; bd.append(("Organización/metadatos", pts, 15, expl))

    summary = "Se verificaron citas mínimas, bibliografía final y consistencia general de referencias."
    return total, bd, summary

def corregir_practico_6(text, paragraphs, filetype):
    """
    TP6: Títulos y subtítulos jerarquizados + índice automático.
    Criterios:
     - Títulos jerarquizados (H1/H2/H3) (50)
     - Tabla de contenido (40)
     - Actualización del índice (mención) (10)
    """
    t = text.lower()
    total = 0
    bd = []

    if filetype == "docx":
        h1, h2, h3 = find_headings_docx(paragraphs)
        if h1 >= 1 and h2 >= 1 and h3 >= 1:
            pts = 50; expl = f"Se detectan títulos jerárquicos: H1={h1}, H2={h2}, H3={h3}."
        elif (h1 >= 1 and h2 >= 1) or (h1 >= 1 and h3 >= 1):
            pts = 35; expl = f"Se detectan algunos niveles (H1={h1}, H2={h2}, H3={h3}); falta un nivel."
        else:
            pts = 15; expl = f"Escasa jerarquía de títulos (H1={h1}, H2={h2}, H3={h3})."
    else:
        caps = len(re.findall(r"\n[A-ZÁÉÍÓÚÑ ]{6,}\n", "\n"+text+"\n"))
        pts = 35 if caps >= 3 else (20 if caps >= 1 else 10)
        expl = "Detección aproximada de jerarquías en PDF; se recomienda subir .docx."
    total += pts; bd.append(("Títulos jerarquizados", pts, 50, expl))

    toc = has_toc(t, paragraphs, filetype)
    if toc:
        pts = 40; expl = "Se detecta tabla de contenido/índice."
    else:
        pts = 15; expl = "No se detecta índice automático."
    total += pts; bd.append(("Tabla de contenido", pts, 40, expl))

    pts = 10 if any(k in t for k in ["actualizar índice", "actualizar el índice", "update table of contents"]) else 5
    expl = "Se menciona la actualización del índice al modificar títulos." if pts == 10 else "No se menciona la actualización del índice."
    total += pts; bd.append(("Actualización del índice (mención)", pts, 10, expl))

    summary = "Se evaluó la estructura por niveles y la presencia de índice automático."
    return total, bd, summary

# -----------------------------
# Router de evaluación
# -----------------------------
def evaluar_practico(num, text, paragraphs, filetype):
    if num == 1:
        return corregir_practico_1(text, paragraphs, filetype)
    if num == 2:
        return corregir_practico_2(text, paragraphs, filetype)
    if num == 3:
        return corregir_practico_3(text, paragraphs, filetype)
    if num == 4:
        return corregir_practico_4(text, paragraphs, filetype)
    if num == 5:
        return corregir_practico_5(text, paragraphs, filetype)
    if num == 6:
        return corregir_practico_6(text, paragraphs, filetype)
    return 0, [], "—"

# -----------------------------
# Envío de correo (SMTP Gmail)
# -----------------------------
def enviar_email(destinatario, asunto, mensaje):
    try:
        remitente = st.secrets["EMAIL_USER"]
        password = st.secrets["EMAIL_PASS"]
        smtp_server = "smtp.gmail.com"
        port = 465

        em = EmailMessage()
        em["From"] = remitente
        em["To"] = destinatario

        # Copia oculta al docente (opcional)
        bcc = st.secrets.get("TEACHER_BCC")
        if bcc:
            em["Bcc"] = bcc

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

# -----------------------------
# Interfaz Streamlit
# -----------------------------
st.title("📑 Auto-corrección de Prácticos")
st.write("Suba su archivo, elija el práctico y escriba el correo electrónico del alumno. Recibirá puntaje y explicaciones por criterio.")

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
            text, paragraphs, filetype = parsed["plain_text"], parsed["paragraphs"], parsed["filetype"]

            score, breakdown, summary = evaluar_practico(practico, text, paragraphs, filetype)
            mensaje = build_feedback_message(practico, score, breakdown, summary)

            enviado = enviar_email(correo, f"Resultado Práctico {practico}", mensaje)
            if enviado:
                st.success("✅ Corregido y enviado al correo del alumno.")
                st.text_area("Mensaje enviado:", mensaje, height=280)
        except EmailNotValidError:
            st.error("Correo electrónico inválido.")
