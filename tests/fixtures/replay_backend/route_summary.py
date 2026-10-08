"""Deliberately controlled disclosure records for scope-worker tests."""
def named_nets(summaries):
    result=set()
    for summary in summaries:
        result.update(summary.get('routed_single',[]))
        result.update(summary.get('oracle_open',{}))
        result.update(item['net'] for item in summary.get('pad_pairs_open',[]))
    return result
