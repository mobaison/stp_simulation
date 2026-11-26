"""Educational, uncalibrated BNR–MBR finite-volume digital-twin simulator.
Volumes in m3, rates in US GPM, concentrations in mg/L, masses in kg.
All geometry except a provisionally assigned 66 ft EQ tank is assumed.
"""
from dataclasses import dataclass, asdict
from math import pi, exp, sqrt
from collections import defaultdict

GPM = 0.003785411784/60
MGD_GPM = 1_000_000/1440
FIELDS=('bod','cod','tss','nh4','no3')
DEFAULT={'bod':35.,'cod':80.,'tss':5.,'nh4':24.,'no3':1.}
# EPA Technical Guidance Manual, Book II, Table A-6 (medium-strength raw sewage).
RAW_MUNICIPAL_INFLUENT = dict(inlet_bod=200., inlet_cod=500., inlet_tss=200.,
                            inlet_nh4=25., inlet_no3=0.)

DEFAULT_INLET_GPM = 1900.
DEFAULT_EQ_FRACTION = .15
EQ_DIVERSION_BASIS_GPM = 2600.
TRAIN_TRANSFER_LIMIT_GPM = 1400.
LEGACY_WASTING_RATIO = .005
DEFAULT_WASTING_RATIO = .006719200983053761
DEFAULT_FOULING = .15
DEFAULT_AIR_SCOUR = 1.
DESIGN_BASIS_AMMONIA_RATE_H = 5.799
LEGACY_AMMONIA_RATE_H = .17
ORGANIC_DECAY_MULTIPLIERS = {'cod': 3.919947, 'bod': 4.095079}
LEGACY_ORGANIC_STAGE_RATES_H = {
    'ana': {'bod': .07, 'cod': .04},
    'pre': {'bod': .12, 'cod': .07, 'no3': .20},
    'aero': {'bod': .28, 'cod': .15, 'nh4': DESIGN_BASIS_AMMONIA_RATE_H},
    'post': {'bod': .08, 'cod': .05, 'no3': .12},
}
STAGE_REACTION_RATES_H = {
    zone: {field: rate * ORGANIC_DECAY_MULTIPLIERS.get(field, 1.) for field, rate in rates.items()}
    for zone, rates in LEGACY_ORGANIC_STAGE_RATES_H.items()
}
LEGACY_MEMBRANE_RETENTION = {'tss': .99, 'bod': .30, 'cod': .18}
DESIGN_TSS_RETENTION = .9998
ORGANICS = ('cod', 'bod')
MEMBRANE_RETENTION = dict.fromkeys(('tss', *ORGANICS), DESIGN_TSS_RETENTION)
# Design assumptions informed by the Pumpkinvine pilot Table 1; not site data.
REFERENCE_PARTICULATE = {'cod': 1 - 201/517, 'bod': 1 - 92/240}
REFERENCE_PARTICULATE_PER_TSS = {
    field: fraction * RAW_MUNICIPAL_INFLUENT[f'inlet_{field}'] / RAW_MUNICIPAL_INFLUENT['inlet_tss']
    for field, fraction in REFERENCE_PARTICULATE.items()
}


def particulate_fraction(field, concentration, tss):
    if concentration <= 0:
        return 0.
    return min(REFERENCE_PARTICULATE[field], tss * REFERENCE_PARTICULATE_PER_TSS[field] / concentration)


def permeate_fraction(fouling, air_scour):
    return max(.10, 1 - .65 * fouling + .1 * (air_scour - 1))


def recycle_power_kw(actual_gpm):
    return 3 * actual_gpm / (4 * TRAIN_TRANSFER_LIMIT_GPM)


# Match nominal inflow to discharge plus sludge wasting at the default settings.
DEFAULT_WASTING_GPM = 4 * TRAIN_TRANSFER_LIMIT_GPM * DEFAULT_WASTING_RATIO
BALANCED_PERMEATE_GPM = (
    (DEFAULT_INLET_GPM - DEFAULT_WASTING_GPM) / permeate_fraction(DEFAULT_FOULING, DEFAULT_AIR_SCOUR)
)
BALANCED_EQ_RETURN_GPM = DEFAULT_EQ_FRACTION * EQ_DIVERSION_BASIS_GPM

@dataclass(frozen=True)
class Vessel:
    key:str
    name:str
    area:float
    depth:float
    role:str
    @property
    def cap(self):return self.area*self.depth

def rect(key,name,length,width,depth,role):return Vessel(key,name,length*width,depth,role)
def circle(key,name,dia,depth,role):return Vessel(key,name,pi*dia*dia/4,depth,role)

VESSELS=[circle('lift','Facility lift station',7,4,'inlet'),rect('coarse','Coarse screening',9,4,2.5,'screen'),rect('grit','Grit removal',10,5,3,'screen'),circle('eq1','Equalization basin 1',66*.3048,15*.3048,'eq'),circle('eq2','Equalization basin 2',12,4.5,'eq'),rect('fine','Fine screening',10,4,2.5,'screen')]
for i in range(1,5):
    VESSELS += [rect(f'ana{i}',f'Anaerobic zone {i}',10,8,4.5,'ana'),rect(f'pre{i}',f'Pre-anoxic zone {i}',9,8,4.5,'pre'),rect(f'aero{i}',f'Aerobic basin {i}',22,8,4.5,'aero'),rect(f'post{i}',f'Post-anoxic zone {i}',9,8,4.5,'post'),rect(f'mbr{i}',f'Membrane tank {i}',13,8,4.5,'mbr')]
VESSELS += [circle('outlet','Treated water holding tank',10,4,'outlet')]
SPEC={s.key:s for s in VESSELS}

@dataclass
class Controls:
    inlet_gpm:float=DEFAULT_INLET_GPM
    lift_gpm:float=3000
    permeate_gpm:float=BALANCED_PERMEATE_GPM
    eq_fraction:float=DEFAULT_EQ_FRACTION
    eq_return_gpm:float=BALANCED_EQ_RETURN_GPM
    nrcy_ratio:float=.30
    arcy_ratio:float=.12
    ras_ratio:float=.12
    wasting_ratio:float=DEFAULT_WASTING_RATIO
    aeration:float=1.
    air_scour:float=DEFAULT_AIR_SCOUR
    fouling:float=DEFAULT_FOULING
    inlet_bod:float=35.
    inlet_cod:float=80.
    inlet_tss:float=5.
    inlet_nh4:float=24.
    inlet_no3:float=1.
    lift_on:bool=True
    permeate_on:bool=True
    eq_on:bool=True
    recycle_on:bool=True
    dt_s:float=60.
    stream_type:str='custom'
    aerobic_ph:float=7.2

class Twin:
    reaction_rates_h = STAGE_REACTION_RATES_H
    membrane_retention = MEMBRANE_RETENTION
    nrcy_ratio_limit = 1.
    track_particulates = True
    particulate_multiplier = 1.

    def __init__(self):self.reset()
    def reset(self):
        self.volume={s.key:s.cap*.50 for s in VESSELS}
        self.mass={s.key:{v:DEFAULT[v]*self.volume[s.key]*.001 for v in FIELDS} for s in VESSELS}
        self.part = {
            key: {v: mass[v] * particulate_fraction(v, DEFAULT[v], DEFAULT['tss']) for v in ORGANICS}
            for key, mass in self.mass.items()
        }
        self.splits = dict.fromkeys(ORGANICS, 0.)
        self.elapsed=0.;self.energy=0.;self.wasted=0.;self.rejected=0.
        self.history=[];self.flows={};self.alerts=[];self.mass_error=0.;self.quality_error={v:0. for v in FIELDS}
        self.effluent_quality = dict.fromkeys(FIELDS)
        self.permeate_tss_mg_l = None
        self.last_recycle_power_kw = 0.
        self.tmp={str(i):0. for i in range(1,5)};self.last_energy=0.
        return self.snapshot()
    def concentration(self,k,v):return max(0.,self.mass[k][v]/(self.volume[k]*.001)) if self.volume[k]>1e-12 else 0.
    def level_limited_gpm(self, key, nominal_gpm, max_gpm):
        # Simplified outlet response, with nominal flow at half-full.
        return min(max_gpm, nominal_gpm * self.volume[key] / (0.5 * SPEC[key].cap))

    def move(self,src,dst,amount,name,retain=None):
        actual=min(max(0.,amount),self.volume[src],float('inf') if dst is None else max(0.,SPEC[dst].cap-self.volume[dst]))
        if actual<=0:return 0.
        transfer_share = actual / self.volume[src] if self.volume[src] > 1e-12 else 0.
        retention = retain or {}
        for v in FIELDS:
            available = self.mass[src][v] * transfer_share
            if self.track_particulates and v in ORGANICS:
                particulate = self.part[src][v] * transfer_share
                particulate_passed = particulate * (1. - retention.get(v, 0.))
                carried = available - particulate * retention.get(v, 0.)
                self.part[src][v] -= particulate_passed
                if dst is not None:
                    self.part[dst][v] += particulate_passed
            else:
                carried = available * (1. - retention.get(v, 0.))
            self.mass[src][v]-=carried
            if dst is not None:
                self.mass[dst][v]+=carried
                if v == 'tss' and dst == 'outlet':
                    self._permeate_tss_mass_kg += carried
            else:
                self._export[v] += carried
                if name == 'treated_out':
                    self._effluent_mass[v] += carried
                    if self.track_particulates and v in ORGANICS:
                        self._effluent_particulate_mass[v] += particulate_passed
        self.volume[src]-=actual
        if dst is not None:self.volume[dst]+=actual
        self._flows[name]+=actual
        return actual
    def process(self,stage,dt_h,aeration,nitrification_factor):
        for v,r in self.reaction_rates_h.get(stage.rstrip('0123456789'),{}).items():
            rate=r*(aeration if stage.startswith('aero') else 1.)
            if v == 'nh4':
                rate *= nitrification_factor
            consumed_fraction = 1-exp(-rate*dt_h)
            removed=self.mass[stage][v]*consumed_fraction
            self.mass[stage][v]-=removed
            if self.track_particulates and v in ORGANICS:
                self.part[stage][v] *= 1. - consumed_fraction
            if v=='nh4':self.mass[stage]['no3']+=removed;self._conversion+=removed
            else:self._removed[v]+=removed
    def step(self,c:Controls):
        if not 0<c.dt_s<=3600:raise ValueError('Timestep must be >0 and <=3600 s')
        if not 0 <= c.aerobic_ph <= 14:
            raise ValueError('Aerobic tank pH must be 0–14')
        # Illustrative inhibition curve. The assumed rate is unchanged within
        # 6.8–8.0 and tapers linearly to zero at pH 5.5 and 9.5.
        nitrification_factor = max(0., min(1., (c.aerobic_ph - 5.5) / 1.3, (9.5 - c.aerobic_ph) / 1.5))
        for k in ('inlet_gpm','lift_gpm','permeate_gpm','eq_return_gpm'):
            if not 0<=getattr(c,k)<=6000:raise ValueError(f'{k} must be 0–6000 GPM')
        if not 0 <= c.nrcy_ratio <= self.nrcy_ratio_limit:
            raise ValueError(f'Nitrate recycle ratio must be between 0 and {self.nrcy_ratio_limit:g}')
        for k in ('eq_fraction','arcy_ratio','ras_ratio','wasting_ratio','fouling'):
            if not 0<=getattr(c,k)<=1:raise ValueError(f'{k} must be between 0 and 1')
        if not 0<=c.aeration<=2 or not 0<=c.air_scour<=2:raise ValueError('Aeration/scour 0–2')
        for k in ('inlet_bod','inlet_cod','inlet_tss','inlet_nh4','inlet_no3'):
            if not 0<=getattr(c,k)<=500:raise ValueError(f'{k}: 0–500 mg/L')
        initial_volume=sum(self.volume.values());initial_mass={v:sum(self.mass[t.key][v] for t in VESSELS) for v in FIELDS}
        self._export=defaultdict(float);self._removed=defaultdict(float);self._conversion=0.;self._flows=defaultdict(float)
        self._effluent_mass = dict.fromkeys(FIELDS, 0.)
        self._effluent_particulate_mass = dict.fromkeys(ORGANICS, 0.)
        self._permeate_tss_mass_kg = 0.
        input_mass=defaultdict(float);admitted=0.;rejected=0.;wasted=0.;energy=0.
        inlet={'bod':c.inlet_bod,'cod':c.inlet_cod,'tss':c.inlet_tss,'nh4':c.inlet_nh4,'no3':c.inlet_no3}
        self.splits = {v: min(1., self.particulate_multiplier * particulate_fraction(v, inlet[v], inlet['tss']))
                       for v in ORGANICS}
        recycle_m3 = 0.
        count=max(1,int(c.dt_s/5+.999999));dt=c.dt_s/count
        for _ in range(count):
            offered=c.inlet_gpm*GPM*dt;received=min(offered,SPEC['lift'].cap-self.volume['lift']);rejected+=offered-received
            self.volume['lift']+=received;admitted+=received;self._flows['inlet']+=received
            for v in FIELDS:
                m=received*.001*inlet[v];input_mass[v]+=m;self.mass['lift'][v]+=m
                if self.track_particulates and v in ORGANICS:
                    self.part['lift'][v] += m * self.splits[v]
            # Assumed pump: quadratic head capacity, plus requested setpoint cap.
            pump_factor=sqrt(max(0.,1-(7+7*self.volume['coarse']/SPEC['coarse'].cap)/20))
            lift_flow=self.level_limited_gpm('lift',c.lift_gpm,min(c.lift_gpm,6000*pump_factor)) if c.lift_on else 0.
            pumped=self.move('lift','coarse',lift_flow*GPM*dt,'lift_pumps')
            self.move('coarse','grit',self.level_limited_gpm('coarse',1900,5500)*GPM*dt,'coarse_grit')
            for i in (1,2):self.move('grit',f'eq{i}',c.eq_fraction*EQ_DIVERSION_BASIS_GPM*GPM*dt/2,f'eq_feed{i}')
            self.move('grit','fine',self.level_limited_gpm('grit',1900,5500)*GPM*dt,'grit_fine')
            if c.eq_on:
                for i in (1,2):self.move(f'eq{i}','fine',c.eq_return_gpm*.5*GPM*dt,f'eq_return{i}')
            # Reserve equal shares before any train can draw down the common feed.
            fine_feed = min(self.volume['fine'], self.level_limited_gpm('fine',1900,5600)*GPM*dt)/4
            for i in range(1,5):
                feed=TRAIN_TRANSFER_LIMIT_GPM*GPM*dt
                self.move('fine',f'ana{i}',fine_feed,f'feed{i}')
                for src, dst, edge in (
                    ('ana','pre','ana_pre'), ('pre','aero','pre_aero'),
                    ('aero','post','aero_post'), ('post','mbr','post_mem'),
                ):
                    source = f'{src}{i}'
                    volume = self.level_limited_gpm(source,750,TRAIN_TRANSFER_LIMIT_GPM)*GPM*dt
                    self.move(source,f'{dst}{i}',volume,f'{edge}{i}')
                if c.recycle_on:
                    recycle_m3 += self.move(f'aero{i}',f'pre{i}',c.nrcy_ratio*feed,f'nrcy{i}')
                    recycle_m3 += self.move(f'mbr{i}',f'ana{i}',c.arcy_ratio*feed,f'arcy{i}')
                    recycle_m3 += self.move(f'mbr{i}',f'aero{i}',c.ras_ratio*feed,f'ras{i}')
                wasted+=self.move(f'mbr{i}',None,c.wasting_ratio*feed,f'waste{i}')
                limited=min(c.permeate_gpm,3.1*MGD_GPM)/4
                factor=permeate_fraction(c.fouling,c.air_scour)
                q=limited*factor if c.permeate_on else 0.
                flow=self.move(f'mbr{i}','outlet',q*GPM*dt,f'permeate{i}',self.membrane_retention)
                self.tmp[str(i)]=round(7+22*c.fouling+3*(flow/GPM/dt/max(1,limited)),2)
                for prefix in ('ana','pre','aero','post'):self.process(f'{prefix}{i}',dt/3600,c.aeration,nitrification_factor)
            self.move('outlet',None,3.1*MGD_GPM*GPM*dt,'treated_out')
            pump_kw=1000*9.81*(pumped/dt)*14/(.72*1000)
            membrane_kw=1000*9.81*(min(c.permeate_gpm,3.1*MGD_GPM)*GPM)*10/(.65*1000) if c.permeate_on else 0
            energy+=(pump_kw+membrane_kw+18*c.aeration+12*c.air_scour)*dt/3600
        self.last_recycle_power_kw = recycle_power_kw(recycle_m3 / (GPM * c.dt_s))
        energy += self.last_recycle_power_kw * c.dt_s / 3600
        self.elapsed+=c.dt_s;self.energy+=energy;self.wasted+=wasted;self.rejected+=rejected;self.last_energy=energy
        actual_export=self._flows['treated_out']+wasted
        self.mass_error=round(initial_volume+admitted-actual_export-sum(self.volume.values()),8)
        self.quality_error={}
        for v in FIELDS:
            conversion=self._conversion*(1 if v=='no3' else -1 if v=='nh4' else 0)
            final=sum(self.mass[t.key][v] for t in VESSELS)
            self.quality_error[v]=round(initial_mass[v]+input_mass[v]+conversion-self._removed[v]-self._export[v]-final,8)
        self.flows={k:round(q/GPM/c.dt_s,2) for k,q in self._flows.items()}
        self.alerts=[f'{s.name}: HIGH LEVEL' for s in VESSELS if self.volume[s.key]/s.cap>=.95]
        # The final tank is modeled as a free-draining outlet and can be
        # nearly empty while discharging normally.
        self.alerts += [f'{s.name}: LOW LEVEL' for s in VESSELS
                        if self.volume[s.key]/s.cap<=.05 and (s.key!='outlet' or not self._flows['treated_out'])]
        if rejected>.0001:self.alerts.append('Wet well: incoming sewage rejected')
        if not c.lift_on:self.alerts.append('Lift pump stopped')
        if c.aeration==0:self.alerts.append('Aeration unavailable')
        if not 6.8 <= c.aerobic_ph <= 8.0:self.alerts.append('Aerobic pH outside modeled range for full nitrification')
        if c.air_scour==0:self.alerts.append('Membrane air scour stopped')
        if c.fouling>.7:self.alerts.append('High membrane fouling index')
        discharged_m3 = self._flows['treated_out']
        self.effluent_quality = {
            v: round(self._effluent_mass[v] / (discharged_m3 * .001), 3) if discharged_m3 else None
            for v in FIELDS
        }
        permeate_m3 = sum(self._flows.get(f'permeate{i}', 0.) for i in range(1, 5))
        self.permeate_tss_mg_l = self._permeate_tss_mass_kg * 1000 / permeate_m3 if permeate_m3 else None
        quality = self.effluent_quality
        self.history.append({'t_s':round(self.elapsed,2),'cod':quality['cod'],'bod':quality['bod'],'tss':quality['tss'],'flow_mgd':round(self.flows.get('treated_out',0)/MGD_GPM,3),'energy':round(self.energy,3),'alerts':len(self.alerts)})
        self.history=self.history[-360:]
        return self.snapshot()
    def quality(self,key):return {v:round(self.concentration(key,v),3) for v in FIELDS}
    def snapshot(self):
        return {'time_s':self.elapsed,'energy_kwh':round(self.energy,4),'step_energy_kwh':round(self.last_energy,4),
                'recycle_power_kw':self.last_recycle_power_kw,
                'tanks':{s.key:{'name':s.name,'pct':round(100*self.volume[s.key]/s.cap,2),'level_m':round(self.volume[s.key]/s.area,3),'volume_m3':round(self.volume[s.key],3),'quality':self.quality(s.key),'role':s.role} for s in VESSELS},
                'flows_gpm':self.flows,'alerts':self.alerts,'history':self.history,'mass_balance_m3':self.mass_error,
                'effluent_quality':self.effluent_quality,
                'permeate_tss_mg_l':self.permeate_tss_mg_l,
                'quality_balance_kg':self.quality_error,'membrane_tmp_kpa':self.tmp,'rejected_m3':round(self.rejected,3),'sludge_waste_m3':round(self.wasted,3),
                'reference':{'plant_mgd':7.5,'outlet_mgd':3.1,'outlet_cod':5,'outlet_tss':2,'electricity_kwh_per_hr':19.65},'uncalibrated':True}
