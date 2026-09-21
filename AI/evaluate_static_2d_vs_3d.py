"""Compare legacy 2D and stored world-3D static hand shape distances."""
import json
import time
from pathlib import Path
import numpy as np
from hands import normalize_landmarks, pose_distances
from static_hand_shape import hand_shape, shape_distances


def main():
    rows = json.loads((Path(__file__).resolve().parent/'testdata/builtin_finger_poses.json').read_text())['cases']
    xy = {r['source']: normalize_landmarks(np.asarray(r['landmarks'][0])[:, :2]) for r in rows}
    world = {r['source']: hand_shape(r['world'][0]) for r in rows}
    positive_2d=[]; positive_3d=[]
    transforms=[np.diag([-1,1,1]), np.diag([-1,1,-1]), np.array([[0,0,1],[0,1,0],[-1,0,0]])]
    for r in rows:
        f=xy[r['source']]
        # A reflected feature is the representation used by runtime pose_distances.
        mirrored=f.copy(); mirrored[0::2]*=-1
        positive_2d.append(float(pose_distances(np.asarray([f]), mirrored)[0]))
        for matrix in transforms:
            transformed=hand_shape(np.asarray(r['world'][0])@matrix*3+4)
            positive_3d.append(float(shape_distances(np.asarray([world[r['source']]]), transformed)[0]))
    names=['peace','one','rock','two_up','middle_finger','three2','fist','palm','call','grip','four']
    neg2=[]; neg3=[]
    for i,a in enumerate(names):
        for b in names[i+1:]:
            neg2.append(float(pose_distances(np.asarray([xy[a]]),xy[b])[0]))
            neg3.append(float(shape_distances(np.asarray([world[a]]),world[b])[0]))
    timing2=[]; timing3=[]
    for _ in range(1000):
        start=time.perf_counter(); pose_distances(np.asarray(list(xy.values())),xy['peace']); timing2.append((time.perf_counter()-start)*1000)
        start=time.perf_counter(); shape_distances(np.asarray(list(world.values())),world['peace']); timing3.append((time.perf_counter()-start)*1000)
    report=dict(threshold_registration=.45, threshold_execution=.35, positive_transform_trials_2d=len(positive_2d),
                positive_transform_matches_2d=sum(x<=.35 for x in positive_2d),
                positive_transform_trials_3d=len(positive_3d), positive_transform_matches_3d=sum(x<=.35 for x in positive_3d),
                negative_shape_pairs=len(neg2), false_duplicate_pairs_2d=sum(x<.45 for x in neg2),
                false_duplicate_pairs_3d=sum(x<.45 for x in neg3), minimum_negative_distance_2d=min(neg2),
                minimum_negative_distance_3d=min(neg3), p50_ms_2d=float(np.percentile(timing2,50)),
                p95_ms_2d=float(np.percentile(timing2,95)), p50_ms_3d=float(np.percentile(timing3,50)),
                p95_ms_3d=float(np.percentile(timing3,95)), iterations=1000,
                limitation='Stored finger-pose coordinates and synthetic transforms; not live camera accuracy.')
    out=Path(__file__).resolve().parent.parent/'Docs/static-2d-vs-3d-evaluation.json'; out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
