"""Presentation keeps evaluation, run and entity identities separate."""
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from fastapi import HTTPException

from orgsim.evaluation.history import run_history
from orgsim.evaluation.presentation import insights_document, presented_scenarios


def test_create_and_edit_scenario_never_overwrites_or_loses_custom_role(tmp_path, monkeypatch):
    server = importlib.import_module('orgsim.server.app')
    scenarios = tmp_path / 'scenarios'; scenarios.mkdir()
    (scenarios / 'baseline.yaml').write_text('id: baseline\ntitle: Reference\nworld: {type: workforce}\n')
    ctx = SimpleNamespace(id='demo', scenarios_dir=scenarios, ui_dir=tmp_path/'ui', meta={'scenarios': {'baseline': 'baseline'}})
    monkeypatch.setattr(server, '_ctx', lambda _: ctx)
    server.create_scenario('demo', {'id':'first', 'title':'First', 'extends':'baseline'})
    server.create_scenario('demo', {'id':'second', 'title':'Second', 'extends':'first'})
    before = (scenarios/'second.yaml').read_bytes()
    with pytest.raises(HTTPException) as error:
        server.create_scenario('demo', {'id':'second', 'title':'Overwrite'})
    assert error.value.status_code == 409
    assert (scenarios/'second.yaml').read_bytes() == before
    for bad in ['../escape', 'has/slash', '']:
        with pytest.raises(HTTPException):
            server.create_scenario('demo', {'id':bad,'title':'Invalid'})
    body=server.scenario('demo','second')
    server.save_scenario('demo','second',body)
    assert next(s for s in presented_scenarios(ctx) if s['id']=='second')['role']=='custom'
    assert server.scenario('demo','second')['world']=={'type':'workforce'}


def test_aggregate_history_keeps_group_paths_even_without_trace_rows():
    class Reader:
        run_id='saved';scenario='baseline'
        def json(self,name):
            return {'summary.json': {'headline':{'groups':[{'group':'43','label':'Office','central':[.1,.12]}], 'outcome':'share'},'seed':1}, 'metrics.json':{}}.get(name)
        def trace(self):
            return pd.DataFrame()
    d=run_history(SimpleNamespace(id='aei_tasks'),Reader())
    assert d['trace_rows']==0
    assert d['metrics'][0]['value']==12
    assert d['entities'][0]['series'][0]['values']==[10,12]
    assert 'individual people and hourly states are not recorded' in d['note']


def test_business_accuracy_uses_mean_error_not_error_of_mean(tmp_path):
    ui=tmp_path/'ui';ui.mkdir()
    (ui/'presentation.yaml').write_text('primary: {story: spend, other: trend, unit: USD, label: Spend, subject: spending}\n')
    evaluation={'business_validation':[{'id':'spend','simulation_mae':4,'baseline_mae':{'trend':8}}]}
    (tmp_path/'evaluation.json').write_text(json.dumps(evaluation))
    result={'story':{'metrics':[{'id':'spend','after_actual':50,'after_sim':45}], 'baselines':[{'id':'trend','label':'Trend','values':{'spend':51}}]}}
    d=insights_document(SimpleNamespace(ui_dir=ui,runs_dir=tmp_path,meta={}),result)
    assert abs(d['primary']['simulation']-50)>abs(d['primary']['other']-50)
    assert d['primary']['error']['simulation']<d['primary']['error']['other']


@pytest.mark.data
def test_trip_level_comparator_and_matched_alternative_are_distinct():
    from orgsim.instances import get_instance
    from orgsim.composition import instance_service
    ctx=get_instance('trip')
    result=instance_service(ctx).results()
    d=insights_document(ctx,result)
    level=result['story']['level_comparison']
    assert d['primary']['other']==next(p['value'] for p in level['predictions'] if p['label']==d['primary']['other_label'])
    assert d['alternatives'][0]['metrics'][0]['reference']==next(m['paired_baseline'] for m in result['metrics'] if m['id']=='attrition_all')
    assert d['alternatives'][1]['metrics']  # presentation edits must not invalidate model fingerprints
