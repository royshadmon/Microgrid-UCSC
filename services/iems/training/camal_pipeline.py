"""Data -> CamAL classification -> rule-based labelling -> weights -> training.

CamAL (Petralia et al. ICDE 2025) architecture, applied in its intended order:
  Problem 1 (DETECT)   : per-window "did appliance X run in this block?"
                         ResNet ensemble w/ varying kernel sizes -> P(a)_ens
  Problem 2 (LOCALIZE) : only if detected, extract CAM from the ensemble, use it
                         as an attention mask over the window, and let the rule
                         engine emit per-timestamp labels INSIDE the CAM support.

The gate is the point: if the detector says the appliance did not run in this
window, the rule engine may not emit ON labels there. That suppresses the
band-collision false positives (e.g. solar_pump sitting inside Panel-1 baseline).
"""
from __future__ import annotations
import sys, os
from pathlib import Path
import numpy as np, pandas as pd, torch, torch.nn as nn

HERE = Path("services/iems/training"); sys.path.insert(0, str(HERE))
import temporal_rule_engine as T
import canonical_signatures as CS

WIN = "1h"          # detection window
L   = 256           # resampled window length (halved from CamAL's 510 for CPU)
NENS, KERNELS = 2, (5, 11)   # paper: classification acc is stable vs ensemble size
EPOCHS, LR = 8, 4e-3
torch.manual_seed(0); np.random.seed(0)

# ---------------- ResNet (CamAL backbone, Wang et al. 2016) ----------------
class Blk(nn.Module):
    def __init__(s, ci, co, k):
        super().__init__()
        s.c1=nn.Conv1d(ci,co,k,padding=k//2); s.b1=nn.BatchNorm1d(co)
        s.c2=nn.Conv1d(co,co,5,padding=2);    s.b2=nn.BatchNorm1d(co)
        s.c3=nn.Conv1d(co,co,3,padding=1);    s.b3=nn.BatchNorm1d(co)
        s.sh=nn.Conv1d(ci,co,1) if ci!=co else nn.Identity()
        s.r=nn.ReLU()
    def forward(s,x):
        y=s.r(s.b1(s.c1(x))); y=s.r(s.b2(s.c2(y))); y=s.b3(s.c3(y))
        return s.r(y+s.sh(x))

class ResNet(nn.Module):
    """3 stacked residual blocks {64,128,128} + GAP + linear (CAM-compatible)."""
    def __init__(s, k, cin=1):
        super().__init__()
        s.b1=Blk(cin,32,k); s.b2=Blk(32,64,k); s.b3=Blk(64,64,k)
        s.fc=nn.Linear(64,2)
    def feat(s,x): return s.b3(s.b2(s.b1(x)))          # (B,64,L)
    def forward(s,x): return s.fc(s.feat(x).mean(-1))   # GAP -> logits
    def cam(s,x):
        f=s.feat(x)                                     # (B,64,L)
        w=s.fc.weight[1]                                # class-1 weights (64,)
        return torch.einsum("bcl,c->bl", f, w)          # CAM_c=1

def train_ensemble(X, y, kernels=KERNELS):
    """Train one ResNet per kernel size; keep those with best val loss."""
    n=len(X); idx=np.random.permutation(n); tr=idx[:int(n*.8)]; va=idx[int(n*.8):]
    Xt=torch.tensor(X[tr]).unsqueeze(1); yt=torch.tensor(y[tr]).long()
    Xv=torch.tensor(X[va]).unsqueeze(1); yv=torch.tensor(y[va]).long()
    pw=torch.tensor([1.0, max(1.0,min(20.0,(y[tr]==0).sum()/max((y[tr]==1).sum(),1)))],
                    dtype=torch.float32)
    models=[]
    for k in kernels:
        m=ResNet(k); opt=torch.optim.AdamW(m.parameters(),lr=LR,weight_decay=1e-4)
        lf=nn.CrossEntropyLoss(weight=pw); best=1e9; bs=None
        for _ in range(EPOCHS):
            m.train(); perm=torch.randperm(len(Xt))
            for i in range(0,len(Xt),64):
                b=perm[i:i+64]
                opt.zero_grad(); l=lf(m(Xt[b]),yt[b]); l.backward(); opt.step()
            m.eval()
            with torch.no_grad(): v=float(lf(m(Xv),yv))
            if v<best: best=v; bs={kk:vv.clone() for kk,vv in m.state_dict().items()}
        if bs: m.load_state_dict(bs)
        m.eval(); models.append((best,m))
    models.sort(key=lambda t:t[0])
    return [m for _,m in models[:NENS]]

def ens_predict(models, X):
    """P(a)_ens = mean of member probabilities; CAM_ens = mean of normalised CAMs."""
    Xt=torch.tensor(X).unsqueeze(1)
    ps=[]; cams=[]
    with torch.no_grad():
        for m in models:
            ps.append(torch.softmax(m(Xt),1)[:,1].numpy())
            c=m.cam(Xt); c=c-c.min(1,keepdim=True).values
            c=c/c.max(1,keepdim=True).values.clamp(min=1e-6)
            cams.append(c.numpy())
    return np.mean(ps,0), np.mean(cams,0)


# ============================ PIPELINE STAGES ============================
W_MEASURED, W_CAM, W_RULE, W_ABSTAIN = 1.00, None, 0.25, 0.00

def stage1_data():
    print("[1] DATA: loading consolidated 11.4M rows ...", flush=True)
    d=pd.read_parquet("analysis/egauge_consolidation/egauge_consolidated_all_eras.parquet",
                      columns=["ts","channel","w"])
    piv=d.pivot_table(index="ts",columns="channel",values="w",aggfunc="first")
    df=pd.DataFrame(index=pd.DatetimeIndex(piv.index))
    for pn,c in T.PANEL_COL.items():
        if pn in piv.columns: df[c]=piv[pn].values
    print(f"    {len(d):,} rows -> {len(df):,} timestamps", flush=True)
    return df

def build_windows(s, idx, win=WIN, L=L):
    """Resample each detection window to fixed length L (CamAL-style)."""
    key=idx.floor(win); uw=pd.DatetimeIndex(sorted(set(key)))
    pos={w:i for i,w in enumerate(uw)}
    X=np.zeros((len(uw),L),dtype="float32"); cnt=np.zeros(len(uw))
    v=s.reindex(idx).to_numpy("float32"); v=np.nan_to_num(v)
    codes=np.array([pos[k] for k in key])
    for wi in range(len(uw)):
        m=codes==wi; seg=v[m]
        if seg.size<2: continue
        X[wi]=np.interp(np.linspace(0,len(seg)-1,L),np.arange(len(seg)),seg)
        cnt[wi]=seg.size
    mx=X.max(1,keepdims=True); mx[mx<1e-6]=1.0
    return uw, X/mx, X, codes, cnt

def stage2_camal(df, idx):
    print("[2] CamAL CLASSIFICATION (detect per window) ...", flush=True)
    det={}
    for app,sig in CS.SIGNATURES.items():
        s=T.series(df,sig.panel,sig.measure)
        uw,Xn,Xr,codes,cnt=build_windows(s,idx)
        # bootstrap weak presence labels from rule events (CamAL trains on weak)
        ev=T.extract_events(s,sig.w[0],sig.w[1],min_dur_s=max(sig.dur_s[0]*0.5,10))
        y=np.zeros(len(uw),dtype="int64")
        if ev:
            fl=pd.DatetimeIndex([e["start"] for e in ev]).floor(WIN)
            pos={w:i for i,w in enumerate(uw)}
            for f in fl:
                if f in pos: y[pos[f]]=1
        ok=cnt>50
        if y[ok].sum()<10 or (y[ok]==0).sum()<10:
            det[app]=dict(uw=uw,p=np.zeros(len(uw)),cam=np.zeros((len(uw),L)),
                          y=y,codes=codes,trained=False,bal_acc=np.nan)
            print(f"    {app:16} SKIP (pos={int(y[ok].sum())}, neg={int((y[ok]==0).sum())})",flush=True)
            continue
        models=train_ensemble(Xn[ok],y[ok])
        p_all,cam_all=ens_predict(models,Xn)
        yh=(p_all[ok]>=0.5).astype(int); yy=y[ok]
        tp=((yh==1)&(yy==1)).sum(); tn=((yh==0)&(yy==0)).sum()
        ba=0.5*(tp/max((yy==1).sum(),1)+tn/max((yy==0).sum(),1))
        det[app]=dict(uw=uw,p=p_all,cam=cam_all,y=y,codes=codes,trained=True,bal_acc=ba)
        print(f"    {app:16} windows={len(uw)} pos={int(y[ok].sum())} "
              f"det_rate={(p_all>=0.5).mean()*100:5.1f}%  bal_acc={ba:.3f}",flush=True)
    return det

def stage3_gated_labels(df, idx, det):
    print("[3] RULE LABELLING (gated by CamAL detection + CAM support) ...", flush=True)
    apps=list(CS.SIGNATURES)
    S=pd.DataFrame(np.nan,index=idx,columns=apps,dtype="float32")
    G=pd.DataFrame(0.0,index=idx,columns=apps,dtype="float32")   # CAM support
    ev_all=T.classify(df)
    for app in apps:
        sig=CS.SIGNATURES[app]; D=det[app]
        # per-timestamp CAM value for its window
        cam_ts=D["cam"][D["codes"], (np.arange(len(idx))%L)] if D["trained"] \
               else np.zeros(len(idx))
        detected=D["p"][D["codes"]]>=0.5
        G[app]=np.where(detected, cam_ts, 0.0)
        # OFF baseline (unchanged; water_heater abstains)
        ser=T.series(df,sig.panel,sig.measure).reindex(idx)
        if not sig.no_confident_off:
            S.loc[ser<sig.on_thr*0.6, app]=0.0
        # ON only where a rule event AND the detector fired
        sub=ev_all[ev_all.appliance==app] if not ev_all.empty else pd.DataFrame()
        for _,e in sub.iterrows():
            span=(idx>=e["start"])&(idx<=e["end"])
            if not (span & detected).any():
                continue                     # GATE: detector says absent -> reject
            S.loc[span & detected, app]=1.0
    return S,G,ev_all

def stage4_weights(S,G,det,ev_all,idx):
    print("[4] WEIGHTS (measured / CAM-confirmed / rule-only / abstain) ...", flush=True)
    apps=list(S.columns)
    Wt=pd.DataFrame(W_ABSTAIN,index=idx,columns=apps,dtype="float32")
    for app in apps:
        sig=CS.SIGNATURES[app]; lab=S[app]
        Wt.loc[lab.notna(),app]=W_RULE
        if not sig.coupled:
            # CAM-confirmed positives: weight = CAM support (attention strength)
            strong=(lab==1)&(G[app]>=0.5)
            Wt.loc[strong,app]=np.clip(G[app][strong],0.5,1.0)
    Wt[S.isna()]=W_ABSTAIN
    return Wt

if __name__=="__main__":
    df=stage1_data(); idx=df.index
    det=stage2_camal(df,idx)
    S,G,ev=stage3_gated_labels(df,idx,det)
    Wt=stage4_weights(S,G,det,ev,idx)
    D=HERE/"data"
    S.to_parquet(D/"labels_camal_gated.parquet"); Wt.to_parquet(D/"weights_camal_gated.parquet")
    # weak labels = CamAL window detections
    WK=pd.DataFrame({a:(det[a]["p"]>=0.5).astype("float32") for a in S.columns},
                    index=det[list(S.columns)[0]]["uw"])
    WKW=pd.DataFrame({a:np.clip(det[a]["p"],0.25,1.0).astype("float32") for a in S.columns},
                     index=WK.index)
    WK.to_parquet(D/"labels_weak_camal.parquet"); WKW.to_parquet(D/"weights_weak_camal.parquet")
    rows=[]
    for a in S.columns:
        lab=S[a]; w=Wt[a]
        rows.append(dict(appliance=a,panel=CS.SIGNATURES[a].panel[:8],
            kind=CS.SIGNATURES[a].kind, coupled=CS.SIGNATURES[a].coupled,
            det_bal_acc=round(float(det[a]["bal_acc"]),3),
            weak_windows_on=int((det[a]["p"]>=0.5).sum()), n_windows=len(det[a]["p"]),
            strong_on=int((lab==1).sum()), strong_off=int((lab==0).sum()),
            cam_confirmed=int((w>=0.5).sum()),
            pct_on=round(float((lab==1).mean()*100),2)))
    R=pd.DataFrame(rows); R.to_csv(HERE/"reports/camal_pipeline_summary.csv",index=False)
    pd.set_option("display.width",220); print(R.to_string(index=False),flush=True)
    print("DONE",flush=True)
