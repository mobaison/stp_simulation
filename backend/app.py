from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from threading import RLock
from pathlib import Path
from typing import Literal
from dataclasses import asdict
from dotenv import load_dotenv
from history import Recorder, csv_lines
from chat import answer
import os
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from engine import BALANCED_EQ_RETURN_GPM, BALANCED_PERMEATE_GPM, DEFAULT_WASTING_RATIO, Twin, Controls

app=FastAPI(title='BNR-MBR Smart STP Digital Twin')
app.add_middleware(CORSMiddleware,allow_origins=['http://localhost:5173','http://127.0.0.1:5173'],allow_methods=['*'],allow_headers=['*'])
root = Path(__file__).resolve().parent
load_dotenv(root / '.env', override=True)
recorder = Recorder(os.environ.get('STP_HISTORY_DB', root / 'history' / 'sessions.sqlite3'))
lock = RLock()
model = Twin()
last_controls = None
pending = None

def flush_pending():
    global pending
    if pending is not None:
        recorder.append(*pending)
        pending = None

class Inputs(BaseModel):
    inlet_gpm:float=Field(1900,ge=0,le=6000)
    lift_gpm:float=Field(3000,ge=0,le=6000)
    permeate_gpm:float=Field(BALANCED_PERMEATE_GPM,ge=0,le=6000)
    eq_fraction:float=Field(.15,ge=0,le=1)
    eq_return_gpm:float=Field(BALANCED_EQ_RETURN_GPM,ge=0,le=6000)
    nrcy_ratio:float=Field(.3,ge=0,le=1)
    arcy_ratio:float=Field(.12,ge=0,le=1)
    ras_ratio:float=Field(.12,ge=0,le=1)
    wasting_ratio:float=Field(DEFAULT_WASTING_RATIO,ge=0,le=1)
    aeration:float=Field(1,ge=0,le=2)
    air_scour:float=Field(1,ge=0,le=2)
    fouling:float=Field(.15,ge=0,le=1)
    inlet_bod:float=Field(35,ge=0,le=500)
    inlet_cod:float=Field(80,ge=0,le=500)
    inlet_tss:float=Field(5,ge=0,le=500)
    inlet_nh4:float=Field(24,ge=0,le=500)
    inlet_no3:float=Field(1,ge=0,le=500)
    lift_on:bool=True
    permeate_on:bool=True
    eq_on:bool=True
    recycle_on:bool=True
    dt_s:float=Field(60,gt=0,le=3600)
    stream_type:Literal['custom','municipal','blackwater','greywater','kitchen','industrial','stormwater']='custom'
    aerobic_ph:float=Field(7.2,ge=0,le=14)

class Compare(BaseModel):
    baseline:Inputs=Field(default_factory=Inputs)
    failure:Inputs=Field(default_factory=lambda:Inputs(lift_on=False,aeration=0))
    steps:int=Field(30,ge=1,le=120)

@app.get('/state')
def state():
    with lock:
        return model.snapshot()
@app.post('/step')
def step(c:Inputs):
    global last_controls, pending
    with lock:
        flush_pending()
        last_controls = c.model_dump()
        snapshot = model.step(Controls(**last_controls))
        pending = (snapshot, last_controls)
        flush_pending()
        return snapshot
@app.post('/reset')
def reset():
    global last_controls
    with lock:
        flush_pending()
        recorder.finish()
        last_controls = None
        return model.reset()
@app.post('/compare')
def compare(req:Compare):
    results={}
    for key,inputs in (('baseline',req.baseline),('failure',req.failure)):
        s=Twin()
        for _ in range(req.steps):s.step(Controls(**inputs.model_dump()))
        d=s.snapshot()
        results[key]={'quality':d['effluent_quality'],'energy_kwh':d['energy_kwh'],'alerts':len(d['alerts']),'flow_gpm':d['flows_gpm'].get('treated_out',0)}
    return results

class Turn(BaseModel):
    role: Literal['user', 'model']
    text: str = Field(min_length=1, max_length=12000)

class Question(BaseModel):
    message: str = Field(min_length=1, max_length=2000, pattern=r'\S')
    history: list[Turn] = Field(default_factory=list, max_length=8)

@app.post('/chat')
def chat(question: Question):
    with lock:
        import copy
        snapshot = copy.deepcopy(model.snapshot())
        controls = last_controls
    reply, provider = answer(question.message, question.history, snapshot, controls, return_provider=True)
    return {'reply': reply, 'time_s': snapshot['time_s'], 'provider': provider}

@app.get('/history')
def sessions():
    return recorder.sessions()

def session(key):
    rows = recorder.sessions(key)
    if not rows:
        raise HTTPException(404, 'Session not found')
    return rows[0]

@app.get('/history/{key}')
def detail(key: str):
    return {**session(key), 'steps': list(recorder.steps(key))}

@app.get('/history/{key}/download')
def download(key: str):
    session(key)
    return StreamingResponse(csv_lines(recorder.steps(key)), media_type='text/csv',
                             headers={'Content-Disposition': f'attachment; filename="stp-{key}.csv"'})

@app.delete('/history/{key}')
def delete(key: str):
    if not recorder.delete(key):
        raise HTTPException(404, 'Session not found')
    return {'deleted': key}
