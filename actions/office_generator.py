from __future__ import annotations


def generate_spreadsheet(parameters: dict, player=None, speak=None) -> str:
    from actions import _impl_office_gen as impl
    return impl.generate_spreadsheet(parameters, player, speak)


TOOL = {'name': 'generate_spreadsheet',
 'description': 'Designs and creates a complete Excel (.xlsx) spreadsheet from a plain-language description: '
                'budgets, expense or habit trackers, invoices, grade books, schedules, inventories, project plans, '
                'financial reports. Includes working formulas, totals, formatting and charts. Use when the user '
                'describes what they want a spreadsheet for.',
 'parameters': {'type': 'OBJECT',
                'properties': {'description': {'type': 'STRING',
                                               'description': 'What the spreadsheet is for and what it must contain'},
                               'theme': {'type': 'STRING', 'description': 'blue | green | dark | mono | sunset'},
                               'language': {'type': 'STRING', 'description': 'Language of labels'},
                               'filename': {'type': 'STRING', 'description': 'Optional file name'},
                               'open_after': {'type': 'BOOLEAN',
                                              'description': 'Open the file when done (default true)'}},
                'required': ['description']}}
TOOL["handler"] = generate_spreadsheet

# by ASDcuber521
