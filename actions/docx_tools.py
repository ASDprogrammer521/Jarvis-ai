from __future__ import annotations


def word_document(parameters: dict, player=None, speak=None) -> str:
    from actions import _impl_docx as impl
    return impl.word_document(parameters, player, speak)


TOOL = {'name': 'word_document',
 'description': 'Creates and edits Word (.docx) documents with real typography: title block, headings, paragraphs, '
                'bullet and numbered lists, formatted tables, quotes, page numbers. Actions: create (from a topic or '
                'structured content), append (add sections to an existing file), replace (find and replace text), '
                'read (return the text). Use for reports, letters, essays, CVs, notes, contracts.',
 'parameters': {'type': 'OBJECT',
                'properties': {'action': {'type': 'STRING',
                                          'description': 'create | append | replace | read (default create)'},
                               'topic': {'type': 'STRING', 'description': 'What to write about (create/append)'},
                               'title': {'type': 'STRING', 'description': 'Document title'},
                               'content_json': {'type': 'STRING',
                                                'description': 'Optional ready-made content: JSON {title, subtitle, '
                                                               'blocks:[...]}'},
                               'path': {'type': 'STRING', 'description': 'Existing .docx path (append/replace/read)'},
                               'find': {'type': 'STRING', 'description': 'Text to find (replace)'},
                               'replace_with': {'type': 'STRING', 'description': 'Replacement text (replace)'},
                               'style': {'type': 'STRING', 'description': 'modern | classic | minimal | bold'},
                               'length': {'type': 'STRING', 'description': "e.g. '1 page', '3 pages'"},
                               'tone': {'type': 'STRING', 'description': 'e.g. formal, friendly'},
                               'language': {'type': 'STRING', 'description': 'Language to write in'},
                               'filename': {'type': 'STRING', 'description': 'Optional file name'},
                               'open_after': {'type': 'BOOLEAN',
                                              'description': 'Open the file when done (default true)'}}}}
TOOL["handler"] = word_document

# by ASDcuber521
