# DocVault

Save PDFs and photos of documents from your phone or PC. DocVault reads each one (OCR
for scans and photos), files it into a category, finds the date, sender and amount, gives
it a sensible file name, writes a summary, spots duplicates, and lets you search inside
everything.

```
backend/   FastAPI server: storage, text reading/OCR, categories, search, duplicates
app/       Flet app: same code runs as a PC window and as the web page phones use
serve.py   runs the API plus the web app at /app on one port
```

## Categories

Bills & Utilities · Bank & Finance · Insurance · Tax · Receipts & Purchases · Work & Payslips ·
ID & Travel · Health & Medical · Home & Property · Education & Certificates · Car & Vehicle ·
Manuals & Warranty · Letters & Government · Other. Add, rename, delete and reorder your own.

Documents DocVault isn't sure about go to the **Review** tab for a one-tap choice. Moving a
document is remembered and given to Claude as an example next time.

## How a document is read

1. **Text PDFs:** the text is taken from the PDF.
2. **Scanned PDFs and photos:** read with OCR (rapidocr), first 10 pages of a scan.
3. **Filing:** keyword rules plus patterns for dates, amounts and the sender. With
   `ANTHROPIC_API_KEY` set, Claude Haiku reads it instead (the PDF or photo itself when the
   text is thin) and writes a title, a one-line description and a summary of the key details
   (dates, deadlines, amounts, reference numbers).
4. **Duplicates:** the exact same file is never stored twice (re-sharing brings it back to the
   top); a different file with the same content is flagged as a possible duplicate.

## Run it

```bash
python -m venv .venv
.venv\Scripts\pip install -e "backend[dev]" "flet[all]==1.0.4" "flet-web==1.0.4"
copy backend\.env.example backend\.env          # set SECRET_KEY (and ANTHROPIC_API_KEY)
.venv\Scripts\python -m uvicorn serve:app --host 127.0.0.1 --port 8001
```

Open http://127.0.0.1:8001/app/ and create your account, then set
`ALLOW_REGISTRATION=false`. Tests: `cd backend && ..\.venv\Scripts\python -m pytest` (32 tests).

## Phone

- **Open your vault:** `https://<server>/app/` in Safari > Share > **Add to Home Screen**.
- **Add documents in the app:** **Add documents** picks PDFs/photos from Files or Photos.
- **Share from any app (iPhone Shortcut "Save to DocVault"):**
  1. Shortcuts > **+**, name it `Save to DocVault`, ⓘ > **Show in Share Sheet**, types:
     **PDFs**, **Images**, **Files**.
  2. **Repeat with Each** item in *Shortcut Input*.
  3. Inside it: **Get Contents of URL**, URL `https://<server>/u/<your dv_ key>`,
     **Show More** > Method **POST**, Request Body **File**, File = *Repeat Item*.
  4. After the repeat: **Show Notification** `Saved to DocVault ✓`.

  Then in Mail, Files, Safari, WhatsApp… tap **Share > Save to DocVault**. HEIC photos: add
  **Convert Image** to JPEG before *Get Contents of URL*. Copy the key and the full upload
  address from **Settings** in the app.

## API

| Method | Path | Purpose |
|---|---|---|
| POST | `/auth/register`, `/auth/login` | Token + API key |
| POST | `/documents` | Upload (multipart `file`) |
| POST | `/u/{api key}` | Upload for Shortcuts: body = the file (`?name=` optional) |
| GET | `/documents?q=&category=&review=&favorite=&duplicates=` | List / search inside documents |
| GET/PATCH/DELETE | `/documents/{id}` | Read (with full text) / edit / delete |
| POST | `/documents/{id}/refresh` | Read and file again |
| GET/POST/PATCH/DELETE | `/categories`, POST `/categories/reorder` | Manage categories |
| GET | `/f/{user}/{name}?sig=` | Signed file / preview link (`&download=1` = save with the nice name) |
