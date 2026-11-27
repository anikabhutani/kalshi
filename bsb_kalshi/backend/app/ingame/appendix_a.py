"""Appendix A in-game walkthrough with the sportsbook side. Run from backend/: python -m app.ingame.appendix_a <swing_id> ...
"""
import pandas as pd, numpy as np, sys
from app.task4.common import REPO_ROOT
NFL=str(REPO_ROOT/'data'/'ingame'/'nfl')+'/'
OUT=NFL+'task9/'
s=pd.read_csv(NFL+'out/swings_nfl.csv').set_index('swing_id')
a=pd.read_csv(NFL+'task8/ingame_aligned_nfl.csv')
mins={y:pd.read_csv(NFL+f'out/kalshi_minutes_nfl_{y}.csv',low_memory=False) for y in (2025,2026)}
md=['# Appendix A candidates: in-game walkthrough with the sportsbook side','',
    'Bears @ Panthers (Sep 13, 2026, 2026_01_CHI_CAR) has no swing in the Task 7 files (its normal movement was high, sigma 6.3, so the threshold was about 30 points and no move cleared it). Below are pulled swings that can stand in. Costs per $10 are in dollars; Kalshi at 24 contracts, fee rounded up to the cent per order; ruler A fair = Kalshi midpoint, ruler B fair = the book\'s Shin price.','']
allrows=[]
for sid in sys.argv[1:]:
    r=s.loc[sid]; m=mins[int(r.season)]; g=m[m.game_id==r.game_id].set_index('ts').sort_index()
    t,b,af=int(r.t_ts),int(r.before_ts),int(r.after_ts)
    w=g.loc[b-5*60:af+3*60,['minute_utc','bid','ask','mid','spread','volume_both','steady','flagged']].copy()
    w['marker']=''; w.loc[w.index==b,'marker']='BEFORE'; w.loc[w.index==t,'marker']='SWING (t)'; w.loc[w.index==af,'marker']='AFTER'
    x=a[a.swing_id==sid]
    md+= [f'## {sid}: {r.away} at {r.home}, {r.t_utc[:10]}', '',
          f'Play near t: {r.matched_play if isinstance(r.matched_play,str) else "no play within 3 min"}; home win price {r.mid_before} -> {r.mid_after} ({r.abs_move} points); threshold {r.threshold:.1f} points (sigma {r.sigma_game:.2f}); settled {int(r.minutes_to_settle)} min after t.','',
          '### Kalshi, minute by minute (home team market)','',w.to_markdown(index=False),'',
          '### Both venues at the before and after times','',]
    cols=['which','request_time_utc','book_snapshot_time','price_age_min','team','kalshi_bid','kalshi_ask','kalshi_mid','kalshi_fee','kalshi_cost_per10','book','odds','implied_p','shin_fair_p','cost_ruler_A','cost_ruler_B','kalshi_cost_ruler_B','extra_cost_A','usable']
    t2=x[cols].sort_values(['which','team','book'],ascending=[False,True,True])
    md+=[t2.round(4).to_markdown(index=False),'']
    allrows.append(t2.assign(swing_id=sid))
open(OUT+'appendix_A_candidates_nfl.md','w').write('\n'.join(md))
pd.concat(allrows).to_csv(OUT+'appendix_A_candidates_nfl.csv',index=False)
print('\n'.join(md)[:6000])
