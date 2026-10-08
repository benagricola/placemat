"""Original fixed copper and zone-intent forms, without native board reads."""
from pathlib import Path
import re


def protected_forms(path, refuse):
    tokens = re.findall(r'"(?:\\.|[^"\\])*"|[()]|[^\s()]+', Path(path).read_text())
    stack, roots = [], []
    for token in tokens:
        if token == '(':
            node = []
            (stack[-1] if stack else roots).append(node)
            stack.append(node)
        elif token == ')':
            if not stack:
                refuse('malformed board closing token')
            stack.pop()
        elif stack:
            stack[-1].append(token)
        else:
            refuse('board token outside form')
    if stack or len(roots) != 1 or not roots[0] or roots[0][0] != 'kicad_pcb':
        refuse('malformed board root')
    def frozen(value):
        return tuple(frozen(v) if isinstance(v, list) else v for v in value)
    fixed, zones = [], []
    for node in roots[0]:
        if not isinstance(node, list) or not node:
            continue
        if type(node[0]) is not str:
            refuse('malformed board form head')
        if node[0] in ('segment', 'arc', 'via') or node[0].startswith('gr_'):
            fixed.append(frozen(node))
        elif node[0] == 'zone':
            definition = []
            for value in node:
                if isinstance(value, list) and value:
                    if value[0] in ('filled_polygon', 'fill_segments'):
                        continue
                    # KiCad's direct zone fill yes atom is derived m_isFilled
                    # state. Retain every fill parameter and unknown token;
                    # graphic fills and nested yes atoms are not normalized.
                    if value[0] == 'fill' and len(value) > 1 and value[1] == 'yes':
                        value = [value[0], *value[2:]]
                definition.append(value)
            zones.append(frozen(definition))
    return tuple(sorted(fixed)), tuple(sorted(zones))
