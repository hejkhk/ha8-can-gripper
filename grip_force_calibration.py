"""Read-only empirical HA8 current/angle -> single-FSR fingertip force reference.
Only for the same contact fixture and active closing motion. Never a motor
controller, safety interlock or verified total clamping force.
"""
from __future__ import annotations
import json
import math
from pathlib import Path
DEFAULT_PATH=Path(__file__).resolve().parent/"calibration"/"grip_force_model.json"

def number(x):
    try: v=float(x)
    except (TypeError,ValueError): return None
    return v if math.isfinite(v) else None

class ForceMap:
    def __init__(self,points,gap_points=None):
        if not isinstance(points,list) or not 18<=len(points)<=30000:
            raise ValueError("需要至少18个有效闭合样本")
        self.points=[]
        for p in points:
            if not isinstance(p,dict): raise ValueError("非法标定点")
            i,a,f=number(p.get("current_a")),number(p.get("angle_deg")),number(p.get("force_gf"))
            if i is None or a is None or f is None or not 0<=i<=3 or not 50<=f<=1000 or abs(a)>368640:
                raise ValueError("标定点越界")
            self.points.append({"current_a":i,"angle_deg":a,"force_gf":f})
        currents=[p["current_a"] for p in self.points]
        angles=[p["angle_deg"] for p in self.points]
        forces=[p["force_gf"] for p in self.points]
        self.imin,self.imax=min(currents),max(currents)
        self.amin,self.amax=min(angles),max(angles)
        if self.imax-self.imin<.04 or self.amax-self.amin<.5 or max(forces)-min(forces)<80:
            raise ValueError("样本跨度不足：需要至少0.04A、0.5度和80gf")
        self.gap_points=[]
        for p in gap_points or []:
            a,g=number(p.get("angle_deg")),number(p.get("gap_mm"))
            if a is None or g is None or not 0<=g<=1000: raise ValueError("夹口开度无效")
            self.gap_points.append({"angle_deg":a,"gap_mm":g})
        self.gap_points.sort(key=lambda p:p["angle_deg"])
        if len(self.gap_points) not in (0,2) or (len(self.gap_points)==2 and
          self.gap_points[1]["angle_deg"]-self.gap_points[0]["angle_deg"]<1):
            raise ValueError("必须提供两个相差至少1度的夹口测量点")

    @classmethod
    def train(cls,rows):
        points=[]
        for r in rows:
            if r.phase!="gripping" or r.status!=0 or r.theoretical_gf is None or not 0<=r.skew_ms<=180: continue
            i,a,f=number(r.current_a),number(r.angle_deg),number(r.theoretical_gf)
            if i is None or a is None or f is None or not 0<=i<=3 or not 50<=f<=1000: continue
            points.append({"current_a":round(i,5),"angle_deg":round(a,4),"force_gf":round(f,3)})
        return cls(points)

    def predict(self,current_a,angle_deg,phase="gripping",status=0):
        i,a=number(current_a),number(angle_deg)
        if phase!="gripping" or status!=0 or i is None or a is None: return None
        if not self.imin<=i<=self.imax or not self.amin<=a<=self.amax: return None
        di,da=self.imax-self.imin,self.amax-self.amin
        near=sorted(((((i-p["current_a"])/di)**2+((a-p["angle_deg"])/da)**2),p["force_gf"]) for p in self.points)[:7]
        if len(near)<3 or near[2][0]>.09:return None
        weights=[1/(math.sqrt(d)+.025) for d,f in near]
        return sum(w*f for w,(_,f) in zip(weights,near))/sum(weights)

    def gap_mm(self,angle):
        a=number(angle)
        if a is None or len(self.gap_points)!=2:return None
        p,q=self.gap_points
        if not p["angle_deg"]<=a<=q["angle_deg"]:return None
        t=(a-p["angle_deg"])/(q["angle_deg"]-p["angle_deg"])
        return p["gap_mm"]+t*(q["gap_mm"]-p["gap_mm"])

    def with_gaps(self,points):
        return ForceMap(self.points,points)

    def as_dict(self):
        return {"schema":1,"source":"one_fingertip_fsr_theoretical_rf158k",
          "independently_force_validated":False,"use":"read_only_gripping_motion_only",
          "gear":{"module_mm":1,"wheel_teeth":20,"worm_starts":None,"external_ratio":None,
                  "servo_internal_ratio":378},
          "points":self.points,"gap_points":self.gap_points}

    def save(self,path=DEFAULT_PATH):
        path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(self.as_dict(),ensure_ascii=False,indent=2),encoding="utf-8")

    @classmethod
    def load(cls,path=DEFAULT_PATH):
        data=json.loads(Path(path).read_text(encoding="utf-8"))
        if (data.get("schema")!=1 or data.get("source")!="one_fingertip_fsr_theoretical_rf158k"
            or data.get("independently_force_validated") is not False):
            raise ValueError("不匹配的离线模型")
        return cls(data["points"],data.get("gap_points",[]))
