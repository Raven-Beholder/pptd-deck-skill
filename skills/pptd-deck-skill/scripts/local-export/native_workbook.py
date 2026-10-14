"""Small editable chart-data workbook, written from normalized cells.

No spreadsheet engine, macros, formulas or external links are generated.
"""
from io import BytesIO
from native_common import NS, NativeExportError, node, xstring
from native_package import Package, opc_xml

TYPE = 'application/vnd.openxmlformats-officedocument.spreadsheetml.'


def column_name(index):
    if not isinstance(index, int) or not 0 <= index < 16384:
        raise NativeExportError('workbook column outside A–XFD')
    result = ''
    index += 1
    while index:
        index, digit = divmod(index - 1, 26)
        result = chr(65 + digit) + result
    return result


def number_text(value):
    return str(value)


def formula(column, count, header=False):
    letter = column_name(column)
    return f"'Data'!${letter}$1" if header else f"'Data'!${letter}$2:${letter}${count + 1}"


def workbook(data):
    package = Package()
    root = node('s:workbook')
    rid = package.relate('xl/workbook.xml', 'worksheets/sheet1.xml', 'worksheet')
    node('s:sheet', node('s:sheets', root), name='Data', sheetId=1, **{'r:id': rid})
    package.add('xl/workbook.xml', opc_xml(root, NS['s']), TYPE + 'sheet.main+xml')
    package.relate('', 'xl/workbook.xml', 'officeDocument')
    sheet = node('s:worksheet')
    node('s:dimension', sheet, ref=f"A1:{column_name(len(data['cols']) - 1)}{len(data['rows']) + 1}")
    items = node('s:sheetData', sheet)
    for row_index, values in enumerate([data['cols'], *data['rows']], 1):
        row = node('s:row', items, r=row_index)
        for column, value in enumerate(values):
            if value is None:
                continue
            ref = column_name(column) + str(row_index)
            if isinstance(value, str):
                if len(value) > 32767:
                    raise NativeExportError('chart workbook string exceeds Excel 32767 character limit')
                cell = node('s:c', row, r=ref, t='inlineStr')
                text = node('s:t', node('s:is', cell), text=xstring(value))
                if value != value.strip():
                    # Microsoft documents xml:space on SpreadsheetML Text.
                    # It is needed only for significant boundary whitespace.
                    text.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
            else:
                node('s:v', node('s:c', row, r=ref), text=number_text(value))
    package.add('xl/worksheets/sheet1.xml', opc_xml(sheet, NS['s']), TYPE + 'worksheet+xml')
    output = BytesIO()
    package.write(output)
    return output.getvalue()
