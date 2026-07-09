"""Phase 0.2 verifier. Given a walk-test log CSV (appliance,action,local_time),
pull each ON/OFF window from the live partitions and report, per appliance:
which leg(s) stepped, the step in amps and watts, the balanced-240 step, and
PF = |panel real-W step| / |CT apparent-VA step|. Confirms 240V vs 120V and leg.

Log CSV columns:  appliance,action,local_time     action in {ON,OFF}
  local_time as 'YYYY-MM-DD HH:MM:SS' (America/Los_Angeles)
Usage:  ../../../../.venv-training/bin/python3 phase0_walktest_queries.py --log walktest_log.csv
"""
import argparse, subprocess, io, sys
import numpy as np, pandas as pd

CH = ["I11","I12","I21","I22","I31","I32","VrmsA","VrmsB",
      "Panel1 (HVAC)","Panel2 (H2O)","Panel3 (Kitchen)"]
PANEL_CT = {"P1":("I11","I12","Panel1 (HVAC)"),"P2":("I21","I22","Panel2 (H2O)"),
            "P3":("I31","I32","Panel3 (Kitchen)")}
APP_PANEL = {"heat_pump":"P1","solar_pump":"P1","blower":"P1","fan":"P1",
  "water_heater":"P2","sprinklers":"P2","bath_lights":"P2","hair_dryer":"P2",
  "dryer":"P3","oven":"P3","cooktop":"P3","microwave":"P3","refrigerator":"P3",
  "washing_machine":"P3","dishwasher":"P3","pressure_pump":"P3","computers":"P3",
  "tv_stereo":"P3","vacuum_cleaner":"P3"}
TZ="America/Los_Angeles"; GUARD_ON=15; GUARD_OFF=10; BASE_A=75; BASE_B=15

def partitions():
    q="select tablename from pg_tables where tablename like 'par_egauge_kafka_%d14_insert_timestamp';"
    out=subprocess.run(["docker","exec","-e","PGPASSWORD=passwd","postgres1","psql","-U","demo",
        "-d","customers","-tAc",q],capture_output=True,text=True).stdout
    return [t.strip() for t in out.splitlines() if t.strip()]

def pull(utc_start, utc_end, parts):
    chlist=",".join("'"+c.replace("'","''")+"'" for c in CH)
    union=" UNION ALL ".join(
        f"select ts,nm,w from {p} where ts between '{utc_start}' and '{utc_end}' and nm in ({chlist})"
        for p in parts)
    sql=f"COPY ({union}) TO STDOUT WITH (FORMAT csv, HEADER false)"
    out=subprocess.run(["docker","exec","-e","PGPASSWORD=passwd","postgres1","psql","-U","demo",
        "-d","customers","-tAc",sql],capture_output=True,text=True).stdout
    if not out.strip(): return None
    df=pd.read_csv(io.StringIO(out),header=None,names=["ts","nm","w"])
    df["ts"]=pd.to_datetime(df["ts"],utc=True)
    return df.pivot_table(index="ts",columns="nm",values="w",aggfunc="mean").sort_index()

def med(w,ch,a,b):
    if ch not in w: return np.nan
    s=w[ch].loc[a:b]; return float(s.median()) if len(s) else np.nan

def pairs_from_log(df):
    df=df.sort_values("t"); out=[]; pend={}
    for _,r in df.iterrows():
        ap=r["appliance"].strip().lower(); act=r["action"].strip().upper()
        if act=="ON": pend[ap]=r["t"]
        elif act=="OFF" and ap in pend:
            out.append((ap,pend.pop(ap),r["t"]))
    return out

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--log",required=True); a=ap.parse_args()
    log=pd.read_csv(a.log)
    log["t"]=pd.to_datetime(log["local_time"]).dt.tz_localize(TZ)
    parts=partitions()
    print(f"partitions: {len(parts)} found")
    print(f"{'appliance':>15} {'panel':>5} {'legA_dW':>8} {'legB_dW':>8} {'bal240_dW':>10} "
          f"{'panel_dW':>9} {'PF':>5}  verdict")
    for ap_name,t_on,t_off in pairs_from_log(log):
        pk=APP_PANEL.get(ap_name)
        on_a=(t_on+pd.Timedelta(seconds=GUARD_ON)).tz_convert("UTC"); on_b=(t_off-pd.Timedelta(seconds=GUARD_OFF)).tz_convert("UTC")
        off_a=(t_on-pd.Timedelta(seconds=BASE_A)).tz_convert("UTC"); off_b=(t_on-pd.Timedelta(seconds=BASE_B)).tz_convert("UTC")
        w=pull(off_a.strftime("%Y-%m-%d %H:%M:%S"),on_b.strftime("%Y-%m-%d %H:%M:%S"),parts)
        if w is None or w.empty: print(f"{ap_name:>15} {'?':>5}   no data in window"); continue
        if pk is None: print(f"{ap_name:>15} {'?':>5}   (unmapped appliance)"); continue
        ca,cb,pn=PANEL_CT[pk]
        VA=med(w,"VrmsA",on_a,on_b) or 123.0; VB=med(w,"VrmsB",on_a,on_b) or 123.0
        dIa=med(w,ca,on_a,on_b)-med(w,ca,off_a,off_b)
        dIb=med(w,cb,on_a,on_b)-med(w,cb,off_a,off_b)
        legA_dW=dIa*VA; legB_dW=dIb*VB
        dmin=(min(med(w,ca,on_a,on_b),med(w,cb,on_a,on_b))
              -min(med(w,ca,off_a,off_b),med(w,cb,off_a,off_b)))
        bal_dW=2*dmin*120.0
        pan_dW=abs(med(w,pn,on_a,on_b)-med(w,pn,off_a,off_b))
        va_step=abs(dIa*VA)+abs(dIb*VB)
        pf=pan_dW/va_step if va_step>1 else float("nan")
        bal=abs(legA_dW-legB_dW); big=max(abs(legA_dW),abs(legB_dW),1)
        if bal/big<0.35: verdict="240V (both legs)"
        else: verdict=f"120V (leg {'A/'+ca if abs(legA_dW)>abs(legB_dW) else 'B/'+cb})"
        print(f"{ap_name:>15} {pk:>5} {legA_dW:>8.0f} {legB_dW:>8.0f} {bal_dW:>10.0f} "
              f"{pan_dW:>9.0f} {pf:>5.2f}  {verdict}")

if __name__=="__main__":
    main()
