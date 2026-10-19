"""Bounded validation for the active BIAVORA upload formats.

These checks precede any parser or persistent write. The original filename is
metadata only; callers must generate storage names independently.
"""

from pathlib import PurePath
import codecs
import csv
import io
import re
import zipfile


class UploadRejected(ValueError):
    pass


DATA_MAX_BYTES = 50 * 1024 * 1024
AUDIO_MAX_BYTES = 25 * 1024 * 1024
AUDIO_MAX_SECONDS = 600
SQLITE_MAX_BYTES = 100 * 1024 * 1024
MAX_NAME = 128
ZIP_MAX_MEMBERS = 2000
ZIP_MAX_EXPANDED = 200 * 1024 * 1024
ZIP_MAX_RATIO = 100
CSV_MAX_ROWS = 1_000_000
CSV_MAX_COLUMNS = 2048
CSV_MAX_CELL_CHARS = 1024 * 1024
_CSV_CONTROLS = re.compile(rb'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')


def _name_and_extension(uploaded):
    name = str(getattr(uploaded, 'name', '') or '')
    if (not name or len(name) > MAX_NAME or name in {'.', '..'}
            or '/' in name or '\\' in name or ':' in name
            or any(ord(char) < 32 for char in name)):
        raise UploadRejected('Invalid upload filename.')
    return name, PurePath(name).suffix.lower()


def _head(uploaded, length=4096):
    pos = uploaded.tell()
    try:
        uploaded.seek(0)
        return uploaded.read(length)
    finally:
        uploaded.seek(pos)


def _check_zip(uploaded):
    pos = uploaded.tell()
    try:
        uploaded.seek(0)
        uploaded.seek(0, 2)
        if uploaded.tell() > DATA_MAX_BYTES:
            raise UploadRejected('Spreadsheet archive exceeds size limit.')
        uploaded.seek(0)
        with zipfile.ZipFile(uploaded) as archive:
            members = archive.infolist()
            if len(members) > ZIP_MAX_MEMBERS:
                raise UploadRejected('Spreadsheet archive has too many members.')
            expanded = 0
            seen = set()
            for member in members:
                name = member.filename
                parts = name.replace('\\', '/').split('/')
                if (name in seen or name.startswith(('/', '\\')) or ':' in parts[0]
                        or any(part == '..' for part in parts)
                        or any(ord(char) < 32 for char in name)
                        or member.flag_bits & 1
                        or member.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}):
                    raise UploadRejected('Spreadsheet archive contains an unsafe member.')
                seen.add(name)
                expanded += member.file_size
                if (expanded > ZIP_MAX_EXPANDED or member.file_size > ZIP_MAX_EXPANDED
                        or (member.file_size > 1024 * 1024 and
                            member.file_size / max(member.compress_size, 1) > ZIP_MAX_RATIO)):
                    raise UploadRejected('Spreadsheet archive exceeds resource limits.')
            if '[Content_Types].xml' not in archive.namelist() or 'xl/workbook.xml' not in archive.namelist():
                raise UploadRejected('Invalid XLSX workbook.')
    except (zipfile.BadZipFile, EOFError, OSError) as exc:
        raise UploadRejected('Invalid XLSX container.') from exc
    finally:
        uploaded.seek(pos)


def validate_upload(uploaded, category):
    """Return the trusted extension; raise UploadRejected on bad input."""
    _, extension = _name_and_extension(uploaded)
    allowed = {
        'dataset': {'.csv', '.xlsx'},
        'sqlite': {'.db', '.sqlite', '.sqlite3'},
        'audio': {'.wav', '.mp3', '.m4a', '.ogg', '.webm'},
    }
    limit = {'dataset': DATA_MAX_BYTES, 'sqlite': SQLITE_MAX_BYTES, 'audio': AUDIO_MAX_BYTES}
    if category not in allowed:
        raise UploadRejected('Unsupported upload category.')
    if extension not in allowed[category]:
        raise UploadRejected(f"File type '{extension or 'no extension'}' not allowed. Allowed types: {', '.join(sorted(allowed[category]))}.")
    size = int(getattr(uploaded, 'size', 0) or 0)
    if size < 1 or size > limit[category]:
        raise UploadRejected('Upload size is outside the allowed range.')
    head = _head(uploaded)
    if extension == '.csv':
        if b'\x00' in head or head.startswith((b'MZ', b'\x7fELF', b'PK\x03\x04', b'%PDF')):
            raise UploadRejected('CSV content is invalid.')
        try:
            decoder = codecs.getincrementaldecoder('utf-8-sig')()
            uploaded.seek(0)
            actual = 0
            while chunk := uploaded.read(64 * 1024):
                actual += len(chunk)
                if actual > DATA_MAX_BYTES or _CSV_CONTROLS.search(chunk):
                    raise UploadRejected('CSV content is invalid or too large.')
                decoder.decode(chunk)
            decoder.decode(b'', final=True)
            uploaded.seek(0)
            text_stream = io.TextIOWrapper(uploaded, encoding='utf-8-sig', newline='')
            try:
                for row_number, row in enumerate(csv.reader(text_stream, strict=True), 1):
                    if (row_number > CSV_MAX_ROWS or len(row) > CSV_MAX_COLUMNS
                            or any(len(cell) > CSV_MAX_CELL_CHARS for cell in row)):
                        raise UploadRejected('CSV exceeds parser limits.')
            finally:
                text_stream.detach()
        except UnicodeDecodeError as exc:
            raise UploadRejected('CSV must be UTF-8 text.') from exc
        except csv.Error as exc:
            raise UploadRejected('CSV structure is invalid.') from exc
        finally:
            uploaded.seek(0)
    elif extension == '.xlsx':
        if not head.startswith(b'PK\x03\x04'):
            raise UploadRejected('Invalid XLSX signature.')
        _check_zip(uploaded)
    elif category == 'sqlite' and not head.startswith(b'SQLite format 3\x00'):
        raise UploadRejected('Invalid SQLite signature.')
    elif category == 'audio':
        valid = {
            '.wav': head.startswith(b'RIFF') and head[8:12] == b'WAVE',
            '.mp3': head.startswith(b'ID3') or (len(head) > 1 and head[0] == 0xff and head[1] & 0xe0 == 0xe0),
            '.m4a': head[4:8] == b'ftyp',
            '.ogg': head.startswith(b'OggS'),
            '.webm': head.startswith(b'\x1a\x45\xdf\xa3'),
        }
        if not valid[extension]:
            raise UploadRejected('Invalid audio signature.')
    uploaded.seek(0)
    return extension
