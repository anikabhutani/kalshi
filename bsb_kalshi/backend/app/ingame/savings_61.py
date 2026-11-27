"""Section 6.1 in-game savings (NFL): in-game Kalshi dollars by price group (minute candles, contracts x price) times
the pooled in-game extra cost per $10, with the Task 9 savings rules (switcher shares 25-100%, half the saving for
new traders where Kalshi is cheaper, full amount where it costs more). Run from backend/: python -m app.ingame.savings_61
"""
import pandas as pd, numpy as np, json
from app.task4.common import REPO_ROOT
NFL=str(REPO_ROOT/'data'/'ingame'/'nfl')+'/'
OUT=NFL+'task9/'
rows=[]
for s in (2025,2026):
    m=pd.read_csv(NFL+f'out/kalshi_minutes_nfl_{s}.csv',low_memory=False)
    home_vol=np.where(m.source_market=='home', m.volume, m.volume_both-m.volume)
    away_vol=m.volume_both-home_vol
    for side,vol,price in (('home',home_vol,m['mid']),('away',away_vol,100-m['mid'])):
        rows.append(pd.DataFrame({'season':s,'game_id':m.game_id,'ts':m.ts,'side':side,'contracts':vol,'price_c':price}))
v=pd.concat(rows,ignore_index=True)
v['dollars']=v.contracts*v.price_c/100
v['price_group']=np.select([v.price_c<10,v.price_c<40,v.price_c<60,v.price_c<=90],['below 10 (not measured)','longshot','middle','favorite'],'above 90 (not measured)')
vol=v.groupby(['season','price_group']).agg(contracts=('contracts','sum'),dollars=('dollars','sum'),games=('game_id','nunique')).reset_index()
tot=v.groupby('price_group').agg(contracts=('contracts','sum'),dollars=('dollars','sum'),games=('game_id','nunique')).reset_index().assign(season='both')
vol=pd.concat([vol,tot],ignore_index=True)
vol.to_csv(OUT+'ingame_volume_by_price_group_nfl.csv',index=False)
print(vol.to_string())
D=tot.set_index('price_group')['dollars']
sm=pd.read_csv(NFL+'task8/ingame_summary_nfl.csv')
sm=sm[sm.metric=='extra_cost_A_pooled_before_after']
res=[]
for book in ('FanDuel','DraftKings'):
    for end,col in (('low','ci_low'),('middle','estimate'),('high','ci_high')):
        for share in (0.25,0.5,0.75,1.0):
            total=0; parts={}
            for g in ('longshot','middle','favorite'):
                e=float(sm[(sm.book==book)&(sm.group==f'price_group={g}')][col].iloc[0])   # cents per $10
                per_dollar=e/1000                                                            # $ saved per $ paid
                if e>0:   # Kalshi cheaper: switchers save in full, new traders count half
                    val=D[g]*per_dollar*(share+0.5*(1-share))
                else:     # Kalshi costs more: full amount, no half rule
                    val=D[g]*per_dollar
                parts[g]=val; total+=val
            res.append({'book':book,'end':end,'switcher_share':share,'savings_usd':total,**{f'{g}_usd':v_ for g,v_ in parts.items()}})
r=pd.DataFrame(res); r.to_csv(OUT+'ingame_savings_nfl.csv',index=False)
for book in ('FanDuel','DraftKings'):
    t=r[r.book==book].pivot(index='switcher_share',columns='end',values='savings_usd')[['low','middle','high']]/1e6
    print(book,'(USD millions)'); print(t.round(2).to_string())
print('measured-range dollars (10-90):', round(D[['longshot','middle','favorite']].sum()/1e6,1),'M of', round(D.sum()/1e6,1),'M')
