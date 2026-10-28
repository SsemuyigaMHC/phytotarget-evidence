#!/usr/bin/env python3
"""
Download accessible full-text artifacts for the metadata acquisition stage.

Resume state is taken from the persistent TEXT log plus validated files on disk. Acquisition files are organized by the exact metadata-screened Acquisition Priority + Screening Route strata:
    data/logs/03_Full_Text_Acquisition_FAST.log

No Excel progress file is used.

Important behaviour
-------------------
* Only the final Stage 02 metadata-screened queue is processed.
* A PMID is completed ONLY when a validated article-level PDF, HTML, or XML
  has actually been saved.
* The downloader resumes from the text log and from validated files already
  present on disk.
* Successful PMIDs are skipped automatically on later runs.
* A PMID that was merely "Processing" in an older/interrupted run is NOT
  considered complete; it will be retried.
* SSL certificate verification failures are NOT retried indefinitely.
* HTTP 429 and temporary 5xx responses are retried with a capped backoff.
* Temporary network/timeout failures are retried with a capped backoff.
* Permanent HTTP failures such as 403/404/410 move to the next route.
* One failed URL or supplementary file never blocks the next paper.
* Google Scholar is deliberately NOT used.
* Publisher landing pages are accepted only when they validate as full article
  HTML.
* PDF, HTML and XML content are validated before being saved.
* Supplementary files are stored separately from article files.
* The text log is append-only and is the source of resume information.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from pathlib import Path
import re
import time
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup
from lxml import etree
from requests.adapters import HTTPAdapter
from tqdm import tqdm


# ============================================================================
# PATHS
# ============================================================================

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
METADATA_DIR = DEFAULT_DATA_DIR / "metadata"
FULL_TEXT_DIR = DEFAULT_DATA_DIR / "full_text"
LOG_DIR = DEFAULT_DATA_DIR / "logs"
TEXT_LOG_PATH = LOG_DIR / "03_Full_Text_Acquisition_FAST.log"


# ============================================================================
# STORAGE STRUCTURE
# ============================================================================

# The metadata-screened acquisition strata are authoritative.  Stage 03 does
# not recreate scientific screening; it only preserves the exact
# Acquisition Priority + Screening Route pair assigned by metadata screening.
# Example: P1_CORE_FULL_TEXT / CORE_MECHANISTIC_THERAPEUTIC

def clean_group_component(value: object) -> str:
    value = clean_identifier(value).upper()
    value = re.sub(r"[^A-Z0-9._-]+", "_", value)
    return value.strip("._-")

def group_directory(group: str) -> Path:
    group = clean_identifier(group).upper()
    if "||" not in group:
        raise ValueError(f"Invalid acquisition group: {group!r}")
    priority, route = group.split("||", 1)
    priority = clean_group_component(priority)
    route = clean_group_component(route)
    if not priority or not route:
        raise ValueError(f"Invalid acquisition group: {group!r}")
    return FULL_TEXT_DIR / priority / route

def prepare_directories(groups: list[str] | None = None) -> None:
    METADATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    for group in groups or []:
        base = group_directory(group)
        for subdirectory in ("pdf", "html", "xml", "supplementary"):
            (base / subdirectory).mkdir(parents=True, exist_ok=True)

# ============================================================================
# CONFIGURATION
# ============================================================================

REQUEST_TIMEOUT = 30

# A URL is never allowed to hang forever.
MAX_RETRIES_PER_URL = 5
INITIAL_RETRY_DELAY = 5
MAX_RETRY_DELAY = 120

RATE_LIMIT_SECONDS = 0.5
MAX_SUPPLEMENTARY_FILES = 100
ARTICLE_HTML_MIN_TEXT = 1200

PERMANENT_HTTP_CODES = {
    400,
    401,
    403,
    404,
    405,
    410,
    451,
}

TRANSIENT_HTTP_CODES = {
    408,
    425,
    429,
    500,
    502,
    503,
    504,
    507,
    509,
    520,
    521,
    522,
    523,
    524,
}

USER_AGENT = (
    "Chapter13-Phytochemical-Target-Review/"
    "1.1 "
    "(full-text acquisition; reproducible research)"
)


# ============================================================================
# LOGGING
# ============================================================================

def configure_logging() -> logging.Logger:
    """Configure the persistent append-only text log and console logging."""

    LOG_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    logger = logging.getLogger("download_full_text")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.propagate = False

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.FileHandler(
        TEXT_LOG_PATH,
        mode="a",
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger


LOGGER = configure_logging()


# ============================================================================
# DATA STRUCTURES
# ============================================================================

@dataclass
class DownloadResult:
    pmid: str
    title: str
    acquisition_group: str
    status: str
    article_status: str
    pdf_path: str
    html_path: str
    xml_path: str
    supplementary_count: int
    sources_attempted: str
    successful_source: str
    failure_reason: str
    timestamp: str


# ============================================================================
# GENERAL UTILITIES
# ============================================================================

def utc_now() -> str:
    """Return a UTC timestamp."""

    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def clean_identifier(value: object) -> str:
    """Convert an identifier safely to text."""

    if value is None:
        return ""

    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass

    text = str(value).strip()

    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]

    return text


def clean_doi(value: object) -> str:
    """Normalize a DOI."""

    doi = clean_identifier(value)

    doi = re.sub(
        r"^https?://(?:dx\.)?doi\.org/",
        "",
        doi,
        flags=re.IGNORECASE,
    )

    return doi.strip()


def clean_pmcid(value: object) -> str:
    """Normalize a PMCID."""

    pmcid = clean_identifier(value)

    if not pmcid:
        return ""

    return pmcid.upper()


def safe_filename(value: str) -> str:
    """Make a filename safe for the local filesystem."""

    value = str(value).strip()

    value = re.sub(
        r"[<>:\"/\\|?*\x00-\x1f]",
        "_",
        value,
    )

    value = value.strip(". ")

    if not value:
        return "artifact"

    return value[:180]


def extension_from_content_type(content_type: str) -> str:
    """Return a useful extension from a MIME content type."""

    content_type = (
        content_type.split(";", 1)[0].strip().lower()
    )

    mapping = {
        "application/pdf": ".pdf",
        "application/xml": ".xml",
        "text/xml": ".xml",
        "text/html": ".html",
        "application/zip": ".zip",
        "application/msword": ".doc",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "application/vnd.ms-excel": ".xls",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
        "text/plain": ".txt",
        "text/csv": ".csv",
    }

    return mapping.get(content_type, ".bin")


# ============================================================================
# HTTP SESSION
# ============================================================================

def create_session() -> requests.Session:
    """Create a requests session with urllib3 retries disabled."""

    session = requests.Session()

    adapter = HTTPAdapter(max_retries=0)

    session.mount("https://", adapter)
    session.mount("http://", adapter)

    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": (
                "application/pdf,"
                "application/xml,"
                "text/xml,"
                "text/html,"
                "application/json,"
                "*/*"
            ),
        }
    )

    return session


# ============================================================================
# NETWORK CLASSIFICATION
# ============================================================================

def classify_request_exception(error: Exception) -> str:
    """
    Classify a requests exception.

    Returns one of:
        SSL_PERMANENT
        TRANSIENT
        PERMANENT
    """

    if isinstance(error, requests.exceptions.SSLError):
        text = str(error).lower()

        if (
            "certificate verify failed" in text
            or "certificateverificationerror" in text
            or "unable to get local issuer certificate" in text
            or "self signed certificate" in text
            or "hostname mismatch" in text
        ):
            return "SSL_PERMANENT"

        # Other SSL failures may be temporary protocol/network failures.
        return "TRANSIENT"

    if isinstance(
        error,
        (
            requests.exceptions.Timeout,
            requests.exceptions.ConnectionError,
        ),
    ):
        return "TRANSIENT"

    return "PERMANENT"


def retry_delay(
    attempt: int,
    response: requests.Response | None = None,
) -> int:
    """Calculate capped exponential backoff, respecting Retry-After."""

    if response is not None:
        retry_after = response.headers.get("Retry-After")

        if retry_after:
            try:
                seconds = int(retry_after)
                return max(1, min(seconds, MAX_RETRY_DELAY))
            except ValueError:
                pass

    delay = INITIAL_RETRY_DELAY * (2 ** max(0, attempt - 1))

    return min(delay, MAX_RETRY_DELAY)


# ============================================================================
# HTTP REQUEST WITH CAPPED RETRY
# ============================================================================

def request_with_retry(
    session: requests.Session,
    url: str,
) -> tuple[requests.Response | None, str]:
    """
    Request one URL without allowing it to block the whole acquisition run.

    Permanent failures, certificate-verification failures, and exhausted
    transient retries immediately return control to the caller so the next
    acquisition route can be attempted.
    """

    for attempt in range(1, MAX_RETRIES_PER_URL + 1):
        try:
            LOGGER.info(
                "Requesting %s (attempt %d/%d)",
                url,
                attempt,
                MAX_RETRIES_PER_URL,
            )

            response = session.get(
                url,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=True,
            )

            status = response.status_code

            if 200 <= status < 300:
                return response, "SUCCESS"

            if status in PERMANENT_HTTP_CODES:
                LOGGER.warning(
                    "Permanent HTTP error %s for %s. Moving to next route.",
                    status,
                    url,
                )
                return response, f"PERMANENT_HTTP_{status}"

            if status in TRANSIENT_HTTP_CODES or status >= 500:
                if attempt >= MAX_RETRIES_PER_URL:
                    LOGGER.warning(
                        "Transient HTTP error %s for %s after %d attempts. "
                        "Moving to next route.",
                        status,
                        url,
                        attempt,
                    )
                    return response, f"RETRY_EXHAUSTED_HTTP_{status}"

                delay = retry_delay(attempt, response)

                LOGGER.warning(
                    "Transient HTTP error %s for %s. "
                    "Retrying in %s seconds...",
                    status,
                    url,
                    delay,
                )

                time.sleep(delay)
                continue

            if 400 <= status < 500:
                LOGGER.warning(
                    "Permanent HTTP error %s for %s. Moving to next route.",
                    status,
                    url,
                )
                return response, f"PERMANENT_HTTP_{status}"

            LOGGER.warning(
                "Unexpected HTTP status %s for %s. Moving to next route.",
                status,
                url,
            )
            return response, f"UNEXPECTED_HTTP_{status}"

        except requests.RequestException as error:
            classification = classify_request_exception(error)

            if classification == "SSL_PERMANENT":
                LOGGER.warning(
                    "SSL certificate failure for %s: %s. "
                    "NOT retrying this URL.",
                    url,
                    error,
                )
                return None, "SSL_CERTIFICATE_ERROR"

            if classification == "TRANSIENT":
                if attempt >= MAX_RETRIES_PER_URL:
                    LOGGER.warning(
                        "Transient connection failure for %s after %d attempts: %s. "
                        "Moving to next route.",
                        url,
                        attempt,
                        error,
                    )
                    return None, "RETRY_EXHAUSTED_CONNECTION"

                delay = retry_delay(attempt)

                LOGGER.warning(
                    "Transient connection error for %s: %s. "
                    "Retrying in %s seconds...",
                    url,
                    error,
                    delay,
                )

                time.sleep(delay)
                continue

            LOGGER.warning(
                "Non-retryable request error for %s: %s",
                url,
                error,
            )
            return None, f"REQUEST_ERROR: {error}"

        except Exception as error:
            LOGGER.exception(
                "Unexpected request error for %s",
                url,
            )
            return None, f"UNEXPECTED_ERROR: {error}"

    return None, "RETRY_EXHAUSTED"


# ============================================================================
# CONTENT DETECTION
# ============================================================================

def detect_file_type(
    content: bytes,
    content_type: str,
    url: str,
) -> str:
    """Detect PDF/XML/HTML using content before URL/MIME fallbacks."""

    leading = content[:1000].lstrip().lower()
    content_type = (content_type or "").lower()
    path_suffix = Path(urlparse(url).path).suffix.lower()

    if content.startswith(b"%PDF"):
        return "PDF"

    if content.startswith(b"PK\x03\x04"):
        return "ZIP"

    if content.startswith(b"\x1f\x8b"):
        return "ARCHIVE"

    if (
        leading.startswith(b"<?xml")
        or leading.startswith(b"<article")
        or "xml" in content_type
    ):
        return "XML"

    if (
        b"<html" in leading
        or b"<!doctype html" in leading
        or "text/html" in content_type
    ):
        return "HTML"

    if path_suffix == ".pdf":
        return "PDF"

    if path_suffix in {".xml", ".nxml"}:
        return "XML"

    if path_suffix in {".html", ".htm"}:
        return "HTML"

    return "BINARY"


# ============================================================================
# CONTENT VALIDATION
# ============================================================================

def validate_pdf(content: bytes) -> tuple[bool, str]:
    if not content:
        return False, "zero-byte response"

    if not content.startswith(b"%PDF"):
        return False, "invalid PDF signature"

    if b"%%EOF" not in content:
        return False, "PDF EOF marker missing"

    return True, ""


def validate_xml(content: bytes) -> tuple[bool, str]:
    if not content:
        return False, "zero-byte response"

    try:
        root = etree.fromstring(content)
    except Exception as error:
        return False, f"invalid XML: {error}"

    if not isinstance(root.tag, str):
        return False, "XML root tag is not a normal element"

    try:
        root_name = etree.QName(root).localname.lower()
    except (TypeError, ValueError):
        return False, "XML root QName could not be parsed"

    body = root.xpath("//*[local-name()='body']")

    if root_name != "article" and not body:
        return False, "XML does not appear to contain an article body"

    return True, ""


def html_text(content: bytes) -> str:
    soup = BeautifulSoup(content, "html.parser")

    for element in soup(["script", "style", "noscript", "svg"]):
        element.decompose()

    return soup.get_text(" ", strip=True)


def validate_html(
    content: bytes,
    *,
    require_article: bool = True,
) -> tuple[bool, str]:
    if not content:
        return False, "zero-byte response"

    soup = BeautifulSoup(content, "html.parser")

    if soup.find("html") is None:
        return False, "HTML document has no html element"

    text = html_text(content)

    if len(text) < ARTICLE_HTML_MIN_TEXT:
        return False, f"HTML text too short ({len(text)} characters)"

    if not require_article:
        return True, ""

    lower_text = text.lower()

    section_terms = (
        "abstract",
        "introduction",
        "methods",
        "materials and methods",
        "results",
        "discussion",
        "references",
    )

    matched = sum(term in lower_text for term in section_terms)

    if matched < 2:
        return False, (
            "HTML appears to be a landing/abstract page rather than "
            "a full article"
        )

    return True, ""


def validate_article_content(
    content: bytes,
    file_type: str,
) -> tuple[bool, str]:
    if file_type == "PDF":
        return validate_pdf(content)

    if file_type == "XML":
        return validate_xml(content)

    if file_type == "HTML":
        return validate_html(content, require_article=True)

    return False, f"unsupported article type: {file_type}"


# ============================================================================
# FILE WRITING / VALIDATION
# ============================================================================

def write_file(path: Path, content: bytes) -> None:
    """Write atomically so an interrupted write cannot masquerade as success."""

    path.parent.mkdir(parents=True, exist_ok=True)

    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_bytes(content)
    temporary.replace(path)


def validate_saved_file(path: Path) -> bool:
    if not path.exists() or not path.is_file():
        return False

    if path.stat().st_size == 0:
        return False

    content = path.read_bytes()
    file_type = detect_file_type(content, "", str(path))

    valid, _ = validate_article_content(content, file_type)
    return valid


def find_valid_article_artifact(
    pmid: str,
    group: str,
) -> tuple[str, Path] | None:
    """Find an already-valid article file for a PMID."""

    group_directory = GROUP_DIRECTORIES[group]

    candidates = (
        ("PDF", group_directory / "pdf" / f"{pmid}.pdf"),
        ("HTML", group_directory / "html" / f"{pmid}.html"),
        ("XML", group_directory / "xml" / f"{pmid}.xml"),
    )

    for file_type, path in candidates:
        if validate_saved_file(path):
            return file_type, path

    return None


# ============================================================================
# URL DISCOVERY
# ============================================================================

def article_urls(row: pd.Series) -> list[tuple[str, str, str]]:
    """Return fast primary article routes, with PDF first whenever PMCID exists."""
    pmid = clean_identifier(row.get("_PMID", row.get("PMID")))
    pmcid = clean_pmcid(row.get("_PMCID", row.get("PMCID")))
    doi = clean_doi(row.get("_DOI", row.get("DOI")))
    candidates: list[tuple[str, str, str]] = []
    if pmcid:
        candidates.extend([
            (f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/pdf/", "PMC", "PDF"),
            (f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML", "Europe PMC", "XML"),
            (f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/", "PMC", "HTML"),
        ])
    if pmid:
        candidates.append((f"https://www.ebi.ac.uk/europepmc/webservices/rest/MED/{pmid}/fullTextXML", "Europe PMC", "XML"))
    if doi:
        candidates.append((f"https://doi.org/{doi}", "Publisher", "AUTO"))
    seen: set[str] = set(); unique=[]
    for url, source, preferred_type in candidates:
        if url.casefold() not in seen:
            seen.add(url.casefold()); unique.append((url, source, preferred_type))
    return unique


# ============================================================================
# CROSSREF DISCOVERY
# ============================================================================

def discover_crossref_links(
    session: requests.Session,
    doi: str,
) -> list[tuple[str, str, str]]:
    if not doi:
        return []

    response, status = request_with_retry(
        session,
        f"https://api.crossref.org/works/{doi}",
    )

    if response is None or status != "SUCCESS":
        return []

    try:
        message = response.json().get("message", {})
    except Exception:
        return []

    candidates: list[tuple[str, str, str]] = []

    for link in message.get("link", []) or []:
        link_url = link.get("URL")
        content_type = str(link.get("content-type", "")).lower()

        if not link_url:
            continue

        if "pdf" in content_type:
            candidates.append((link_url, "CrossRef", "PDF"))
        elif "html" in content_type:
            candidates.append((link_url, "CrossRef", "HTML"))

    return candidates


# ============================================================================
# SUPPLEMENTARY DISCOVERY
# ============================================================================

SUPPLEMENTARY_MARKERS = (
    "supplement",
    "supplementary",
    "supporting",
    "supporting information",
    "appendix",
    "additional file",
    "additional data",
    "dataset",
    "table s",
    "figure s",
)


def looks_supplementary(url: str, text: str) -> bool:
    path = urlparse(url).path.lower()
    lower_text = text.lower()
    suffix = Path(path).suffix.lower()

    known_extensions = {
        ".pdf",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".csv",
        ".tsv",
        ".txt",
        ".zip",
        ".gz",
        ".tar",
        ".tgz",
        ".xml",
        ".jpg",
        ".jpeg",
        ".png",
        ".tif",
        ".tiff",
    }

    if suffix in known_extensions:
        return True

    return any(
        marker in path or marker in lower_text
        for marker in SUPPLEMENTARY_MARKERS
    )


def discover_supplementary(
    content: bytes,
    base_url: str,
    file_type: str,
) -> list[str]:
    links: list[str] = []

    if file_type == "HTML":
        soup = BeautifulSoup(content, "html.parser")

        for anchor in soup.find_all("a", href=True):
            href = anchor.get("href")
            text = anchor.get_text(" ", strip=True)
            url = urljoin(base_url, href)

            if looks_supplementary(url, text):
                links.append(url)

    elif file_type == "XML":
        try:
            root = etree.fromstring(content)
            hrefs = root.xpath(
                "//*[local-name()='ext-link' or local-name()='link']"
                "/@*[local-name()='href']"
            )

            for href in hrefs:
                url = urljoin(base_url, str(href))
                if looks_supplementary(url, ""):
                    links.append(url)
        except Exception:
            return []

    unique: list[str] = []
    seen: set[str] = set()

    for url in links:
        if url in seen:
            continue

        seen.add(url)
        unique.append(url)

        if len(unique) >= MAX_SUPPLEMENTARY_FILES:
            break

    return unique


# ============================================================================
# SUPPLEMENTARY DOWNLOAD
# ============================================================================

def download_supplementary(
    session: requests.Session,
    url: str,
    destination_directory: Path,
    pmid: str,
    index: int,
) -> bool:
    """Download one supplementary file; failure never blocks the article."""

    response, status = request_with_retry(session, url)

    if response is None or status != "SUCCESS":
        LOGGER.warning(
            "Supplementary file unavailable for PMID %s: %s [%s]",
            pmid,
            url,
            status,
        )
        return False

    content = response.content

    if not content:
        LOGGER.warning(
            "Supplementary file was empty for PMID %s: %s",
            pmid,
            url,
        )
        return False

    content_type = response.headers.get("Content-Type", "")

    filename = Path(urlparse(response.url).path).name
    filename = safe_filename(filename)

    if not filename or filename == "artifact":
        filename = (
            f"{pmid}_supplementary_{index}"
            f"{extension_from_content_type(content_type)}"
        )

    destination = destination_directory / f"{pmid}_{filename}"

    if destination.exists():
        # Do not create endless duplicate copies on resumed runs.
        if destination.stat().st_size > 0:
            return True

        destination.unlink(missing_ok=True)

    try:
        write_file(destination, content)
    except Exception as error:
        LOGGER.warning(
            "Could not save supplementary file for PMID %s: %s",
            pmid,
            error,
        )
        return False

    if destination.stat().st_size == 0:
        destination.unlink(missing_ok=True)
        return False

    return True


# ============================================================================
# TEXT-LOG RESUME STATE
# ============================================================================

SUCCESS_RE = re.compile(
    r"SUCCESS:\s*PMID\s+(\d+)\s*->\s*(PDF|HTML|XML)",
    flags=re.IGNORECASE,
)

PROCESSING_RE = re.compile(
    r"(?:Processing|Retrieving)\s+PMID\s+(\d+)",
    flags=re.IGNORECASE,
)

ARTICLE_RESULT_COMPLETED_RE = re.compile(
    r"ARTICLE_RESULT\s*\|\s*PMID=(\d+)\s*\|\s*STATUS=COMPLETED",
    flags=re.IGNORECASE,
)

ARTICLE_RESULT_FAILED_RE = re.compile(
    r"ARTICLE_RESULT\s*\|\s*PMID=(\d+)\s*\|\s*STATUS=FAILED",
    flags=re.IGNORECASE,
)


def parse_text_log_progress(
    path: Path,
) -> tuple[set[str], set[str], set[str]]:
    """
    Parse the persistent text log.

    Returns:
        successful_pmids:
            PMIDs for which the log contains a success indication.

        failed_pmids:
            PMIDs whose latest terminal result is FAILED.

        processed_pmids:
            PMIDs that have appeared in the log.

    IMPORTANT:
        A PMID is never considered completed from the text log alone.
        The article file must also exist and pass validation.

    The parser understands both the older log format:

        SUCCESS: PMID 123456 -> PDF

    and the newer explicit terminal format:

        ARTICLE_RESULT | PMID=123456 | STATUS=COMPLETED ...

        ARTICLE_RESULT | PMID=123456 | STATUS=FAILED ...
    """

    successful: set[str] = set()
    failed: set[str] = set()
    processed: set[str] = set()

    if not path.exists():
        return successful, failed, processed

    try:
        with path.open(
            "r",
            encoding="utf-8",
            errors="replace",
        ) as handle:

            for line in handle:

                processing_match = PROCESSING_RE.search(line)

                if processing_match:
                    processed.add(
                        processing_match.group(1)
                    )

                success_match = SUCCESS_RE.search(line)

                if success_match:
                    pmid = success_match.group(1)

                    successful.add(pmid)
                    processed.add(pmid)

                completed_match = ARTICLE_RESULT_COMPLETED_RE.search(line)

                if completed_match:
                    pmid = completed_match.group(1)

                    successful.add(pmid)
                    processed.add(pmid)

                    # A later COMPLETED result supersedes an earlier FAILED
                    # result for resume purposes.
                    failed.discard(pmid)

                failed_match = ARTICLE_RESULT_FAILED_RE.search(line)

                if failed_match:
                    pmid = failed_match.group(1)

                    failed.add(pmid)
                    processed.add(pmid)

                    # A later FAILED result supersedes an earlier success
                    # indication in the text log. The actual file validation
                    # below remains authoritative.
                    successful.discard(pmid)

    except OSError as error:

        LOGGER.warning(
            "Could not read text resume log %s: %s",
            path,
            error,
        )

    return successful, failed, processed


def validated_artifact_pmids() -> set[str]:
    """Validate article files anywhere below full_text/. This preserves the 310
    papers already downloaded by the slow run and prevents redownloads."""
    completed=set()
    if not FULL_TEXT_DIR.exists(): return completed
    for suffix, file_type in ((".pdf","PDF"),(".html","HTML"),(".xml","XML")):
        for path in FULL_TEXT_DIR.rglob(f"*{suffix}"):
            if path.stem.isdigit() and validate_saved_file(path):
                completed.add(path.stem)
    return completed

def parse_text_log_progress(path: Path) -> tuple[set[str], set[str], set[str]]:
    successful=set(); failed=set(); processed=set()
    if not path.exists(): return successful, failed, processed
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            m=PROCESSING_RE.search(line)
            if m: processed.add(m.group(1))
            m=SUCCESS_RE.search(line)
            if m: successful.add(m.group(1)); processed.add(m.group(1))
            m=ARTICLE_RESULT_COMPLETED_RE.search(line)
            if m: successful.add(m.group(1)); processed.add(m.group(1)); failed.discard(m.group(1))
            m=ARTICLE_RESULT_FAILED_RE.search(line)
            if m: failed.add(m.group(1)); processed.add(m.group(1)); successful.discard(m.group(1))
    except OSError as error: LOGGER.warning("Could not read resume log: %s", error)
    return successful, failed, processed

def load_resume_state() -> tuple[set[str], set[str], set[str]]:
    log_successful, log_failed, processed = parse_text_log_progress(TEXT_LOG_PATH)
    disk_completed = validated_artifact_pmids()
    completed=set(disk_completed)
    failed={p for p in log_failed if p not in completed}
    return completed, failed, processed


# ============================================================================
# METADATA LOADING
# ============================================================================

def find_metadata_queue() -> Path:
    path = METADATA_DIR / "Chapter13_Metadata_Screened" / "Chapter13_Metadata_Screened_FINAL.xlsx"
    if path.exists():
        return path
    raise FileNotFoundError(f"Required metadata-screened workbook not found: {path}")

def normalize_columns(dataframe: pd.DataFrame) -> pd.DataFrame:
    dataframe = dataframe.copy()
    dataframe.rename(columns={c: re.sub(r"[^a-z0-9]", "", str(c).strip().lower()) for c in dataframe.columns}, inplace=True)
    return dataframe

def get_column(dataframe: pd.DataFrame, *names: str) -> str | None:
    for name in names:
        normalized = re.sub(r"[^a-z0-9]", "", name.lower())
        if normalized in dataframe.columns:
            return normalized
    return None

def metadata_decision(row: pd.Series) -> str:
    value = clean_identifier(row.get("metadatadecision", "")).upper()
    if value == "RETAIN":
        return "INCLUDE"
    return value

def determine_group(row: pd.Series) -> str | None:
    decision = metadata_decision(row)
    if decision not in {"INCLUDE", "REVIEW"}:
        return None
    priority = clean_identifier(row.get("acquisitionpriority", "")).upper()
    route = clean_identifier(row.get("screeningroute", "")).upper()
    if not priority or not route:
        return None
    return f"{priority}||{route}"

def load_queue(metadata_path: Path) -> pd.DataFrame:
    LOGGER.info("Loading metadata queue: %s", metadata_path)
    dataframe = normalize_columns(pd.read_excel(metadata_path, dtype=object))
    pmid_column = get_column(dataframe, "PMID", "PubMed ID", "PubMedID")
    if pmid_column is None:
        raise ValueError("Metadata file does not contain a PMID column.")
    dataframe["_PMID"] = dataframe[pmid_column].map(clean_identifier)
    dataframe = dataframe.loc[dataframe["_PMID"].ne("")].copy()
    pmcid_column = get_column(dataframe, "PMCID", "PMC ID")
    doi_column = get_column(dataframe, "DOI")
    title_column = get_column(dataframe, "Title", "Article Title")
    dataframe["_PMCID"] = dataframe[pmcid_column].map(clean_pmcid) if pmcid_column else ""
    dataframe["_DOI"] = dataframe[doi_column].map(clean_doi) if doi_column else ""
    dataframe["_TITLE"] = dataframe[title_column].map(clean_identifier) if title_column else ""
    dataframe["_DECISION"] = dataframe.apply(metadata_decision, axis=1)
    dataframe["_GROUP"] = dataframe.apply(determine_group, axis=1)
    raw = dataframe["_DECISION"].value_counts(dropna=False).to_dict()
    LOGGER.info("Metadata decisions: %s", raw)
    excluded = int((dataframe["_DECISION"] == "EXCLUDE").sum())
    eligible = int(dataframe["_DECISION"].isin({"INCLUDE", "REVIEW"}).sum())
    LOGGER.info("EXCLUDE records blocked from acquisition: %d", excluded)
    LOGGER.info("INCLUDE + REVIEW records eligible for acquisition: %d", eligible)
    bad = dataframe.loc[dataframe["_DECISION"].isin({"INCLUDE", "REVIEW"}) & dataframe["_GROUP"].isna()]
    if not bad.empty:
        raise RuntimeError(f"{len(bad)} eligible records lack Acquisition Priority/Screening Route.")
    return dataframe

# ============================================================================
# ARTICLE SAVING
# ============================================================================

def save_article_artifact(
    content: bytes,
    file_type: str,
    directory: Path,
    pmid: str,
) -> Path | None:
    """Validate and atomically save one canonical article artifact."""

    valid, reason = validate_article_content(content, file_type)

    if not valid:
        LOGGER.warning(
            "Rejected article content for PMID %s: %s",
            pmid,
            reason,
        )
        return None

    suffix = {
        "PDF": ".pdf",
        "HTML": ".html",
        "XML": ".xml",
    }.get(file_type)

    if suffix is None:
        return None

    destination = directory / f"{pmid}{suffix}"

    try:
        write_file(destination, content)
    except Exception as error:
        LOGGER.warning(
            "Could not save %s for PMID %s: %s",
            file_type,
            pmid,
            error,
        )
        return None

    if not validate_saved_file(destination):
        LOGGER.warning(
            "Saved %s failed post-write validation for PMID %s",
            file_type,
            pmid,
        )
        destination.unlink(missing_ok=True)
        return None

    return destination


# ============================================================================
# ONE PMID
# ============================================================================

def process_paper(
    row: pd.Series,
    group: str,
    session: requests.Session,
) -> DownloadResult:
    pmid = clean_identifier(row["_PMID"])
    title = clean_identifier(row["_TITLE"])

    base_directory = group_directory(group)
    pdf_directory = base_directory / "pdf"
    html_directory = base_directory / "html"
    xml_directory = base_directory / "xml"
    supplementary_directory = base_directory / "supplementary"

    LOGGER.info("Processing PMID %s", pmid)

    candidates = article_urls(row)
    doi = clean_doi(row["_DOI"])

    attempted_sources: list[str] = []

    pdf_path = ""
    html_path = ""
    xml_path = ""
    successful_source = ""

    article_content: bytes | None = None
    article_base_url = ""
    article_file_type = ""

    # ----------------------------------------------------------------------
    # Primary acquisition routes
    # ----------------------------------------------------------------------

    for url, source, preferred_type in candidates:
        attempted_sources.append(f"{source}:{preferred_type}")

        response, status = request_with_retry(session, url)

        if response is None or status != "SUCCESS":
            continue

        content = response.content

        file_type = detect_file_type(
            content,
            response.headers.get("Content-Type", ""),
            response.url,
        )

        if preferred_type in {"PDF", "XML", "HTML"} and file_type != preferred_type:
            LOGGER.warning(
                "Expected %s but received %s from %s for PMID %s",
                preferred_type,
                file_type,
                response.url,
                pmid,
            )
            continue

        destination_directory = {
            "PDF": pdf_directory,
            "HTML": html_directory,
            "XML": xml_directory,
        }.get(file_type)

        if destination_directory is None:
            LOGGER.warning(
                "Unsupported article content type %s for PMID %s",
                file_type,
                pmid,
            )
            continue

        destination = save_article_artifact(
            content,
            file_type,
            destination_directory,
            pmid,
        )

        if destination is None:
            continue

        if file_type == "PDF":
            pdf_path = str(destination)
        elif file_type == "HTML":
            html_path = str(destination)
        elif file_type == "XML":
            xml_path = str(destination)

        successful_source = source
        article_content = content
        article_base_url = response.url
        article_file_type = file_type

        LOGGER.info(
            "SUCCESS: PMID %s -> %s via %s",
            pmid,
            file_type,
            source,
        )
        break

    # ----------------------------------------------------------------------
    # CrossRef discovery if primary routes did not yield article
    # ----------------------------------------------------------------------

    if article_content is None and doi:
        LOGGER.info(
            "Primary routes exhausted for PMID %s. Attempting CrossRef discovery.",
            pmid,
        )

        crossref_candidates = discover_crossref_links(session, doi)

        for url, source, preferred_type in crossref_candidates:
            attempted_sources.append(f"{source}:{preferred_type}")

            response, status = request_with_retry(session, url)

            if response is None or status != "SUCCESS":
                continue

            content = response.content

            file_type = detect_file_type(
                content,
                response.headers.get("Content-Type", ""),
                response.url,
            )

            if preferred_type in {"PDF", "HTML"} and file_type != preferred_type:
                LOGGER.warning(
                    "CrossRef expected %s but received %s for PMID %s",
                    preferred_type,
                    file_type,
                    pmid,
                )
                continue

            destination_directory = {
                "PDF": pdf_directory,
                "HTML": html_directory,
                "XML": xml_directory,
            }.get(file_type)

            if destination_directory is None:
                continue

            destination = save_article_artifact(
                content,
                file_type,
                destination_directory,
                pmid,
            )

            if destination is None:
                continue

            if file_type == "PDF":
                pdf_path = str(destination)
            elif file_type == "HTML":
                html_path = str(destination)
            elif file_type == "XML":
                xml_path = str(destination)

            successful_source = source
            article_content = content
            article_base_url = response.url
            article_file_type = file_type

            LOGGER.info(
                "SUCCESS: PMID %s -> %s via %s",
                pmid,
                file_type,
                source,
            )
            break

    # ----------------------------------------------------------------------
    # Supplementary files
    # ----------------------------------------------------------------------

    supplementary_count = 0

    if article_content is not None:
        supplementary_urls = discover_supplementary(
            article_content,
            article_base_url,
            article_file_type,
        )

        for index, url in enumerate(supplementary_urls, start=1):
            try:
                if download_supplementary(
                    session,
                    url,
                    supplementary_directory,
                    pmid,
                    index,
                ):
                    supplementary_count += 1
            except Exception as error:
                # A supplementary failure must never invalidate the article.
                LOGGER.exception(
                    "Unexpected supplementary-file error for PMID %s: %s",
                    pmid,
                    error,
                )

    # ----------------------------------------------------------------------
    # Final status
    # ----------------------------------------------------------------------

    if article_content is not None:
        article_status = (
            "PDF"
            if pdf_path
            else "HTML"
            if html_path
            else "XML"
        )

        return DownloadResult(
            pmid=pmid,
            title=title,
            acquisition_group=group,
            status="COMPLETED",
            article_status=article_status,
            pdf_path=pdf_path,
            html_path=html_path,
            xml_path=xml_path,
            supplementary_count=supplementary_count,
            sources_attempted="; ".join(attempted_sources),
            successful_source=successful_source,
            failure_reason="",
            timestamp=utc_now(),
        )

    return DownloadResult(
        pmid=pmid,
        title=title,
        acquisition_group=group,
        status="FAILED",
        article_status="NONE",
        pdf_path="",
        html_path="",
        xml_path="",
        supplementary_count=0,
        sources_attempted="; ".join(attempted_sources),
        successful_source="",
        failure_reason=(
            "All legitimate article acquisition routes were exhausted "
            "without obtaining a validated PDF, HTML, or XML article."
        ),
        timestamp=utc_now(),
    )


# ============================================================================
# COMMAND-LINE ARGUMENTS
# ============================================================================

def parse_arguments() -> argparse.Namespace:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retry-failed", action="store_true", help="Retry previously failed PMIDs.")
    parser.add_argument("--retry-completed", action="store_true", help="Force redownload even when a validated article exists.")
    parser.add_argument("--limit", type=int, default=None, help="Optional maximum number of pending papers for this run.")
    return parser.parse_args()

def main() -> None:
    arguments=parse_arguments()
    metadata_path=find_metadata_queue()
    metadata=load_queue(metadata_path)
    queue=metadata.loc[metadata["_DECISION"].isin({"INCLUDE","REVIEW"}) & metadata["_GROUP"].notna()].copy()
    assert set(queue["_DECISION"].unique()).issubset({"INCLUDE","REVIEW"})
    groups=sorted(queue["_GROUP"].unique())
    prepare_directories(groups)
    completed, failed, processed=load_resume_state()
    LOGGER.info("FAST RESUMABLE ACQUISITION")
    LOGGER.info("Total metadata records: %d", len(metadata))
    LOGGER.info("Eligible queue: %d", len(queue))
    LOGGER.info("Groups: %d", len(groups))
    LOGGER.info("Validated articles already on disk (all layouts): %d", len(completed))
    LOGGER.info("Resume log: %s", TEXT_LOG_PATH)
    session=create_session(); session_completed=session_failed=session_skipped=0
    try:
        for group in groups:
            gq=queue.loc[queue["_GROUP"].eq(group)].copy()
            pending=[]
            for _,row in gq.iterrows():
                pmid=clean_identifier(row["_PMID"])
                if not pmid: continue
                if pmid in completed and not arguments.retry_completed: session_skipped+=1; continue
                if pmid in failed and not arguments.retry_failed and not arguments.retry_completed: session_skipped+=1; continue
                pending.append(row)
            if arguments.limit is not None:
                remaining=arguments.limit-session_completed-session_failed
                if remaining<=0: break
                pending=pending[:remaining]
            LOGGER.info("GROUP %s | total=%d | pending=%d | folder=%s", group, len(gq), len(pending), group_directory(group))
            for _,row in tqdm(pd.DataFrame(pending).iterrows() if pending else [], total=len(pending), desc=group):
                pmid=clean_identifier(row["_PMID"])
                if pmid in completed and not arguments.retry_completed: session_skipped+=1; continue
                try:
                    result=process_paper(row, group, session)
                except Exception as error:
                    LOGGER.exception("Unexpected article-level error for PMID %s", pmid)
                    result=DownloadResult(pmid=pmid,title=clean_identifier(row["_TITLE"]),acquisition_group=group,status="FAILED",article_status="NONE",pdf_path="",html_path="",xml_path="",supplementary_count=0,sources_attempted="",successful_source="",failure_reason=f"Unexpected article-level error: {error}",timestamp=utc_now())
                if result.status=="COMPLETED":
                    completed.add(pmid); failed.discard(pmid); processed.add(pmid); session_completed+=1
                    LOGGER.info("ARTICLE_RESULT | PMID=%s | STATUS=COMPLETED | TYPE=%s | GROUP=%s | SUPPLEMENTARY=%d",pmid,result.article_status,group,result.supplementary_count)
                else:
                    failed.add(pmid); processed.add(pmid); session_failed+=1
                    LOGGER.warning("ARTICLE_RESULT | PMID=%s | STATUS=FAILED | GROUP=%s | REASON=%s",pmid,group,result.failure_reason)
                time.sleep(RATE_LIMIT_SECONDS)
    finally: session.close()
    final_completed,final_failed,final_processed=load_resume_state()
    LOGGER.info("FINISHED | completed_this_run=%d failed_this_run=%d skipped=%d validated_on_disk=%d failed_state=%d",session_completed,session_failed,session_skipped,len(final_completed),len(final_failed))

if __name__ == "__main__":
    main()
