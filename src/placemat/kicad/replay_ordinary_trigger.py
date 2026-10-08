"""Read the actual backend's original second-slot applicability rule."""
import ast
from pathlib import Path
from placemat.kicad.final_call import ProofUnavailable,file_hash


def permits_second_slot(helper,summary,expected_sha):
    helper=Path(helper)
    try:
        if file_hash(helper)!=expected_sha:
            raise ProofUnavailable('replay_ordinary_trigger_source_changed')
        tree=ast.parse(helper.read_text())
        node=next((item for item in tree.body if isinstance(item,ast.FunctionDef) and item.name=='closure_hint'),None)
        if node is None:raise ProofUnavailable('replay_ordinary_trigger_unavailable')
        namespace={}
        exec(compile(ast.Module(body=[node],type_ignores=[]),str(helper),'exec'),namespace)
        hint=namespace['closure_hint'](summary)
        if file_hash(helper)!=expected_sha:
            raise ProofUnavailable('replay_ordinary_trigger_source_changed')
    except (OSError,ValueError,TypeError,AttributeError,KeyError) as error:
        raise ProofUnavailable('replay_ordinary_trigger_unavailable') from error
    if hint is None:return False
    if type(hint) is not int or hint<0:
        raise ProofUnavailable('replay_ordinary_trigger_unavailable')
    return hint>0
