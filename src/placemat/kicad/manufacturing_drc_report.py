"""Pinned KiCad DRC-v1 report validation; ignored checks remain disclosed."""
import math
from pathlib import Path
from uuid import UUID
from .manufacturing_annular import Unproved


def validate(data,board):
    required={'$schema','coordinate_units','date','ignored_checks','included_severities','kicad_version','source',
              'violations','unconnected_items','schematic_parity'}
    if not isinstance(data,dict) or not required<=set(data):raise Unproved('drc_report_schema')
    if data['$schema']!='https://schemas.kicad.org/drc.v1.json' or data['coordinate_units']!='mm':raise Unproved('drc_report_schema')
    for key in ('date','kicad_version','source'):
        if type(data[key]) is not str or not data[key]:raise Unproved('drc_report_schema')
    if Path(data['source']).name!=Path(board).name:raise Unproved('drc_report_board_mismatch')
    severities=data['included_severities']
    if (not isinstance(severities,list)
            or any(type(v) is not str or v not in ('error','warning','exclusion') for v in severities)
            or len(set(severities))!=len(severities)
            or not {'error','warning'}<=set(severities)):raise Unproved('drc_report_severities')
    ignored=data['ignored_checks']
    if not isinstance(ignored,list):raise Unproved('drc_report_ignored')
    for row in ignored:
        if not isinstance(row,dict) or any(type(row.get(k)) is not str for k in ('description','key')):raise Unproved('drc_report_ignored')
    for bucket in ('violations','unconnected_items','schematic_parity'):
        if not isinstance(data[bucket],list):raise Unproved('drc_report_items')
        for row in data[bucket]:
            if not isinstance(row,dict) or any(type(row.get(k)) is not str for k in ('description','type','severity')):
                raise Unproved('drc_report_items')
            if row['severity'] not in ('error','warning','exclusion'):raise Unproved('drc_report_items')
            if not isinstance(row.get('items'),list):raise Unproved('drc_report_items')
            for item in row['items']:
                if not isinstance(item,dict) or type(item.get('description')) is not str or type(item.get('uuid')) is not str:
                    raise Unproved('drc_report_item_identity')
                try:uid=UUID(item['uuid'])
                except (ValueError,TypeError):raise Unproved('drc_report_item_identity') from None
                if str(uid)!=item['uuid'] or uid.int==0:raise Unproved('drc_report_item_identity')
                pos=item.get('pos')
                if not isinstance(pos,dict) or set(pos)!={'x','y'}:raise Unproved('drc_report_position')
                for value in pos.values():
                    try:finite=type(value) in (int,float) and math.isfinite(value)
                    except OverflowError:finite=False
                    if not finite:raise Unproved('drc_report_position')
    return {'schema_validated':True,'ignored_checks':ignored,'included_severities':severities,
            'manufacturing_complete':False,'comparison_authority':False}
