from __future__ import annotations


def build_spreadsheet(parameters: dict, player=None, speak=None) -> str:
    from actions import _impl_office as impl
    return impl.build_spreadsheet(parameters, player, speak)


TOOL = {'name': 'build_spreadsheet',
 'description': 'Builds a formatted Excel (.xlsx) workbook from structured content or a CSV file: styled headers, '
                "number formats, formulas (cells starting with '=', use {row} for the current row), total rows, "
                'charts, conditional formatting, frozen headers and filters. Use when the user already has the '
                'data/structure; to design a spreadsheet from a description use generate_spreadsheet instead.',
 'parameters': {'type': 'OBJECT',
                'properties': {'spec_json': {'type': 'STRING',
                                             'description': 'JSON: {theme, '
                                                            'sheets:[{name,title,subtitle,columns:[{header,format,width}],rows:[[...]],totals:{label,columns:{"C":"sum"}},charts:[{type,title,data_cols:["C"],cat_col:"A"}],conditional:[{column,rule,value,color}]}]}'},
                               'csv_path': {'type': 'STRING',
                                            'description': 'Path of a CSV file to turn into a formatted workbook'},
                               'title': {'type': 'STRING', 'description': 'Report title'},
                               'theme': {'type': 'STRING', 'description': 'blue | green | dark | mono | sunset'},
                               'filename': {'type': 'STRING', 'description': 'Optional file name'},
                               'open_after': {'type': 'BOOLEAN',
                                              'description': 'Open the file when done (default true)'}}}}
TOOL["handler"] = build_spreadsheet

# by ASDcuber521
