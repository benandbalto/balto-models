from dataclasses import dataclass, fields
from datetime import date
@dataclass(frozen=True)
class Phase:
    key: str
    label: str
@dataclass(frozen=True)
class SpendingPeriod:
    key: str
    phase: str
    label: str
@dataclass(frozen=True)
class UnitType:
    key: str
    label: str
@dataclass(frozen=True)
class DevelopmentDeal:
    kind: str
    name: str
    location: str
    closing: date
    horizon_years: int
    phases: tuple[Phase,...]
    spending_periods: tuple[SpendingPeriod,...]
    unit_types: tuple[UnitType,...]

def read_deal(value,kind='development'):
    if not isinstance(value,dict) or set(value)!={f.name for f in fields(DevelopmentDeal)}:
        raise ValueError('Every development structure field is required.')
    data=dict(value)
    if data['kind']!=kind or type(data['horizon_years']) is not int or not 3<=data['horizon_years']<=10:
        raise ValueError('Invalid development kind or horizon.')
    data['closing']=date.fromisoformat(data['closing'])
    for name,cls,limit in (('phases',Phase,10),('spending_periods',SpendingPeriod,120),('unit_types',UnitType,20)):
        rows=data[name]
        if not isinstance(rows,list) or not 1<=len(rows)<=limit:raise ValueError('Invalid development structure size.')
        data[name]=tuple(cls(**row) for row in rows)
        if len({r.key for r in data[name]})!=len(rows):raise ValueError('Keys must be unique.')
    return DevelopmentDeal(**data)
