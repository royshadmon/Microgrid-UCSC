"""Energy accounting: how much of sub-panel energy the 3 measured 240V loads
capture, and how much stays in the un-separable 120V leg bucket."""
import glob, os
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
PAIR = {"P1": ("I11","I12"), "P2": ("I21","I22"), "P3": ("I31","I32")}
PN = {"P1":"Panel1 (HVAC)","P2":"Panel2 (H2O)","P3":"Panel3 (Kitchen)"}
LOAD = {"P1":"heat_pump","P2":"water_heater","P3":"dryer"}
ONTHR = {"P1":300,"P2":500,"P3":1000}  # 240V-load on-threshold (W)

def load():
    fs = sorted(glob.glob(os.path.join(HERE,"raw_par_egauge_kafka_*.csv")))
    long = pd.concat([pd.read_csv(f,header=None,names=["ts","nm","w"]) for f in fs],ignore_index=True)
    long["ts"]=pd.to_datetime(long["ts"],utc=True)
    wide=long.pivot_table(index="ts",columns="nm",values="w",aggfunc="mean").sort_index()
    w6=wide.resample("6s").mean()
    return w6
w=load()
DT_H = 6/3600.0
tot_panel=tot_240=tot_imbal=0.0
print(f"{'panel':>6} {'appl':>13} {'panel_kWh':>10} {'240_kWh':>9} {'240_share':>10} {'imbal_kWh':>10} {'240_duty':>9} {'240_on_med_W':>12}")
for pk,(a,b) in PAIR.items():
    P=w[PN[pk]].abs(); Ia,Ib=w[a],w[b]
    m=P.notna()&Ia.notna()&Ib.notna(); P,Ia,Ib=P[m],Ia[m],Ib[m]
    bal=2*np.minimum(Ia,Ib)*120.0
    imbal=(Ia-Ib).abs()*120.0
    recon=120*(Ia+Ib)
    e_panel=(recon.sum())*DT_H/1000
    e_240=(bal.sum())*DT_H/1000
    e_imbal=(imbal.sum())*DT_H/1000
    on=bal>ONTHR[pk]
    duty=on.mean(); onmed=np.median(bal[on]) if on.any() else 0
    tot_panel+=e_panel; tot_240+=e_240; tot_imbal+=e_imbal
    print(f"{pk:>6} {LOAD[pk]:>13} {e_panel:>10.1f} {e_240:>9.1f} {e_240/e_panel:>9.1%} {e_imbal:>10.1f} {duty:>8.1%} {onmed:>12.0f}")
print(f"{'ALL':>6} {'(3x240 loads)':>13} {tot_panel:>10.1f} {tot_240:>9.1f} {tot_240/tot_panel:>9.1%} {tot_imbal:>10.1f}")
print()
print(f"Sub-panel energy over window: {tot_panel:.0f} kWh")
print(f"Captured as measured 240V loads (heat_pump+water_heater+dryer): {tot_240:.0f} kWh = {tot_240/tot_panel:.1%}")
print(f"Left in un-separable 120V leg bucket (9+ P3 loads, P2 minor, P1 minor): {tot_imbal:.0f} kWh = {tot_imbal/tot_panel:.1%}")
