"""Replay is a lossless count projection, with clearly bounded record previews."""
import importlib

import pandas as pd

from orgsim.evaluation.replay import event_replay
from orgsim.store import RunWriter, RunReader


def test_replay_orders_native_steps_counts_every_event_and_filters_exact_entities(tmp_path, monkeypatch):
    store = importlib.import_module('orgsim.store.runs')
    monkeypatch.setattr(store, 'RUNS_DIR', tmp_path)
    writer = RunWriter('demo', 'baseline', 'recorded')
    # Out-of-order frames, repeated actions, a quiet gap, an empty actor and an exact-ID trap.
    rows = []
    for tick, who, action, activity in [(48,'p1','complete','Invoice'),(0,'p10','start','Invoice'),(0,'p1','start','Invoice'),(0,'p1','complete','Invoice'),(0,'p1','complete','Invoice'),(0,'','state','Queue')]:
        rows.append(dict(tick=tick,sim_time=pd.Timestamp('2020-01-01')+pd.Timedelta(hours=tick),agent_id=who,
                         role='Clerk',org_unit='',case_id='c1',activity=activity,action_type=action,
                         duration_h=1.,wait_h=0.,provenance='simulated',attributes='{"amount":42}'))
    writer.write_rows(pd.DataFrame(rows));writer.close({})
    reader=RunReader('demo','baseline','recorded')
    result=event_replay(reader)
    assert result['total']==6
    assert [f['tick'] for f in result['frames']]==[0,48]  # no invented idle-hour events
    assert [f['total'] for f in result['frames']]==[5,1]
    first=result['frames'][0]
    assert first['entities']==2
    assert sum(a['count'] for a in first['activities'])==5
    assert len(first['samples'])==3  # activity AND action remain separate
    assert first['samples'][0]['attributes']=='{"amount":42}'
    filtered=event_replay(reader,'p1')
    assert filtered['total']==4
    assert all(r['agent_id']=='p1' for f in filtered['frames'] for r in f['samples'])
    assert event_replay(reader,'missing')['frames']==[]


def test_live_trace_activity_link_filters_action_type(tmp_path, monkeypatch):
    server=importlib.import_module('orgsim.server.app')
    frame=pd.DataFrame({'tick':[0,0,1], 'agent_id':['p1']*3, 'case_id':['c']*3,
                        'activity':['Invoice']*3,'action_type':['start','complete','complete']})
    monkeypatch.setattr(server,'_reader',lambda *args:None)
    monkeypatch.setattr(server,'_trace',lambda _:frame)
    page=server.run_file('demo','baseline','recorded','trace',limit=50,activity='Invoice',action='complete',from_tick=0,to_tick=0)
    assert page['total']==1
    assert page['rows'][0]['action_type']=='complete'
