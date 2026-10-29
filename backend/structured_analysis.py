"""Inspect the Responses envelope before attempting to validate its JSON payload."""

import json
from copy import deepcopy

from .analysis_errors import ResponseProblem


def source_schema(schema, references, source_quotes=None):
    """Constrain every reference at the provider boundary, not just in prose."""
    result = deepcopy(schema.model_json_schema())
    def visit(node):
        if isinstance(node, dict):
            properties = node.get('properties', {})
            if 'publication_id' in properties:
                properties['publication_id']['enum'] = list(references)
            if 'publication_ids' in properties:
                properties['publication_ids']['items']['enum'] = list(references)
            for child in node.values():
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)
    visit(result)
    if source_quotes:
        evidence = result['$defs']['Evidence']
        variants = []
        for reference, quotes in source_quotes.items():
            variant = deepcopy(evidence)
            variant['properties']['publication_id']['enum'] = [reference]
            variant['properties']['quote']['enum'] = quotes
            variants.append(variant)
        result['$defs']['Evidence'] = {'anyOf': variants}
    return result


def request_structured(client, *, model, schema, instructions, input_text,
                       references=None, source_quotes=None, raw=False, max_output_tokens=6000):
    response = client.responses.create(
        model=model, store=False, max_output_tokens=max_output_tokens, reasoning={'effort': 'none'},
        instructions=instructions, input=input_text,
        text={'format': {'type': 'json_schema', 'name': schema.__name__,
                         'strict': True, 'schema': source_schema(schema, references, source_quotes) if references else schema.model_json_schema()}})
    # responses.parse parses JSON even for an incomplete envelope in the installed
    # SDK. A truncated response raises before its status can be inspected there.
    if response.status != 'completed':
        reason = getattr(getattr(response, 'incomplete_details', None), 'reason', None)
        raise ResponseProblem('output_truncated' if reason == 'max_output_tokens' else 'output_incomplete')
    if any(getattr(content, 'type', None) == 'refusal'
           for item in response.output for content in (getattr(item, 'content', None) or [])):
        raise ResponseProblem('output_refused')
    if not response.output_text:
        raise ResponseProblem('output_incomplete')
    if raw:
        try:
            return json.loads(response.output_text)
        except (ValueError, TypeError):
            raise ResponseProblem('output_json') from None
    return schema.model_validate_json(response.output_text)


def literal_fragments(text, limit=79):
    """Bounded, exact slices: no ellipses, spelling changes or normalization."""
    fragments = []
    remaining = text.strip()
    while remaining:
        end = min(len(remaining), limit)
        if end < len(remaining):
            boundary = remaining.rfind(' ', 0, end + 1)
            if boundary > 0:
                end = boundary
        fragment = remaining[:end].strip()
        if fragment:
            fragments.append(fragment)
        remaining = remaining[end:].lstrip()
    return list(dict.fromkeys(fragments))
