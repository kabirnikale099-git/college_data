import os
import re
import sqlite3
import fitz

os.makedirs("photos", exist_ok=True)
os.makedirs("doc_pages", exist_ok=True)

PDF_FILE = "all_teachers.pdf"
conn = sqlite3.connect("csmss_data.db")
cur = conn.cursor()


def clean_name(text):
  return re.sub(r"[^a-zA-Z0-9]", "_", text)[:40]


def map_department(raw_dept):
  d = raw_dept.lower()
  if "artificial" in d or "aiml" in d or "machine learning" in d:
    return "AIML"
  if "computer" in d:
    return "Computer Engineering"
  if "civil" in d:
    return "Civil Engineering"
  if "electrical" in d:
    return "Electrical Engineering"
  if "mechanical" in d:
    return "Mechanical Engineering"
  if "electronic" in d or "entc" in d or "telecommunication" in d:
    return "E&TC"
  if "science" in d or "humanities" in d or "first year" in d or "applied" in d:
    return "Science & Humanities"
  return raw_dept.strip().title() if raw_dept.strip() else "General"


def get_val(kv_dict, keyword):
  for k, v in kv_dict.items():
    if keyword.lower() in k.lower() and v.strip():
      return v.strip()
  return ""
doc = fitz.open(PDF_FILE)
print(f"Scanning {len(doc)} pages accurately...\n")
count = 0

for page_idx in range(len(doc)):
  page = doc[page_idx]
  txt = page.get_text("text")
  if "Faculty Profile" not in txt and "Profile of Principal" not in txt:
    continue

  kv = {}
  ordered_pairs = []
  for tab in page.find_tables():
    for row in tab.extract():
      cells = [re.sub(r"\s+", " ", str(c)).strip() for c in row if c and str(c).strip()]
      if len(cells) >= 2:
        k, v = cells[0], " | ".join(cells[1:])
        kv[k] = v
        ordered_pairs.append(f"{k}: {v}")

  title = get_val(kv, "Title")
  fname = get_val(kv, "First name")
  mname = get_val(kv, "Middle name")
  sname = get_val(kv, "Surname")

  full_name = " ".join(p for p in [title, fname, mname, sname] if p).strip()
  if not full_name:
    full_name = get_val(kv, "Name")
  if not full_name or len(full_name) < 4:
    continue

  raw_dept = get_val(kv, "Department")
  dept = "Administration" if "Principal" in txt else map_department(raw_dept)
  desig = get_val(kv, "Designation") or "Lecturer"
  qual = get_val(kv, "Highest Degree") or get_val(kv, "PG Degree") or get_val(kv, "UG degree") or "-"
  email = get_val(kv, "Email")

  safe_id = f"p{page_idx + 1}_{clean_name(full_name)}"
  doc_img_path = os.path.join("doc_pages", f"{safe_id}.png")
  page.get_pixmap(dpi=150).save(doc_img_path)

  photo_path = ""
  best_img, max_size = None, 0
  for img_info in page.get_images(full=True):
    xref, *_ = img_info
    b_img = doc.extract_image(xref)
    if 2500 < len(b_img["image"]) < 800000 and len(b_img["image"]) > max_size:
      max_size, best_img = len(b_img["image"]), b_img

  if best_img:
    photo_path = os.path.join("photos", f"{safe_id}.{best_img['ext']}")
    with open(photo_path, "wb") as f:
      f.write(best_img["image"])

  clean_bio = "\n".join(ordered_pairs) if ordered_pairs else txt.strip()

  cur.execute("SELECT id, name FROM teachers WHERE role_type='Teacher'")
  existing_id = None
  s_key = sname.lower() if len(sname) > 3 else fname.lower()
  for tid, tname in cur.fetchall():
    if s_key and s_key in tname.lower() and (fname.lower() in tname.lower() or len(s_key) > 5):
      existing_id = tid
      break

  if existing_id:
    if photo_path:
      cur.execute("UPDATE teachers SET name=?, department=?, qualification=?, designation=?, photo_path=?, doc_image_path=?, full_details=? WHERE id=?", (full_name, dept, qual, desig, photo_path, doc_img_path, clean_bio, existing_id))
    else:
      cur.execute("UPDATE teachers SET name=?, department=?, qualification=?, designation=?, doc_image_path=?, full_details=? WHERE id=?", (full_name, dept, qual, desig, doc_img_path, clean_bio, existing_id))
  else:
    cur.execute("INSERT INTO teachers (role_type, department, name, qualification, designation, photo_path, doc_image_path, full_details) VALUES ('Teacher',?,?,?,?,?,?,?)", (dept, full_name, qual, desig, photo_path, doc_img_path, clean_bio))

  count += 1
  print(f"Saved: {full_name} | {dept} | {qual}")

conn.commit()
conn.close()
doc.close()
print(f"\nDONE! {count} profiles updated cleanly!")
