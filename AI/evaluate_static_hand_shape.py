"""Offline geometry checks; transformed samples are not new camera trials."""
import json
import time
from pathlib import Path
import numpy as np
from static_hand_shape import hand_shape, shape_distances


def main():
    root = Path(__file__).resolve().parent
    rows = json.loads((root/'testdata/builtin_finger_poses.json').read_text())['cases']
    features = {r['source']: hand_shape(r['world'][0]) for r in rows}
    positives = []
    for row in rows:
        for matrix in [np.diag([-1,1,1]), np.diag([-1,1,-1]),
                       np.array([[0,0,1],[0,1,0],[-1,0,0]])]:
            query = hand_shape((np.asarray(row['world'][0])@matrix)*3 + 4)
            positives.append(float(shape_distances(features[row['source']], query)))
    names = ['peace','one','rock','two_up','middle_finger','three2',
             'fist','palm','call','grip','four']
    negatives = [dict(a=a,b=b,distance=float(shape_distances(features[a],features[b])))
                 for i,a in enumerate(names) for b in names[i+1:]]
    timings=[]
    templates=np.asarray(list(features.values()))
    for _ in range(1000):
        start=time.perf_counter()
        query=hand_shape(rows[0]['world'][0])
        shape_distances(templates,query)
        timings.append((time.perf_counter()-start)*1000)
    report=dict(source='testdata/builtin_finger_poses.json',
                transformed_positive_trials=len(positives),
                transformed_positive_matches=sum(d<=.35 for d in positives),
                distinct_shape_pairs=len(negatives),
                false_duplicate_pairs=sum(p['distance']<.45 for p in negatives),
                minimum_distinct_shape_distance=min(p['distance'] for p in negatives),
                geometry_ms_p50=float(np.percentile(timings,50)),
                geometry_ms_p95=float(np.percentile(timings,95)),
                timing_iterations=1000,templates_per_iteration=len(templates),
                negatives=negatives,
                limitation='Synthetic transforms of stored coordinates; not live recognition accuracy.')
    out=root.parent/'Docs/custom-static-shape-evaluation.json'
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='negatives'},indent=2))


if __name__=='__main__': main()
