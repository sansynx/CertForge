from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin, urlparse, urlunparse

import cv2
import fitz
import numpy as np
import requests
from bs4 import BeautifulSoup


FetchBytes = Callable[[str], bytes]
FetchText = Callable[[str], tuple[str, str]]


@dataclass
class CertificateFields:
    name: str = ""
    course: str = ""
    course_code: str = ""
    assignment_score: str = ""
    exam_score: str = ""
    total_score: str = ""


@dataclass
class VerificationResult:
    filename: str
    status: str
    confidence: int
    qr_url: str = ""
    certificate_url: str = ""
    uploaded: CertificateFields = field(default_factory=CertificateFields)
    online: CertificateFields = field(default_factory=CertificateFields)
    field_matches: dict[str, bool] = field(default_factory=dict)
    messages: list[str] = field(default_factory=list)
    same_file: bool = False
    local_sha256: str = ""
    online_sha256: str = ""


FIELD_WEIGHTS = {
    "same_file": 40,
    "course_code": 12,
    "name": 12,
    "course": 8,
    "assignment_score": 13,
    "exam_score": 13,
    "total_score": 12,
}

OFFICIAL_CERTIFICATE_ORIGIN = "https://archive.nptel.ac.in"
ALLOWED_QR_HOSTS = {"nptel.ac.in", "archive.nptel.ac.in"}
MAX_PDF_PAGES = 10  # reject absurdly large PDFs


def _validate_nptel_url(url: str) -> str:
    """Raise ValueError if url is not a safe NPTEL URL, else return it."""
    try:
        parsed = urlparse(url)
    except Exception:
        raise ValueError(f"Malformed URL: {url!r}")
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Disallowed URL scheme: {parsed.scheme!r}")
    host = parsed.netloc.lower().split(":")[0]
    if not any(host == allowed or host.endswith("." + allowed) for allowed in ALLOWED_QR_HOSTS):
        raise ValueError(f"URL host {host!r} is not an allowed NPTEL domain.")
    return url


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def extract_qr_url(pdf_bytes: bytes) -> str:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    if doc.page_count > MAX_PDF_PAGES:
        raise ValueError(f"PDF has {doc.page_count} pages; maximum allowed is {MAX_PDF_PAGES}.")
    detector = cv2.QRCodeDetector()

    for page_index in range(doc.page_count):
        page = doc.load_page(page_index)
        for zoom in (1, 2, 3, 4, 5):
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                pix.height, pix.width, pix.n
            )
            data, _, _ = detector.detectAndDecode(image)
            if data:
                return data.strip()

            ok, decoded, _, _ = detector.detectAndDecodeMulti(image)
            if ok:
                for item in decoded:
                    if item:
                        return item.strip()

    return ""


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    if doc.page_count > MAX_PDF_PAGES:
        raise ValueError(f"PDF has {doc.page_count} pages; maximum allowed is {MAX_PDF_PAGES}.")
    return "\n".join(page.get_text() for page in doc)


def extract_certificate_pdf_url(html: str, base_url: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for anchor in soup.find_all("a", href=True):
        label = " ".join(anchor.get_text(" ", strip=True).split()).lower()
        href = anchor["href"]
        if href.lower().endswith(".pdf") or "certificate" in label:
            return force_official_certificate_origin(urljoin(base_url, href))
    return ""


def force_official_certificate_origin(url: str) -> str:
    parsed = urlparse(url)
    official = urlparse(OFFICIAL_CERTIFICATE_ORIGIN)
    return urlunparse(
        (
            official.scheme,
            official.netloc,
            parsed.path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )


def paired_value(uploaded_value: str, online_value: str) -> str:
    uploaded_label = uploaded_value or "not parsed"
    online_label = online_value or "not parsed"
    return f"uploaded: {uploaded_label} | online: {online_label}"


def default_fetch_text(url: str) -> tuple[str, str]:
    _validate_nptel_url(url)
    response = requests.get(
        url,
        timeout=10,
        allow_redirects=False,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    # follow at most one redirect, re-validating the target
    if response.is_redirect:
        location = response.headers.get("Location", "")
        _validate_nptel_url(location)
        response = requests.get(
            location,
            timeout=10,
            allow_redirects=False,
            headers={"User-Agent": "Mozilla/5.0"},
        )
    response.raise_for_status()
    return response.text, response.url


def default_fetch_bytes(url: str) -> bytes:
    _validate_nptel_url(url)
    response = requests.get(
        url,
        timeout=15,
        allow_redirects=False,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    if response.is_redirect:
        location = response.headers.get("Location", "")
        _validate_nptel_url(location)
        response = requests.get(
            location,
            timeout=15,
            allow_redirects=False,
            headers={"User-Agent": "Mozilla/5.0"},
        )
    response.raise_for_status()
    return response.content


def normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip().casefold()


def normalize_score(value: str) -> str:
    """Normalize a score string so that trailing zeros don't cause false mismatches.

    Examples: "67.50/75" == "67.5/75", "25.0/25" == "25/25", "93.0" == "93"
    Non-score strings are passed through the regular normalize path unchanged.
    """
    value = normalize(value)

    def _strip_zeros(num: str) -> str:
        if "." in num:
            return num.rstrip("0").rstrip(".")
        return num

    # fraction form  e.g. "67.50/75"
    fraction = re.fullmatch(r"(\d+(?:\.\d+)?)/(\d+(?:\.\d+)?)", value)
    if fraction:
        return f"{_strip_zeros(fraction.group(1))}/{_strip_zeros(fraction.group(2))}"

    # plain number e.g. "93.0"
    plain = re.fullmatch(r"\d+(?:\.\d+)?", value)
    if plain:
        return _strip_zeros(value)

    return value


def extract_fields_from_text(text: str) -> CertificateFields:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    roll = next((line for line in lines if re.fullmatch(r"NPTEL\d+[A-Z]+\d+S\d+", line)), "")
    score_lines = [line for line in lines if re.fullmatch(r"\d+(?:\.\d+)?/\d+(?:\.\d+)?", line)]
    assignment = score_lines[0] if len(score_lines) >= 1 else ""
    exam = score_lines[1] if len(score_lines) >= 2 else ""
    total = ""
    if exam in lines:
        exam_index = lines.index(exam)
        total = next(
            (
                candidate
                for candidate in lines[exam_index + 1 :]
                if re.fullmatch(r"\d+(?:\.\d+)?", candidate)
            ),
            "",
        )
    course = ""
    name = ""

    if assignment in lines:
        assignment_index = lines.index(assignment)
        if assignment_index >= 2:
            course = lines[assignment_index - 2]
            name = lines[assignment_index - 1]
    elif roll in lines:
        roll_index = lines.index(roll)
        prior_lines = lines[:roll_index]
        candidate_scores = [
            index
            for index, line in enumerate(prior_lines)
            if re.fullmatch(r"\d+(?:\.\d+)?/\d+(?:\.\d+)?", line)
        ]
        if candidate_scores and candidate_scores[0] >= 2:
            first_score_index = candidate_scores[0]
            course = prior_lines[first_score_index - 2]
            name = prior_lines[first_score_index - 1]

    return CertificateFields(
        name=name,
        course=course,
        course_code=roll,
        assignment_score=assignment,
        exam_score=exam,
        total_score=total,
    )


SCORE_FIELDS = {"assignment_score", "exam_score", "total_score"}


def calculate_confidence(
    uploaded: CertificateFields, online: CertificateFields, same_file: bool
) -> tuple[int, dict[str, bool]]:
    matches: dict[str, bool] = {}
    score = FIELD_WEIGHTS["same_file"] if same_file else 0

    for field_name, weight in FIELD_WEIGHTS.items():
        if field_name == "same_file":
            continue
        left = getattr(uploaded, field_name)
        right = getattr(online, field_name)
        norm = normalize_score if field_name in SCORE_FIELDS else normalize
        matched = bool(left and right and norm(left) == norm(right))
        matches[field_name] = matched
        if matched:
            score += weight

    return min(score, 100), matches


def status_from(confidence: int, messages: list[str]) -> str:
    if messages:
        return "needs_review"
    if confidence >= 90:
        return "verified"
    if confidence >= 60:
        return "partial_match"
    return "mismatch"


def verify_certificate(
    filename: str,
    pdf_bytes: bytes,
    fetch_text: FetchText = default_fetch_text,
    fetch_bytes: FetchBytes = default_fetch_bytes,
) -> VerificationResult:
    messages: list[str] = []
    local_sha = sha256_bytes(pdf_bytes)
    uploaded_fields = extract_fields_from_text(extract_text_from_pdf(pdf_bytes))
    qr_url = extract_qr_url(pdf_bytes)

    if not qr_url:
        return VerificationResult(
            filename=filename,
            status="qr_not_found",
            confidence=0,
            uploaded=uploaded_fields,
            local_sha256=local_sha,
            messages=["No QR code could be decoded from the uploaded PDF."],
        )

    try:
        html, resolved_url = fetch_text(qr_url)
        certificate_url = extract_certificate_pdf_url(html, resolved_url)
        if not certificate_url:
            raise ValueError("The NPTEL page did not expose a certificate PDF link.")
        online_pdf = fetch_bytes(certificate_url)
        online_sha = sha256_bytes(online_pdf)
        online_fields = extract_fields_from_text(extract_text_from_pdf(online_pdf))
        same_file = local_sha == online_sha
        confidence, matches = calculate_confidence(uploaded_fields, online_fields, same_file)
        return VerificationResult(
            filename=filename,
            status=status_from(confidence, messages),
            confidence=confidence,
            qr_url=qr_url,
            certificate_url=certificate_url,
            uploaded=uploaded_fields,
            online=online_fields,
            field_matches=matches,
            messages=messages,
            same_file=same_file,
            local_sha256=local_sha,
            online_sha256=online_sha,
        )
    except Exception as exc:
        messages.append(str(exc))
        return VerificationResult(
            filename=filename,
            status="fetch_failed",
            confidence=0,
            qr_url=qr_url,
            uploaded=uploaded_fields,
            messages=messages,
            local_sha256=local_sha,
        )


def result_to_dict(result: VerificationResult) -> dict:
    data = asdict(result)
    return data


def _sanitize_csv_field(value: str) -> str:
    """Prevent CSV formula injection by prefixing dangerous leading characters."""
    if value and value[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def build_csv(results: list[VerificationResult]) -> str:
    output = io.StringIO()
    columns = [
        "name",
        "course",
        "course_code",
        "assignment_score",
        "exam_score",
        "total_score",
        "confidence_level",
        "qr_url",
    ]
    writer = csv.DictWriter(output, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for result in results:
        uploaded = result.uploaded
        writer.writerow(
            {
                "name": _sanitize_csv_field(paired_value(uploaded.name, result.online.name)),
                "course": _sanitize_csv_field(paired_value(uploaded.course, result.online.course)),
                "course_code": _sanitize_csv_field(paired_value(uploaded.course_code, result.online.course_code)),
                "assignment_score": _sanitize_csv_field(paired_value(
                    uploaded.assignment_score, result.online.assignment_score
                )),
                "exam_score": _sanitize_csv_field(paired_value(uploaded.exam_score, result.online.exam_score)),
                "total_score": _sanitize_csv_field(paired_value(uploaded.total_score, result.online.total_score)),
                "confidence_level": result.confidence,
                "qr_url": _sanitize_csv_field(result.qr_url),
            }
        )
    return output.getvalue()


def verify_pdf_path(path: Path) -> VerificationResult:
    return verify_certificate(path.name, path.read_bytes())
