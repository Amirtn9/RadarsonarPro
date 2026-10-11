"""Separate connectivity health from server capacity. No LLM/paid service needed."""
from math import isfinite

def _clamp(n, low, high): return max(low,min(high,n))

def score_config(ping, jitter, ok, uptime_percent=None, download_mbps=None):
    if not ok:return 0
    try: p=float(ping); j=float(jitter)
    except (ValueError,TypeError):return 0
    if not all(isfinite(n) for n in (p,j)) or p<=0 or j<0:return 0
    latency=_clamp(100-(p-30)*.18,0,100)
    stability=_clamp(100-j*1.5,0,100)
    parts=[(latency,.60),(stability,.40)]
    if uptime_percent is not None:
        up=_clamp(float(uptime_percent),0,100)
        parts=[(latency,.45),(stability,.30),(up,.25)]
    score=sum(value*weight for value,weight in parts)
    if download_mbps is not None and download_mbps>0:
        score=.9*score+.1*_clamp(float(download_mbps)*5,0,100)
    return round(_clamp(score,0,100),1)


def likely_cause(iran_ok,external_ok):
    if iran_ok is False and external_ok is True:return 'احتمال اختلال مسیر ایران؛ نیازمند بررسی از نقاط مستقل'
    if iran_ok is False and external_ok is False:return 'احتمال اختلال مشترک سرویس یا زیرساخت؛ نیازمند بررسی بیشتر'
    if iran_ok is True and external_ok is False:return 'احتمال اختلال مسیر خارج؛ نیازمند بررسی بیشتر'
    return 'شواهد کافی برای تشخیص علت وجود ندارد'
