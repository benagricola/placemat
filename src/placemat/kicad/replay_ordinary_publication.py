"""Publish original ordinary selection, explicitly without strict adoption."""
import json
from pathlib import Path
import shutil
from placemat.kicad.final_call import ProofUnavailable,file_hash,record_digest
from .replay_comparison import preserve_current
from .replay_publication import detached


def publish_selected(budget,authority,incumbent,candidate,destination,selection):
    budget._check(budget.executor)
    if (selection.get('selected') not in ('pocket','escape') or selection.get('ordinary_comparison_only') is not True
            or selection.get('selected')=='escape' and (selection.get('candidate_kind')!='escape'
                                                       or selection.get('preference_candidate')!='pocket')):
        raise ProofUnavailable('replay_original_ordinary_selection_required')
    source=Path(candidate.evidence).parent
    expected={p.name:file_hash(p) for p in source.iterdir() if p.is_file()}
    destination=Path(destination).resolve()
    if destination.exists():raise ProofUnavailable('replay_fresh_publication_required')
    # Final adjacent guard on the exact minted boards, not aggregate ranking.
    preserve_current(authority,budget.grader,incumbent,candidate)
    budget._check(budget.executor)
    shutil.copytree(source,destination)
    actual={p.name:file_hash(p) for p in destination.iterdir() if p.is_file()}
    if record_digest(actual)!=record_digest(expected):
        raise ProofUnavailable('replay_ordinary_publication_changed')
    # Full-standing evidence remains truthful (including unknown/invalid facts).
    # This distinct record identifies execution selection, never certification.
    return detached(authority,candidate,destination,ordinary_selection=selection)
