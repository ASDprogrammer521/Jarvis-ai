from __future__ import annotations


def create_presentation(parameters: dict, player=None, speak=None) -> str:
    from actions import _impl_ppt as impl
    return impl.create_presentation(parameters, player, speak)


TOOL = {'name': 'create_presentation',
 'description': 'Builds a complete PowerPoint (.pptx) deck from a topic: title slide, structured body slides '
                '(bullets, two-column, comparison, process and timeline diagrams, stats, quotes), speaker notes and '
                'a closing slide. Use when the user asks for a presentation, slides, a deck or a PowerPoint.',
 'parameters': {'type': 'OBJECT',
                'properties': {'topic': {'type': 'STRING', 'description': 'What the presentation is about'},
                               'slide_count': {'type': 'INTEGER',
                                               'description': 'Total slides including title and closing (3-20, '
                                                              'default 8)'},
                               'style': {'type': 'STRING',
                                         'description': 'midnight | ocean | sunset | forest | mono | aurora'},
                               'audience': {'type': 'STRING', 'description': 'Who it is for'},
                               'language': {'type': 'STRING', 'description': 'Language of the slides'},
                               'instructions': {'type': 'STRING', 'description': 'Any extra requirements'},
                               'filename': {'type': 'STRING', 'description': 'Optional file name'},
                               'open_after': {'type': 'BOOLEAN',
                                              'description': 'Open the file when done (default true)'}},
                'required': ['topic']}}
TOOL["handler"] = create_presentation

# by ASDcuber521
