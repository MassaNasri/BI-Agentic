import io
import zipfile

import pytest

from bi_platform_shared import uploads
from bi_platform_shared.uploads import UploadRejected, validate_upload


class Uploaded(io.BytesIO):
    def __init__(self, name, content, size=None):
        super().__init__(content)
        self.name = name
        self.size = len(content) if size is None else size


def test_csv_content_and_name_are_checked():
    assert validate_upload(Uploaded('data.csv', b'a,b\n1,2\n'), 'dataset') == '.csv'
    for name, content in [('../data.csv', b'a,b\n'), ('C:\\data.csv', b'a,b\n'),
                          ('data.csv', b'MZfake'), ('data.exe', b'a,b\n')]:
        with pytest.raises(UploadRejected):
            validate_upload(Uploaded(name, content), 'dataset')


def test_claimed_oversize_is_rejected_before_read():
    with pytest.raises(UploadRejected):
        validate_upload(Uploaded('data.csv', b'a,b\n', 50 * 1024 * 1024 + 1), 'dataset')


def test_zip_bomb_and_malformed_workbook_are_rejected():
    with pytest.raises(UploadRejected):
        validate_upload(Uploaded('data.xlsx', b'PK\x03\x04'), 'dataset')
    memory = io.BytesIO()
    with zipfile.ZipFile(memory, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml', '<Types/>')
        archive.writestr('xl/workbook.xml', '<workbook/>')
        archive.writestr('xl/huge.xml', b'0' * (2 * 1024 * 1024))
    with pytest.raises(UploadRejected):
        validate_upload(Uploaded('data.xlsx', memory.getvalue()), 'dataset')


def test_audio_magic_and_size_are_checked():
    wav = b'RIFF' + b'\x00\x00\x00\x00' + b'WAVEfmt '
    assert validate_upload(Uploaded('voice.wav', wav), 'audio') == '.wav'
    with pytest.raises(UploadRejected):
        validate_upload(Uploaded('voice.wav', b'not audio'), 'audio')
    with pytest.raises(UploadRejected):
        validate_upload(Uploaded('voice.wav', wav, 25 * 1024 * 1024 + 1), 'audio')


def _xlsx_with_member(name, payload=b'x'):
    memory = io.BytesIO()
    with zipfile.ZipFile(memory, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml', '<Types/>')
        archive.writestr('xl/workbook.xml', '<workbook/>')
        archive.writestr(name, payload)
    return memory.getvalue()


def test_well_formed_xlsx_package_and_archive_byte_ceiling():
    memory = io.BytesIO()
    with zipfile.ZipFile(memory, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml',
                         '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                         '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                         '<Default Extension="xml" ContentType="application/xml"/>'
                         '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                         '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                         '</Types>')
        archive.writestr('_rels/.rels',
                         '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                         '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                         '</Relationships>')
        archive.writestr('xl/workbook.xml',
                         '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                         'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                         '<sheets><sheet name="Data" sheetId="1" r:id="rId1"/></sheets></workbook>')
        archive.writestr('xl/_rels/workbook.xml.rels',
                         '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                         '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
                         '</Relationships>')
        archive.writestr('xl/worksheets/sheet1.xml',
                         '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                         '<sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>name</t></is></c>'
                         '<c r="B1" t="inlineStr"><is><t>value</t></is></c></row>'
                         '<row r="2"><c r="A2" t="inlineStr"><is><t>A</t></is></c>'
                         '<c r="B2"><v>1</v></c></row></sheetData></worksheet>')
    content = memory.getvalue()
    assert validate_upload(Uploaded('data.xlsx', content), 'dataset') == '.xlsx'
    with pytest.raises(UploadRejected):
        validate_upload(Uploaded('data.xlsx', content, uploads.DATA_MAX_BYTES + 1), 'dataset')


@pytest.mark.parametrize('member', ['../bad.xml', '..\\bad.xml', '/bad.xml', 'C:/bad.xml'])
def test_xlsx_rejects_unsafe_members(member):
    with pytest.raises(UploadRejected):
        validate_upload(Uploaded('data.xlsx', _xlsx_with_member(member)), 'dataset')


def test_xlsx_rejects_member_count_expansion_and_ratio(monkeypatch):
    content = _xlsx_with_member('xl/worksheets/sheet1.xml', b'0' * (2 * 1024 * 1024))
    with pytest.raises(UploadRejected):
        validate_upload(Uploaded('data.xlsx', content), 'dataset')
    monkeypatch.setattr(uploads, 'ZIP_MAX_RATIO', 10_000)
    monkeypatch.setattr(uploads, 'ZIP_MAX_EXPANDED', 1024)
    with pytest.raises(UploadRejected):
        validate_upload(Uploaded('data.xlsx', content), 'dataset')
    monkeypatch.setattr(uploads, 'ZIP_MAX_EXPANDED', 200 * 1024 * 1024)
    monkeypatch.setattr(uploads, 'ZIP_MAX_MEMBERS', 2)
    with pytest.raises(UploadRejected):
        validate_upload(Uploaded('data.xlsx', content), 'dataset')


@pytest.mark.parametrize('name', ['data\x00.csv', 'data\n.csv', '/tmp/data.csv', 'C:\\data.csv'])
def test_csv_rejects_unsafe_filename(name):
    with pytest.raises(UploadRejected):
        validate_upload(Uploaded(name, b'a,b\n1,2\n'), 'dataset')


def test_csv_rejects_invalid_utf8_and_nul():
    for content in (b'a,b\n\xff,2\n', b'a,b\n1,\x00\n', b'a,b\n1,\x1b\n', b'a,b\n"unterminated,2\n'):
        with pytest.raises(UploadRejected):
            validate_upload(Uploaded('data.csv', content), 'dataset')
