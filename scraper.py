import os
import re
import sqlite3
from urllib.parse import urljoin
import fitz  # PyMuPDF
from playwright.sync_api import sync_playwright

os.makedirs('photos', exist_ok=True)
os.makedirs('pdfs', exist_ok=True)
os.makedirs('doc_pages', exist_ok=True)

conn = sqlite3.connect('csmss_data.db')
cursor = conn.cursor()
cursor.execute('DROP TABLE IF EXISTS teachers')

cursor.execute('''
CREATE TABLE teachers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    department TEXT,
    name TEXT,
    qualification TEXT,
    designation TEXT,
    photo_path TEXT,
    doc_image_path TEXT,
    full_details TEXT
)
''')
conn.commit()


def clean_filename(name):
  return re.sub(r'[^a-zA-Z0-9]', '_', name)


def process_pdf(pdf_bytes, name):
  photo_path = ''
  doc_img_path = ''
  extracted_text = ''

  safe_name = clean_filename(name)
  pdf_file = os.path.join('pdfs', f'{safe_name}.pdf')
  with open(pdf_file, 'wb') as f:
    f.write(pdf_bytes)

  try:
    doc = fitz.open(pdf_file)
    text_list = []

    for page_idx in range(len(doc)):
      page = doc[page_idx]
      text_list.append(page.get_text('text'))

      # पहिल्या पेजचे पूर्ण इमेज रेंडरिंग (जेणेकरून स्कॅन केलेला डेटा सुद्धा स्पष्ट दिसेल)
      if page_idx == 0:
        pix = page.get_pixmap(dpi=150)
        doc_img_path = os.path.join('doc_pages', f'{safe_name}_page1.png')
        pix.save(doc_img_path)

        # PDF मधील शिक्षकाचा पासपोर्ट फोटो वेगळा काढणे
        images = page.get_images(full=True)
        best_img = None
        max_size = 0
        for img_info in images:
          xref = img_info[0]
          base_image = doc.extract_image(xref)
          img_bytes = base_image['image']
          if 3000 < len(img_bytes) < 500000 and len(img_bytes) > max_size:
            max_size = len(img_bytes)
            best_img = base_image

        if best_img:
          ext = best_img['ext']
          photo_path = os.path.join('photos', f'{safe_name}.{ext}')
          with open(photo_path, 'wb') as img_f:
            img_f.write(best_img['image'])

    extracted_text = '\n'.join(text_list).strip()
    doc.close()
  except Exception as e:
    extracted_text = f'PDF Read Error: {e}'

  return photo_path, doc_img_path, extracted_text


def start_extraction():
  dept_name = 'Computer Engineering'
  with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    context = browser.new_context(ignore_https_errors=True)
    page = context.new_page()

    page.goto(
        'https://csmsspoly.com',
        wait_until='domcontentloaded',
        timeout=60000,
    )

    print('\n' + '=' * 60)
    print(
        '👉 उघडलेल्या Chrome मध्ये Popup बंद करून DEPARTMENT -> Computer'
        ' Engineering वर जा.'
    )
    print('👉 शिक्षकांची यादी दिसली की इथे टर्मिनलमध्ये ENTER दाब!')
    print('=' * 60)
    input('\nPress ENTER here after Computer Engineering page is open...')

    current_url = page.url
    tables = page.locator('table')
    target_table = None
    for i in range(tables.count()):
      if 'Qualification' in tables.nth(i).inner_text():
        target_table = tables.nth(i)
        break

    if not target_table:
      print('❌ Table not found!')
      browser.close()
      return

    rows = target_table.locator('tr')
    total_rows = rows.count()
    print(f'\n✅ Extracting complete data for {total_rows - 1} faculty...\n')

    for i in range(1, total_rows):
      row = rows.nth(i)
      cols = row.locator('td')
      if cols.count() >= 4:
        name = ' '.join(cols.nth(1).inner_text().split())
        qual = ' '.join(cols.nth(2).inner_text().split())
        desig = ' '.join(cols.nth(3).inner_text().split())

        local_photo = ''
        doc_img = ''
        bio_text = ''

        if cols.count() >= 5:
          view_link = cols.nth(4).locator('a')
          if view_link.count() > 0:
            href = view_link.first.get_attribute('href') or ''
            if href and href != '#':
              full_link = urljoin(current_url, href)
              try:
                # ब्राउझरच्या सेशनमधूनच थेट PDF फाईल डाउनलोड करणे
                api_res = context.request.get(full_link, timeout=20000)
                if api_res.ok:
                  body = api_res.body()
                  if body[:4] == b'%PDF':
                    local_photo, doc_img, bio_text = process_pdf(body, name)
                  else:
                    # जर HTML पेज असेल तर त्याचा सर्व मजकूर घेणे
                    temp_page = context.new_page()
                    temp_page.goto(full_link, wait_until='domcontentloaded')
                    temp_page.wait_for_timeout(1500)
                    bio_text = temp_page.locator('body').inner_text()
                    temp_page.close()
              except Exception as e:
                bio_text = f'Fetch error: {e}'

        if not bio_text or len(bio_text) < 15:
          bio_text = (
              f'Name: {name}\nDepartment: {dept_name}\nQualification:'
              f' {qual}\nDesignation: {desig}\n(Refer to the attached profile'
              ' document below for complete details)'
          )

        cursor.execute(
            """
                    INSERT INTO teachers (department, name, qualification, designation, photo_path, doc_image_path, full_details)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
            (dept_name, name, qual, desig, local_photo, doc_img, bio_text),
        )
        conn.commit()
        print(
            f'✅ Saved: {name} | Photo: {"YES" if local_photo else "NO"} |'
            f' Full Doc: {"YES" if doc_img else "NO"}'
        )

    browser.close()
    print('\n🎉 ALL DONE! 100% Data Extracted & Saved!')


start_extraction()
conn.close()
