# CertForge - NPTEL Certificate Verifier

A batch verification tool for NPTEL certificate PDFs. Upload one certificate or a full batch, and CertForge checks each one against the official NPTEL archive using the embedded QR code.

---

## How It Works

### 1. QR Decode
Each uploaded PDF is scanned for an embedded QR code using OpenCV. The QR code contains the official NPTEL verification URL for that certificate. The scanner tries multiple zoom levels to handle low-resolution PDFs.

### 2. Fetch Online Certificate
CertForge opens the QR URL, scrapes the NPTEL archive page for the certificate PDF link, and downloads the official PDF directly from `archive.nptel.ac.in`. The domain is always forced to the official origin to prevent spoofing.

Here is exactly what happens on the server for each certificate:

```
Browser uploads PDF → Flask server
                            ↓
                  Extracts QR URL from PDF
                  (e.g. https://nptel.ac.in/noc/Ecertificate/?q=NPTEL25CS38S542200012)
                            ↓
                  GET request to that QR URL
                  BeautifulSoup finds the <a href="...cert.pdf"> link on the page
                            ↓
                  Downloads the official PDF from archive.nptel.ac.in into memory
                  (never written to disk — lives as bytes for the request lifetime)
                            ↓
                  Extracts text from both PDFs using PyMuPDF
                            ↓
                  Compares fields + SHA-256 hash
                            ↓
                  Returns JSON result to browser
```

### 3. Extract Fields
Both the uploaded PDF and the online PDF go through the same text extraction pipeline using PyMuPDF. The parser pulls out:

- Student name
- Course name
- Course code (e.g. `NPTEL25CS38S542200012`)
- Assignment score (e.g. `25/25`)
- Exam score (e.g. `67.5/75`)
- Total score (e.g. `93`)

Score values are normalized before comparison trailing zeros are stripped so `67.50/75` matches `67.5/75` and `93.0` matches `93`.

### 4. Confidence Scoring
Each certificate gets a confidence score out of 100 based on how closely the uploaded PDF matches the official online version:

| Check | Points |
|---|---|
| Exact PDF match (SHA-256) | 40 |
| Assignment score match | 13 |
| Exam score match | 13 |
| Course code match | 12 |
| Name match | 12 |
| Total score match | 12 |
| Course name match | 8 |
| **Total** | **100** |

The SHA-256 check compares the raw bytes of both PDFs. If they are identical, that alone accounts for 40 points and is the strongest signal of authenticity.

### 5. Status Labels

| Status | Condition |
|---|---|
| `verified` | Confidence ≥ 90 |
| `partial match` | Confidence 60-89 |
| `mismatch` | Confidence < 60 |
| `needs review` | Any fetch or parse warning |
| `qr not found` | No QR code detected in the PDF |
| `fetch failed` | Could not reach the NPTEL archive |

### 6. Export
Results can be exported as a CSV with uploaded and online values shown side by side in each column.

---

## Project Structure

```
certforge/
├── app.py                      # Flask app — routes, security headers, API endpoints
├── nptel_verifier.py           # Core verification logic
├── requirements.txt            # Pinned Python dependencies
├── .gitignore
├── static/
│   ├── app.js                  # Frontend — upload, verify, render results
│   ├── nav.js                  # Mobile nav toggle
│   ├── styles.css              # All styles (desktop + mobile responsive)
│   ├── favicon.svg             # Site favicon
│   └── Cinematic_Sky.mp4       # Hero background video
└── templates/
    ├── index.html              # Landing page
    └── toolkit.html            # Upload and results toolkit
```

---

## Safety Limits

CertForge only follows HTTPS links on `nptel.ac.in` and `archive.nptel.ac.in`, including after redirects. Uploaded batches are limited to 100 PDFs and 50 MB in total. To keep PDF rendering and archive downloads bounded, each PDF is limited to 10 pages, QR rendering is capped by pixel count, verification pages are limited to 2 MB, and downloaded archive PDFs are limited to 50 MB.

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Landing page |
| `GET` | `/toolkit` | Upload toolkit |
| `POST` | `/api/verify` | Accepts PDF uploads, returns JSON results |
| `POST` | `/api/export` | Accepts JSON results, returns CSV download |
| `GET` | `/health` | Health check |

`/api/export` accepts at most 100 result records, matching the upload batch limit.

---

## Running Locally

```bash
python app.py
```

Open in browser:

```
http://127.0.0.1:5000
```

This uses Flask's built-in development server, which is fine for local testing. You will see a warning that says *"This is a development server."* — that is expected and can be ignored locally.

The app requires internet access to fetch the official NPTEL certificate PDF during verification.

## Running in Production

Gunicorn does **not** work on Windows (missing `fcntl` module). Use **Waitress** instead:

```bash
waitress-serve --host=127.0.0.1 --port=5000 app:app
```

On Linux/macOS you can use Gunicorn:

```bash
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```

To enable debug mode locally (never in production):

```bash
set FLASK_DEBUG=1   # Windows
python app.py
```

---

## CSV Export Format

```
name, course, course_code, assignment_score, exam_score, total_score, confidence_level, qr_url
```

Score columns contain both values in the format `uploaded: X | online: Y` for easy side-by-side review.

---

## Requirements

Install dependencies:

```bash
pip install -r requirements.txt
```

- Python 3.10+
- Flask 3.1.0
- PyMuPDF 1.24.10
- OpenCV 4.12.0
- NumPy 2.2.6
- Requests 2.32.3
- BeautifulSoup4 4.14.3
- lxml 6.0.0
- Waitress 3.0.2 (production server, Windows)

## Setup

It is recommended to run the app inside a virtual environment to keep dependencies isolated.

**Windows**

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

**macOS / Linux**

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

To deactivate the virtual environment when you are done:

```bash
deactivate
```
