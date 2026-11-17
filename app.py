from difflib import SequenceMatcher
import os
import re
import sqlite3
import fitz
import pandas as pd
import streamlit as st

st.set_page_config(page_title="CSMSS DATA", layout="wide")

ADMIN_PASSWORD = "csmss123"

os.makedirs("photos", exist_ok=True)
os.makedirs("pdfs", exist_ok=True)
os.makedirs("doc_pages", exist_ok=True)


def init_db():
  conn = sqlite3.connect("csmss_data.db")
  cursor = conn.cursor()
  cursor.execute(
      "CREATE TABLE IF NOT EXISTS teachers (id INTEGER PRIMARY KEY"
      " AUTOINCREMENT, department TEXT, name TEXT, qualification TEXT,"
      " designation TEXT, photo_path TEXT, doc_image_path TEXT, full_details"
      " TEXT)"
  )
  cursor.execute("PRAGMA table_info(teachers)")
  cols = [row[1] for row in cursor.fetchall()]
  new_cols = {
      "doc_image_path": "TEXT",
      "role_type": "TEXT DEFAULT 'Teacher'",
      "roll_no": "TEXT",
      "mobile": "TEXT",
      "address": "TEXT",
  }
  for c_name, c_type in new_cols.items():
    if c_name not in cols:
      cursor.execute(f"ALTER TABLE teachers ADD COLUMN {c_name} {c_type}")
  cursor.execute(
      "UPDATE teachers SET role_type = 'Teacher' WHERE role_type IS NULL OR"
      " role_type = ''"
  )
  conn.commit()
  conn.close()


init_db()

DEFAULT_PHOTO = "https://flaticon.com"


def clean_filename(name):
  return re.sub(r"[^a-zA-Z0-9]", "_", name)


def save_uploaded_photo(uploaded_img, person_name):
  if not uploaded_img:
    return ""
  ext = os.path.splitext(uploaded_img.name)[1] or ".jpg"
  safe = (
      clean_filename(person_name)
      + "_"
      + str(int(pd.Timestamp.now().timestamp()))
  )
  path = os.path.join("photos", f"{safe}{ext}")
  with open(path, "wb") as f:
    f.write(uploaded_img.read())
  return path


def find_duplicate(name, roll_no="", mobile=""):
  conn = sqlite3.connect("csmss_data.db")
  cur = conn.cursor()
  cur.execute("SELECT id, name, department, role_type, roll_no, mobile, photo_path FROM teachers")
  rows = cur.fetchall()
  conn.close()

  clean_new = re.sub(r"\s+", " ", name.strip().lower())
  for r in rows:
    r_id, r_name, r_dept, r_role, r_roll, r_mob, r_photo = r
    clean_old = re.sub(r"\s+", " ", str(r_name).strip().lower())
    sim = SequenceMatcher(None, clean_new, clean_old).ratio()
    if clean_new == clean_old or sim >= 0.85:
      return r, "Name already exists in database"
    if roll_no and r_roll and roll_no.strip().lower() == str(r_roll).strip().lower():
      return r, "Roll Number already registered"
    if mobile and r_mob and mobile.strip() == str(r_mob).strip():
      return r, "Mobile Number already registered"
  return None, ""


def process_uploaded_pdf(uploaded_file):
  raw_bytes = uploaded_file.read()
  base_name, _ = os.path.splitext(uploaded_file.name)
  safe_name = clean_filename(base_name)
  pdf_path = os.path.join("pdfs", f"{safe_name}.pdf")
  with open(pdf_path, "wb") as f:
    f.write(raw_bytes)

  doc = fitz.open(pdf_path)
  all_text, page_images, photo_path = [], [], ""
  for page_idx in range(len(doc)):
    page = doc[page_idx]
    txt = page.get_text("text").strip()
    if txt:
      all_text.append(txt)
    pix = page.get_pixmap(dpi=150)
    p_img = os.path.join("doc_pages", f"{safe_name}_p{page_idx + 1}.png")
    pix.save(p_img)
    page_images.append(p_img)
    if page_idx == 0 and not photo_path:
      best_img, max_size = None, 0
      for img_info in page.get_images(full=True):
        xref, *_ = img_info
        b_img = doc.extract_image(xref)
        if 2500 < len(b_img["image"]) < 800000 and len(b_img["image"]) > max_size:
          max_size, best_img = len(b_img["image"]), b_img
      if best_img:
        photo_path = os.path.join("photos", f"{safe_name}.{best_img['ext']}")
        with open(photo_path, "wb") as img_f:
          img_f.write(best_img["image"])
  doc.close()

  combined = "\n\n".join(all_text).strip() or "See document pages below."
  joined_imgs = "|".join(page_images)
  conn = sqlite3.connect("csmss_data.db")
  cursor = conn.cursor()
  cursor.execute("SELECT id, name FROM teachers")
  matched_id, best_score = None, 0
  pool = (base_name + " " + combined[:500]).lower()
  for t_id, t_name in cursor.fetchall():
    tokens = [w.lower() for w in re.sub(r"[^a-zA-Z\s]", " ", t_name).split() if len(w) > 3]
    score = sum(1 for tok in tokens if tok in pool)
    if score > best_score:
      best_score, matched_id = score, t_id

  if matched_id and best_score >= 1:
    if photo_path:
      cursor.execute("UPDATE teachers SET photo_path=?, doc_image_path=?, full_details=? WHERE id=?", (photo_path, joined_imgs, combined, matched_id))
    else:
      cursor.execute("UPDATE teachers SET doc_image_path=?, full_details=? WHERE id=?", (joined_imgs, combined, matched_id))
  else:
    cursor.execute("INSERT INTO teachers (role_type, department, name, qualification, designation, photo_path, doc_image_path, full_details) VALUES ('Teacher',?,?,?,?,?,?,?)", ("Computer Engineering", base_name.upper(), "Faculty", "FACULTY", photo_path, joined_imgs, combined))
  conn.commit()
  conn.close()
def parse_sections(raw_text):
  lines = [re.sub(r"\s+", " ", l).strip() for l in str(raw_text).split("\n") if l.strip()]
  full_str = "\n".join(lines)
  emails = list(set(re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", full_str)))
  phones = list(set(re.findall(r"(?:\+91[\-\s]?)?[6-9]\d{9}", full_str)))
  sections = {
      "Contact & Address": [],
      "Education & Qualification": [],
      "Experience & Subjects": [],
      "Personal & Family Details": [],
      "Achievements & Other Info": [],
  }
  cat = "Achievements & Other Info"
  for line in lines:
    low = line.lower()
    if any(k in low for k in ["address", "email", "mobile", "phone", "contact", "city", "pin", "aurangabad", "chhatrapati"]):
      cat = "Contact & Address"
    elif any(k in low for k in ["qualification", "education", "degree", "b.e", "m.e", "m.tech", "phd", "university", "college", "diploma"]):
      cat = "Education & Qualification"
    elif any(k in low for k in ["experience", "subject", "taught", "teaching", "industrial", "designation", "years"]):
      cat = "Experience & Subjects"
    elif any(k in low for k in ["family", "father", "mother", "spouse", "husband", "wife", "dob", "birth", "gender", "marital", "blood"]):
      cat = "Personal & Family Details"
    if line not in sections[cat]:
      sections[cat].append(line)
  return emails, phones, sections


@st.dialog("ADD NEW PROFILE", width="large")
def add_record_dialog():
  role = st.radio("Who are you adding?", ["Student", "Teacher"], horizontal=True)
  st.caption("* Name and Photo are compulsory. Other fields are optional.")
  name = st.text_input("Full Name *")
  photo = st.file_uploader("Upload Photo *", type=["jpg", "jpeg", "png"])

  if role == "Student":
    c1, c2 = st.columns(2)
    roll_no = c1.text_input("Roll Number (Optional)")
    dept = c2.selectbox("Branch / Department", ["Computer Engineering", "AIML", "Mechanical Engineering", "Civil Engineering", "Electrical Engineering", "E&TC"])
    c3, c4 = st.columns(2)
    year_val = c3.selectbox("Year", ["First Year (FY)", "Second Year (SY)", "Third Year (TY)"])
    mobile = c4.text_input("Mobile Number (Optional)")
    address = st.text_area("Home Address (Optional)", height=70)
    extra = st.text_area("Additional Info (Optional)", height=70)
    desig, qual = year_val, "Diploma Student"
  else:
    c1, c2 = st.columns(2)
    dept = c1.selectbox("Department", ["Computer Engineering", "AIML", "Mechanical Engineering", "Civil Engineering", "Electrical Engineering", "E&TC", "Science & Humanities"])
    desig = c2.text_input("Designation (Optional, e.g., Lecturer, HOD)")
    c3, c4 = st.columns(2)
    qual = c3.text_input("Education / Qualification (Optional)")
    mobile = c4.text_input("Mobile Number (Optional)")
    address = st.text_area("Address (Optional)", height=70)
    extra = st.text_area("Experience / Subjects / Family Info (Optional)", height=70)
    roll_no = ""

  if st.button("Save Profile", type="primary", use_container_width=True):
    if not name.strip() or not photo:
      st.error("Name and Photo are compulsory!")
    else:
      dup, reason = find_duplicate(name, roll_no, mobile)
      if dup:
        st.error(f"⚠️ Profile Already Exists! ({reason})")
        with st.container(border=True):
          dc1, dc2 = st.columns((1, 3))
          _, d_name, d_dept, d_role, _, _, d_photo = dup
          dc1.image(d_photo if d_photo and os.path.exists(d_photo) else DEFAULT_PHOTO, width=90)
          dc2.write(f"**Existing Name:** {d_name}")
          dc2.write(f"**Category:** {d_role} | **Dept:** {d_dept}")
      else:
        saved_photo = save_uploaded_photo(photo, name)
        details_parts = [f"Name: {name}", f"Category: {role}", f"Department: {dept}"]
        if roll_no:
          details_parts.append(f"Roll No: {roll_no}")
        if qual:
          details_parts.append(f"Education: {qual}")
        if desig:
          details_parts.append(f"Designation: {desig}")
        if mobile:
          details_parts.append(f"Mobile: {mobile}")
        if address:
          details_parts.append(f"Address: {address}")
        if extra:
          details_parts.append(extra)

        conn = sqlite3.connect("csmss_data.db")
        cur = conn.cursor()
        cur.execute("INSERT INTO teachers (role_type, department, name, qualification, designation, roll_no, mobile, address, photo_path, full_details) VALUES (?,?,?,?,?,?,?,?,?,?)", (role, dept, name.strip(), qual or "-", desig or role.upper(), roll_no, mobile, address, saved_photo, "\n".join(details_parts)))
        conn.commit()
        conn.close()
        st.success("Profile created successfully!")
        st.rerun()
@st.dialog("ADMIN EDIT RECORD", width="large")
def edit_record_dialog(person):
  st.subheader(f"Editing: {person['name']}")
  new_name = st.text_input("Full Name *", value=person["name"])
  new_photo = st.file_uploader("Change Photo (Optional)", type=["jpg", "jpeg", "png"])
  c1, c2 = st.columns(2)
  new_dept = c1.text_input("Department / Branch", value=person["department"] or "")
  new_desig = c2.text_input("Designation / Year", value=person["designation"] or "")
  c3, c4 = st.columns(2)
  new_qual = c3.text_input("Education / Qualification", value=person["qualification"] or "")
  new_roll = c4.text_input("Roll Number", value=person.get("roll_no") or "")
  new_mobile = st.text_input("Mobile Number", value=person.get("mobile") or "")
  new_addr = st.text_area("Address", value=person.get("address") or "", height=70)
  new_details = st.text_area("Complete Bio / Notes", value=person["full_details"] or "", height=130)

  b_save, b_del = st.columns(2)
  if b_save.button("Update Record", type="primary", use_container_width=True):
    photo_to_save = save_uploaded_photo(new_photo, new_name) if new_photo else person["photo_path"]
    conn = sqlite3.connect("csmss_data.db")
    cur = conn.cursor()
    cur.execute("UPDATE teachers SET name=?, department=?, designation=?, qualification=?, roll_no=?, mobile=?, address=?, photo_path=?, full_details=? WHERE id=?", (new_name.strip(), new_dept, new_desig, new_qual, new_roll, new_mobile, new_addr, photo_to_save, new_details, person["id"]))
    conn.commit()
    conn.close()
    st.rerun()

  if b_del.button("Delete Record", use_container_width=True):
    conn = sqlite3.connect("csmss_data.db")
    cur = conn.cursor()
    cur.execute("DELETE FROM teachers WHERE id=?", (person["id"],))
    conn.commit()
    conn.close()
    st.rerun()


@st.dialog("PERSONNEL COMPLETE RECORD", width="large")
def show_details(person):
  c1, c2 = st.columns((1, 2.2))
  with c1:
    p = str(person.get("photo_path") or "")
    st.image(p if p and os.path.exists(p) else DEFAULT_PHOTO, use_container_width=True)
  with c2:
    st.subheader(str(person.get("name") or ""))
    role_val = str(person.get("role_type") or "Teacher")
    dept_val = str(person.get("department") or "-")
    st.write(f"**Category:** {role_val} | **Dept:** {dept_val}")

    roll_val = str(person.get("roll_no") or "").strip()
    if roll_val and roll_val.lower() != "nan":
      st.write(f"**Roll Number:** {roll_val}")

    st.write(f"**Designation / Year:** {str(person.get('designation') or '-')}")
    st.write(f"**Education:** {str(person.get('qualification') or '-')}")

    emails, phones, sections = parse_sections(str(person.get("full_details") or ""))
    mob_val = str(person.get("mobile") or "").strip()
    if mob_val and mob_val.lower() != "nan" and mob_val not in phones:
      phones.insert(0, mob_val)

    if emails:
      st.write(f"**Email:** {', '.join(str(e) for e in emails)}")
    if phones:
      st.write(f"**Mobile:** {', '.join(str(ph) for ph in phones)}")

    addr_val = str(person.get("address") or "").strip()
    if addr_val and addr_val.lower() != "nan":
      st.write(f"**Address:** {addr_val}")

  st.divider()
  t1, t2, t3 = st.tabs(["Structured Profile", "Original Document Pages", "Full Text"])
  with t1:
    for title, items in sections.items():
      if items:
        with st.container(border=True):
          st.markdown(f"#### {title}")
          for it in items:
            st.write(f"- {it}")
  with t2:
    imgs = str(person.get("doc_image_path") or "")
    for ip in imgs.split("|"):
      if ip and os.path.exists(ip):
        st.image(ip, use_container_width=True)
  with t3:
    st.write(str(person.get("full_details") or ""))



st.sidebar.header("🔐 Admin Access")
admin_input = st.sidebar.text_input("Enter Admin PIN to Edit:", type="password")
is_admin = admin_input == ADMIN_PASSWORD
if is_admin:
  st.sidebar.success("Admin Mode Unlocked!")
  st.sidebar.divider()
  st.sidebar.subheader("Upload Faculty PDFs")
  files = st.sidebar.file_uploader("Select PDF files:", type=["pdf"], accept_multiple_files=True)
  if files and st.sidebar.button("Extract & Save All PDFs", use_container_width=True):
    for f in files:
      process_uploaded_pdf(f)
    st.sidebar.success("Saved!")
    st.rerun()

conn = sqlite3.connect("csmss_data.db")
df = pd.read_sql_query("SELECT * FROM teachers", conn)
conn.close()

top_c1, top_c2 = st.columns((3, 1))
with top_c1:
  st.title("CSMSS DATA")
with top_c2:
  st.write("")
  if st.button("➕ Add Profile", type="primary", use_container_width=True):
    add_record_dialog()

st.divider()

f1, f2, f3 = st.columns((2, 1, 1))
q = f1.text_input("Search Name, Roll No, Address or Keyword:", placeholder="Type name (e.g., pophale, phopa)...")
role_filter = f2.selectbox("Category:", ["All", "Teacher", "Student"])
dept_list = ["All Departments"] + sorted(list(df["department"].dropna().unique()))
dept_filter = f3.selectbox("Department:", dept_list)

fdf = df.copy()
if role_filter != "All":
  fdf = fdf[fdf["role_type"] == role_filter]
if dept_filter != "All Departments":
  fdf = fdf[fdf["department"] == dept_filter]
if q:
  fdf = fdf[fdf.apply(lambda r: q.lower() in f"{r['name']} {r.get('roll_no','')} {r.get('address','')} {r['full_details']}".lower() or any(SequenceMatcher(None, q.lower(), w).ratio() >= 0.65 for w in str(r["name"]).lower().split()), axis=1)]

st.write(f"**Total Records:** {len(fdf)}")
cols = st.columns(4)
for idx, (_, row) in enumerate(fdf.iterrows()):
  with cols[idx % 4]:
    with st.container(border=True):
      p = row["photo_path"]
      st.image(p if p and os.path.exists(p) else DEFAULT_PHOTO, use_container_width=True)
      st.markdown(f"**{row['name']}**")
      sub_txt = f"Roll: {row['roll_no']} | {row['designation']}" if row.get("roll_no") else row["designation"]
      st.caption(sub_txt)
      if is_admin:
        b1, b2 = st.columns(2)
        if b1.button("View", key=f"v_{row['id']}", use_container_width=True):
          show_details(row)
        if b2.button("Edit", key=f"e_{row['id']}", use_container_width=True):
          edit_record_dialog(row)
      else:
        if st.button("View Details", key=f"v_{row['id']}", use_container_width=True):
          show_details(row)
