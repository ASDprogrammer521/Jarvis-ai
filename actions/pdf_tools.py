from __future__ import annotations


def pdf_tools(parameters: dict, player=None, speak=None) -> str:
    from actions import _impl_pdf as impl
    return impl.pdf_tools(parameters, player, speak)


TOOL = {'name': 'pdf_tools',
 'description': 'PDF toolkit. Actions: merge (combine several PDFs), split (by page ranges, every N pages, or one '
                'file per page), extract_text (with automatic OCR for scanned pages), ocr (force OCR), '
                'extract_tables (tables to an Excel file), convert (Word/PowerPoint/Excel/text/images to PDF), info '
                '(page count and metadata). Use whenever the user works with PDF files.',
 'parameters': {'type': 'OBJECT',
                'properties': {'action': {'type': 'STRING',
                                          'description': 'merge | split | extract_text | ocr | extract_tables | '
                                                         'convert | info'},
                               'paths': {'type': 'ARRAY',
                                         'items': {'type': 'STRING'},
                                         'description': 'File path(s). merge needs 2+, other actions use the first'},
                               'pages': {'type': 'STRING',
                                         'description': "Page selection like '1-3,5,8-' (extract_text, "
                                                        'extract_tables)'},
                               'ranges': {'type': 'STRING', 'description': "split: groups like '1-3;4-6;7-'"},
                               'every': {'type': 'INTEGER', 'description': 'split: pages per output file'},
                               'ocr': {'type': 'STRING', 'description': 'auto | always | never (extract_text)'},
                               'language': {'type': 'STRING',
                                            'description': "OCR language code(s), e.g. 'eng', 'eng+rus'"},
                               'filename': {'type': 'STRING', 'description': 'Output name for merge'},
                               'open_after': {'type': 'BOOLEAN', 'description': 'Open the result when done'}},
                'required': ['action']}}
TOOL["handler"] = pdf_tools

# by ASDcuber521
