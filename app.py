import streamlit as st
import random, string, smtplib, io, base64, httpx, uuid
from datetime import datetime
from azure.data.tables import TableServiceClient
from openai import AzureOpenAI
from azure.ai.formrecognizer import DocumentAnalysisClient
from azure.core.credentials import AzureKeyCredential
from PyPDF2 import PdfReader, PdfWriter
from reportlab.platypus import Paragraph, Frame
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4


def get_certificate_template():
    cert_tpl = '''
This is to certify that Mr./Ms. [Student Name], son/daughter of Mr./Mrs. [Parent's Name], is a bonafide student of Rajalakshmi Engineering College, Chennai, enrolled in the [Department Name] for the [Course Name] program during the academic year [Start Year] to [End Year].
He/She has completed/ is currently pursuing his/her studies in the [Year/Semester] of the course.
This certificate is issued to him/her on request for the purpose of [Purpose, e.g., Higher Studies, Bank Loan, Passport, etc.].
'''
    return cert_tpl


def college_branding():
    st.markdown("""
    <div style="text-align:center;">
      <img src="https://rajalakshmi.org/_next/image?url=%2Flogo.svg&w=384&q=75" style="width:180px; margin-bottom:0.8em;" />
      <h1 style="font-size:2.7em;color:#6f2ca3;">Rajalakshmi Engineering College</h1>
      <p style="font-size:1.20em;color:#222;">Bonafide Certificate Request Portal</p>
    </div>
    <hr style="margin-bottom:2em;">
    """, unsafe_allow_html=True)


def create_text_overlay(text, x=45, y=660, width=520, height=180, font_size=14, line_spacing=5):
    packet = io.BytesIO()
    can = canvas.Canvas(packet, pagesize=A4)
    style = ParagraphStyle('custom', fontName='Helvetica', fontSize=font_size, leading=font_size+line_spacing, alignment=4)
    para = Paragraph(text, style)
    frame = Frame(x, y - height, width, height, showBoundary=0)
    frame.addFromList([para], can)
    can.save()
    packet.seek(0)
    return packet


def pdf_viewer(pdf_bytes, height=650):
    b64 = base64.b64encode(pdf_bytes).decode()
    iframe = f'<iframe src="data:application/pdf;base64,{b64}" width="100%" height="{height}px" frameborder="0"></iframe>'
    st.markdown(iframe, unsafe_allow_html=True)


# Configuration: Replace with your actual keys and endpoints
connection_string = "DefaultEndpointsProtocol=https;AccountName=smartcertifydb;AccountKey=3XbtwZAXbadP5uPgSPRaeVD0VcNDP02igNyF1+vbwjJuApwec6B2XTcZCtSBeRPoaKnM+L/ewm7e+AStFLG9dA==;EndpointSuffix=core.windows.net"
user_table_name = "StudentLogin"
bonafide_table_name = "BonafideRequests"
ADMIN_EMAIL = "admin@rec.edu.in"
ADMIN_PASSWORD = "rec@admin"
certificate_template = get_certificate_template()

ai_endpoint = "https://skee-me7e071s-eastus2.cognitiveservices.azure.com/"
ai_api_key = "3QJaFSbooorxbNBFQvoYYcIlPOp6yZ5SCCo4cXLORLZ8wytnyyHUJQQJ99BHACHYHv6XJ3w3AAAAACOGxzlk"
deployment_name = "smartcertify-gpt4"
ai_api_version = "2025-01-01-preview"

doc_endpoint = "https://docverifier.cognitiveservices.azure.com/"
doc_api_key = "5MyHBkcOQPixoYPdry1lOdGTRJVnBMUFRHxxcrqynU5I1BzH55ISJQQJ99BJACGhslBXJ3w3AAALACOGvOv0"


# Initialize Azure clients
service = TableServiceClient.from_connection_string(conn_str=connection_string)
user_table_client = service.create_table_if_not_exists(table_name=user_table_name)
bonafide_table_client = service.create_table_if_not_exists(table_name=bonafide_table_name)
client = AzureOpenAI(api_version=ai_api_version, azure_endpoint=ai_endpoint, api_key=ai_api_key, timeout=httpx.Timeout(30.0))
doc_client = DocumentAnalysisClient(endpoint=doc_endpoint, credential=AzureKeyCredential(doc_api_key))


def check_student_login(email, password):
    entities = user_table_client.query_entities(f"PartitionKey eq '{email}'")
    for entity in entities:
        if entity.get("Password") == password:
            return True
    return False


def store_bonafide_request(email, entries, letter, doc_status):
    row_key = str(uuid.uuid4())
    entity = {
        "PartitionKey": email,
        "RowKey": row_key,
        "StudentName": entries["Student Name"],
        "RegNo": entries["Reg No"],
        "Purpose": entries["Purpose"],
        "GeneratedLetter": letter,
        "DocumentVerification": doc_status,
        "AdminApproval": "Pending",
        "RequestDate": datetime.utcnow().isoformat()
    }
    bonafide_table_client.create_entity(entity=entity)


def update_bonafide_status(rowkey, status):
    entity = next(e for e in bonafide_table_client.list_entities() if e["RowKey"] == rowkey)
    entity["AdminApproval"] = status
    bonafide_table_client.update_entity(entity)


def extract_text(uploaded_file):
    poller = doc_client.begin_analyze_document("prebuilt-document", document=uploaded_file)
    result = poller.result()
    text = " ".join(line.content for page in result.pages for line in page.lines)
    return text


def verify_fields(extracted_text, expected_name, expected_regno):
    name_ok = expected_name.lower() in extracted_text.lower()
    regno_ok = expected_regno.lower() in extracted_text.lower()
    col_ok = "rajalakshmi engineering college" in extracted_text.lower()
    return name_ok, regno_ok, col_ok


def login():
    college_branding()
    with st.form("login_form"):
        role = st.radio("🔑 Select your role", ["Student", "Admin"], horizontal=True)
        email = st.text_input("College Email", placeholder="e.g. 220701001@rajalakshmi.edu.in")
        password = st.text_input("Password", type="password")
        forgot_pw = st.checkbox("Forgot Password?", key="forgot_pw")
        login_clicked = st.form_submit_button("Login", use_container_width=True)
        if login_clicked and not forgot_pw:
            if role == "Admin":
                if email == ADMIN_EMAIL and password == ADMIN_PASSWORD:
                    st.session_state["role"] = "admin"
                    st.session_state["user"] = email
                    st.session_state["logged_in"] = True
                    st.success("Admin login successful!")
                else:
                    st.error("Invalid admin credentials.")
            else:
                if check_student_login(email, password):
                    st.session_state["role"] = "student"
                    st.session_state["user"] = email
                    st.session_state["logged_in"] = True
                    st.success("Student login successful!")
                else:
                    st.error("Invalid student credentials.")


def student_dashboard_page():
    college_branding()
    st.markdown("""
    <style>
    .cert-header {font-size: 2em;font-weight: 780;color: #22397d; margin-bottom: 6px;margin-top: 10px;letter-spacing: 1px;}
    .cert-desc {color: #333;font-size: 1.07em;padding-bottom: 16px;margin-top: 0.2em;}
    .section-title {color: #22397d;font-size: 1.25em;font-weight: 700;margin-top: 20px;margin-bottom: 8px;letter-spacing: 0.5px;}
    .info-box {background: linear-gradient(135deg, #f6f9fd 80%, #eaf0ff 100%);border-radius: 14px;padding: 20px 22px 10px 22px; margin-bottom: 18px;box-shadow: 0 1px 8px rgba(34,57,125,0.09);}
    .neat-btn-row {display: flex;justify-content: center;gap: 55px;margin-top: 32px;}
    .neat-btn {background: #22397d;color: #fff;font-weight: 700;border: none;border-radius: 15px;padding: 22px 38px;font-size: 1.18em;box-shadow: 0 4px 15px rgba(34,57,125,0.12);cursor: pointer;transition: background 0.2s;min-width: 210px;text-align: center;outline:none;letter-spacing: 0.5px;line-height: 1.3em;}
    .neat-btn:hover {background: #384fa8;color: #f1eafb;}
    .dash-card {background:#f4f6fc; border-radius:13px;display:inline-block; box-shadow:0 2px 12px rgba(34,57,125,0.09); margin:14px 18px; min-width:180px; padding:20px 22px 15px 22px; text-align:center; color:#22397d; }
    .card-title {font-size:1.15em;font-weight:700;}
    .card-value {font-size:2.1em;font-weight:800; margin-top:3px;}
    </style>
    """, unsafe_allow_html=True)
    st.markdown('<div class="cert-header">Application for Bonafide Certificate</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Description</div>', unsafe_allow_html=True)
    st.markdown("""<div class="cert-desc">Bonafide certificate is a document provided by the institution confirming and testifying that you are a student enrolled at Rajalakshmi Engineering College. This certificate establishes your identity as a student for all legal and official purposes such as admission, scholarships, bank loans, passport applications, etc.</div>""", unsafe_allow_html=True)
    col_docs, col_how = st.columns(2)
    with col_docs:
        st.markdown('<div class="section-title">Supporting Documents</div>', unsafe_allow_html=True)
        st.markdown("""
        <div class="info-box">
        <ul style="font-size:1.07em;color:#333;">
            <li>College ID Proof</li>
            <li>Parent/Guardian ID Proof</li>
            <li>Relevant supporting document (for purpose)</li>
        </ul>
        </div>
        """, unsafe_allow_html=True)
    with col_how:
        st.markdown('<div class="section-title">How To Apply</div>', unsafe_allow_html=True)
        st.markdown("""
        <div class="info-box"><ul style="font-size:1.07em;color:#333;">
            <li>Fill out your details and submit the online application</li>
            <li>Upload your supporting document(s)</li>
            <li>Await admin approval and verification</li>
            <li>Download bonafide certificate when approved</li>
        </ul></div>
        """, unsafe_allow_html=True)

    requests = [e for e in bonafide_table_client.list_entities() if e["PartitionKey"] == st.session_state.get("user")]
    pending = len([r for r in requests if r["AdminApproval"] == "Pending"])
    approved = len([r for r in requests if r["AdminApproval"] == "Approved"])
    rejected = len([r for r in requests if r["AdminApproval"] == "Rejected"])

    st.markdown('<div style="text-align:center;">', unsafe_allow_html=True)
    st.markdown(f'<div class="dash-card"><div class="card-title">Pending Requests</div><div class="card-value">{pending}</div></div>', unsafe_allow_html=True)
    st.markdown(f'<div class="dash-card"><div class="card-title">Approved</div><div class="card-value">{approved}</div></div>', unsafe_allow_html=True)
    st.markdown(f'<div class="dash-card"><div class="card-title">Rejected</div><div class="card-value">{rejected}</div></div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="neat-btn-row">', unsafe_allow_html=True)
    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("Request Certificate", key="req_cert_btn"):
            st.session_state.student_page = "request_workflow"
    with col2:
        if st.button("Check Status", key="status_btn"):
            st.session_state.student_page = "status_page"
    st.markdown('</div>', unsafe_allow_html=True)


def admin_dashboard():
    college_branding()
    requests = [e for e in bonafide_table_client.list_entities()]
    pending = len([r for r in requests if r["AdminApproval"] == "Pending"])
    approved = len([r for r in requests if r["AdminApproval"] == "Approved"])
    rejected = len([r for r in requests if r["AdminApproval"] == "Rejected"])

    st.markdown("""
    <style>
    .dash-card {background:#f4f6fc; border-radius:13px;display:inline-block; box-shadow:0 2px 12px rgba(34,57,125,0.09); margin:14px 18px; min-width:190px; padding:20px 28px 15px 28px; text-align:center; color:#22397d; }
    .card-title {font-size:1.13em;font-weight:700;}
    .card-value {font-size:2em;font-weight:800; margin-top:3px;}
    </style>
    """, unsafe_allow_html=True)
    st.markdown('<div style="text-align:center;">', unsafe_allow_html=True)
    st.markdown(f'<div class="dash-card"><div class="card-title">Pending</div><div class="card-value">{pending}</div></div>', unsafe_allow_html=True)
    st.markdown(f'<div class="dash-card"><div class="card-title">Approved</div><div class="card-value">{approved}</div></div>', unsafe_allow_html=True)
    st.markdown(f'<div class="dash-card"><div class="card-title">Rejected</div><div class="card-value">{rejected}</div></div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

    st.header("Pending Bonafide Requests")
    for req in [r for r in requests if r["AdminApproval"] == "Pending"]:
        st.markdown(f"**Name:** {req.get('StudentName', '')}")
        st.markdown(f"**Roll No:** {req.get('RegNo', '')}")
        st.markdown(f"**Purpose:** {req.get('Purpose', '')}")
        if st.button(f"View Letter - {req['RowKey']}"):
            st.text_area("Request Letter Preview", req.get("GeneratedLetter", ""), height=250)
        accept_key = f"accept_{req['RowKey']}"
        if st.button("Accept", key=accept_key):
            update_bonafide_status(req["RowKey"], "Approved")
            st.session_state["approval_done"] = True
            st.success(f"Request approved for {req.get('StudentName', '')}")


def student_workflow(user_email):
    college_branding()
    if "step" not in st.session_state:
        st.session_state.step = 0
    if "approval_done" not in st.session_state:
        st.session_state.approval_done = False
    if st.session_state.step == 0:
        st.header("Request Bonafide Certificate")
        st.session_state.entries = {
            "Student Name": st.text_input("Student Name"),
            "Parent's Name": st.text_input("Parent's Name"),
            "Department Name": st.text_input("Department Name"),
            "Course Name": st.text_input("Course Name"),
            "Start Year": st.text_input("Start Year"),
            "End Year": st.text_input("End Year"),
            "Year/Semester": st.text_input("Year/Semester"),
            "Purpose": st.text_input("Purpose"),
            "Reg No": st.text_input("Reg No")
        }
        if st.button("Generate Letter"):
            if all(st.session_state.entries.values()):
                prompt = f"""Write a formal Bonafide Certificate request letter:\n{st.session_state.entries}"""
                response = client.chat.completions.create(
                    model=deployment_name,
                    messages=[
                        {"role": "system", "content": "You are a helpful assistant."},
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=512,
                    temperature=0.7,
                )
                st.session_state.letter_text = response.choices[0].message.content
                st.session_state.step = 1
            else:
                st.error("Please fill all fields.")
    elif st.session_state.step == 1:
        st.header("Edit Letter")
        st.session_state.letter_text = st.text_area("Letter", value=st.session_state.letter_text, height=250)
        if st.button("Preview Letter"):
            if st.session_state.letter_text.strip():
                st.session_state.step = 2
            else:
                st.error("Letter can't be empty")
    elif st.session_state.step == 2:
        st.header("Preview Letter")
        st.write(st.session_state.letter_text)
        if st.button("Next: Upload Document"):
            st.session_state.step = 3
    elif st.session_state.step == 3:
        st.header("Upload Supporting Document")
        doc = st.file_uploader("Upload Document (PDF, JPG, PNG)", type=["pdf", "jpg", "jpeg", "png"])
        doc_status = None
        if doc:
            with st.spinner("Verifying document..."):
                try:
                    text = extract_text(doc)
                    name_ok, regno_ok, college_ok = verify_fields(text, st.session_state.entries["Student Name"], st.session_state.entries["Reg No"])
                    if name_ok and regno_ok and college_ok:
                        doc_status = "Verified"
                        st.success("Verification successful")
                        if st.button("Submit for Admin Approval"):
                            store_bonafide_request(user_email, st.session_state.entries, st.session_state.letter_text, doc_status)
                            st.session_state.step = 4
                            st.success("Request submitted, waiting for admin approval.")
                    else:
                        doc_status = "Verification Failed"
                        st.error("Verification failed. Check document.")
                except Exception as e:
                    doc_status = "Verification Error"
                    st.error(f"Verification error: {e}")
    elif st.session_state.step == 4:
        st.header("Waiting for Admin Approval...")
        records = [e for e in bonafide_table_client.list_entities() if e["PartitionKey"] == user_email]
        if records:
            status = records[-1].get("AdminApproval", "Pending")
            if status == "Approved" or st.session_state.approval_done:
                st.session_state.step = 5
            else:
                st.info(f"Current status: {status}. Please refresh or check back later.")
        else:
            st.warning("No request found. Please submit request first.")
        if st.button("Check Status"):
            st.experimental_rerun()
    elif st.session_state.step == 5:
        st.header("Certificate Preview & Download")
        try:
            with open("template.pdf", "rb") as f:
                template_pdf_bytes = f.read()
            template_stream = io.BytesIO(template_pdf_bytes)
            template_pdf = PdfReader(template_stream)
            pairs = "\n".join(f"{k}: {v}" for k, v in st.session_state.entries.items())
            prompt = f"""Replace the brackets in the following certificate template with these values.
Template:
{certificate_template}
Field values:
{pairs}
Return ONLY the final certificate text formatted appropriately with all replacements."""
            with st.spinner("Generating certificate text..."):
                resp = client.chat.completions.create(
                    model=deployment_name,
                    messages=[
                        {"role": "system", "content": "You are a document automation assistant."},
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=500,
                    temperature=0,
                )
                cert_text = resp.choices[0].message.content
            packet = create_text_overlay(cert_text)
            overlay_pdf = PdfReader(packet)
            template_page = template_pdf.pages[0]
            template_page.merge_page(overlay_pdf.pages[0])
            writer = PdfWriter()
            writer.add_page(template_page)
            out_bytes = io.BytesIO()
            writer.write(out_bytes)
            out_bytes.seek(0)
            st.markdown('<span style="font-size:1.5em">👁 <b>Preview Certificate</b></span>', unsafe_allow_html=True)
            pdf_viewer(out_bytes.read())
            st.download_button("Download Certificate PDF", out_bytes.getvalue(), "bonafide_certificate.pdf", "application/pdf")
            st.text_area("Certificate Text", cert_text, height=300)
        except FileNotFoundError:
            st.error("Certificate template file template.pdf not found in the current folder.")


def main():
    if not st.session_state.get("logged_in", False):
        login()
    else:
        if st.session_state.get("role") == "student":
            if "student_page" not in st.session_state:
                st.session_state.student_page = "dashboard"
            if st.session_state.student_page == "dashboard":
                student_dashboard_page()
            elif st.session_state.student_page == "request_workflow":
                student_workflow(st.session_state.get("user"))
            elif st.session_state.student_page == "status_page":
                st.info("Status tracking page coming soon!")  # Replace with your status page or logic!
                if st.button("Back to Dashboard"):
                    st.session_state.student_page = "dashboard"
        elif st.session_state.get("role") == "admin":
            admin_dashboard()


if __name__ == "__main__":
    main()
